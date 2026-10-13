# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local service discovery and shutdown. Uses only the Python standard library."""

import argparse
import contextlib
import ctypes
import fcntl
import json
import math
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LABEL = "com.nvidia.telesurgery"
ROLES = ("patient", "surgeon", "node")


def host_identity():
    return {
        "machine": Path("/etc/machine-id").read_text().strip(),
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "namespace": os.readlink("/proc/self/ns/pid"),
    }


def process_identity(pid):
    try:
        directory = Path("/proc") / str(pid)
        fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X"}:
            return None
        return {"pid": pid, "start": fields[19], "uid": directory.stat().st_uid}
    except (FileNotFoundError, ProcessLookupError):
        return None


def remove_record(path, record, *, locked=False):
    # A new service may have acquired the lock since this instance exited.
    if not locked:
        try:
            with (path.parent / "service.lock").open() as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                remove_record(path, record, locked=True)
        except FileNotFoundError:
            pass
        return
    try:
        if json.loads(path.read_text()) == record:
            path.unlink(missing_ok=True)
    except (FileNotFoundError, ValueError):
        pass


@contextlib.contextmanager
def register(directory, role, instance):
    """Register while the caller holds service.lock; container labels track Docker."""
    if os.environ.get("TELESURGERY_CONTAINER") == "1":
        yield
        return
    directory = Path(directory)
    record = {
        **host_identity(),
        **process_identity(os.getpid()),
        "role": role,
        "instance": str(instance),
        "log": os.environ.get("TELESURGERY_LOG", ""),
    }
    path = directory / "service.json"
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".service-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream)
        os.replace(temporary, path)
        try:
            yield
        finally:
            remove_record(path, record, locked=True)
    finally:
        Path(temporary).unlink(missing_ok=True)


def native_instances(workspace):
    host = host_identity()
    tracked = set()
    for pattern in ("patient-*/service.json", "surgeon-*/service.json", "nodes/*/service.json"):
        for path in sorted(workspace.glob(pattern)):
            try:
                record = json.loads(path.read_text())
            except FileNotFoundError:
                continue
            if not isinstance(record, dict) or record.get("role") not in ROLES:
                raise ValueError(f"Invalid service record: {path}")
            if record.get("machine") != host["machine"] or record.get("uid") != os.getuid():
                continue
            # A reboot leaves stale records; another PID namespace must never be signalled.
            if record.get("boot") != host["boot"]:
                remove_record(path, record)
                continue
            if record.get("namespace") != host["namespace"]:
                continue
            expected = {key: record[key] for key in ("pid", "start", "uid")}
            if process_identity(record["pid"]) != expected:
                remove_record(path, record)
                continue
            tracked.add(path.parent)
            yield {**record, "mode": "native", "path": path, "record": record}
    # Existing services already own an exclusive service.lock, even before tracking was added.
    owners = lock_owners()
    for pattern in ("patient-*/service.lock", "surgeon-*/service.lock", "nodes/*/service.lock"):
        for lock in sorted(workspace.glob(pattern)):
            if lock.parent in tracked:
                continue
            pid = owners.get(lock_key(lock))
            if pid is None:
                continue
            process = process_identity(pid)
            if not process or process["uid"] != os.getuid():
                continue
            try:
                namespace = os.readlink(f"/proc/{pid}/ns/pid")
                argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, ProcessLookupError):
                continue
            if namespace != host["namespace"]:
                continue
            role, instance = (
                ("node", lock.parent.name)
                if lock.parent.parent.name == "nodes"
                else lock.parent.name.split("-", 1)
            )
            if argv[1:4] != [b"-m", b"telesurgery", role.encode()]:
                continue
            yield {
                **host,
                **process,
                "role": role,
                "instance": instance,
                "mode": "native",
                "lock": lock,
                "legacy": True,
            }


def lock_key(path):
    info = path.stat()
    return os.major(info.st_dev), os.minor(info.st_dev), info.st_ino


def lock_owners():
    owners = {}
    for line in Path("/proc/locks").read_text().splitlines():
        fields = line.split()
        if fields[1:4] == ["FLOCK", "ADVISORY", "WRITE"]:
            major, minor, inode = fields[5].split(":")
            owners[int(major, 16), int(minor, 16), int(inode)] = int(fields[4])
    return owners


def docker(*args):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=10, check=False
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        if args[0] == "inspect" and any(
            missing in message.lower() for missing in ("no such object:", "no such container:")
        ):
            return "[]"
        raise RuntimeError(message or f"docker {args[0]} failed")
    return result.stdout


def docker_instances(workspace):
    if not shutil.which("docker"):
        return
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = os.environ.get("DOCKER_HOST")
    if context or not endpoint:
        endpoint = docker(
            "context",
            "inspect",
            *([context] if context else []),
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        ).strip()
    if not endpoint.startswith("unix://"):
        raise RuntimeError("Remote Docker endpoints are excluded; run this command on that host")
    rows = docker("ps", "--no-trunc", "--format", "{{json .}}").splitlines()
    for row in rows:
        summary = json.loads(row)
        if summary["Image"].split(":", 1)[
            0
        ] != "holoscan-telesurgery" and f"{LABEL}.role=" not in summary.get("Labels", ""):
            continue
        for info in json.loads(docker("inspect", summary["ID"])):
            labels = info["Config"].get("Labels") or {}
            role = labels.get(f"{LABEL}.role")
            if (
                role in ROLES
                and labels.get(f"{LABEL}.workspace") == str(workspace)
                and labels.get(f"{LABEL}.uid") == str(os.getuid())
                and info["State"]["Running"]
            ):
                yield {
                    "role": role,
                    "instance": labels[f"{LABEL}.instance"],
                    "mode": "docker",
                    "container": info["Id"],
                    "log": labels.get(f"{LABEL}.log", ""),
                }
            elif f"{LABEL}.workspace" not in labels:
                legacy = legacy_container(info, workspace)
                if legacy:
                    yield legacy


def option(argv, name, default):
    value = default
    for index, argument in enumerate(argv):
        if argument == name:
            value = argv[index + 1]
        elif argument.startswith(name + "="):
            value = argument.split("=", 1)[1]
    return value


def legacy_container(info, workspace):
    """Recognize older launcher containers by entrypoint, user and exact workspace mount."""
    config = info["Config"]
    argv = config.get("Cmd") or []
    if (
        config.get("Entrypoint") != ["python", "-m", "telesurgery"]
        or config.get("User", "").split(":", 1)[0] != str(os.getuid())
        or not argv
        or argv[0] not in ROLES
        or not info["State"]["Running"]
    ):
        return None
    directory = str(
        Path(config.get("WorkingDir") or "/") / option(argv, "--workspace", "workspace")
    )
    if not any(
        mount["Destination"] == directory and Path(mount["Source"]).resolve() == workspace
        for mount in info.get("Mounts", [])
    ):
        return None
    role = argv[0]
    if role == "node":
        sim = option(argv, "--sim", "")
        instance = option(argv, "--name", config["Hostname"] + (f"-{sim}" if sim else ""))
    else:
        instance = str(int(option(argv, "--port", "8000" if role == "patient" else "8002")))
    return {"role": role, "instance": instance, "mode": "docker", "container": info["Id"]}


def describe(item):
    identifier = str(item["pid"]) if item["mode"] == "native" else item["container"][:12]
    return f"{item['role']} {item['instance']} ({item['mode']} {identifier})"


def show(instances):
    for item in instances:
        print(f"Running: {describe(item)}")
        if item.get("log"):
            print(f"  Log: {item['log']}")


def pidfd_call(name, *args):
    # Some standalone Python builds omit pidfd bindings despite host libc support.
    python = getattr(os if name == "pidfd_open" else signal, name, None)
    if python is not None:
        return python(*args)
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, name, None)
    if function is None:
        if os.uname().machine not in {"x86_64", "aarch64"}:
            raise RuntimeError("Stopping native services requires Linux pidfd support")
        # Linux UAPI numbers shared by x86-64 and ARM64; Ubuntu 22.04 libc lacks wrappers.
        function = libc.syscall
        args = ({"pidfd_open": 434, "pidfd_send_signal": 424}[name], *args)
    result = function(*args)
    if result == -1:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def stop_native(item, timeout, force):
    try:
        fd = pidfd_call("pidfd_open", item["pid"], 0)
    except ProcessLookupError:
        return
    try:
        # Open first, then check identity: pidfd keeps the signal bound to this process.
        expected = {key: item[key] for key in ("pid", "start", "uid")}
        if process_identity(item["pid"]) != expected:
            return
        if item.get("legacy") and lock_owners().get(lock_key(item["lock"])) != item["pid"]:
            return
        try:
            pidfd_call("pidfd_send_signal", fd, signal.SIGTERM, None, 0)
            if not select.select([fd], [], [], timeout)[0]:
                if not force:
                    raise TimeoutError(
                        "still running; retry with --force to kill after the timeout"
                    )
                print(f"Force killing: {describe(item)}", flush=True)
                pidfd_call("pidfd_send_signal", fd, signal.SIGKILL, None, 0)
                if not select.select([fd], [], [], 5)[0]:
                    raise TimeoutError("still running after SIGKILL")
        except ProcessLookupError:
            pass
    finally:
        os.close(fd)
    if not item.get("legacy"):
        remove_record(item["path"], item["record"])


def container_running(container):
    return any(info["State"]["Running"] for info in json.loads(docker("inspect", container)))


def signal_container(container, number):
    try:
        docker("kill", "--signal", number, container)
    except RuntimeError:
        if container_running(container):
            raise


def wait_container(container, timeout):
    deadline = time.monotonic() + timeout
    while container_running(container):
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    return True


def stop_docker(item, timeout, force):
    container = item["container"]
    if not container_running(container):
        return
    # docker stop forcibly kills on timeout; only escalate when --force was requested.
    signal_container(container, "TERM")
    if wait_container(container, timeout):
        return
    if not force:
        raise TimeoutError("still running; retry with --force to kill after the timeout")
    print(f"Force killing: {describe(item)}", flush=True)
    signal_container(container, "KILL")
    if not wait_container(container, 5):
        raise TimeoutError("still running after SIGKILL")


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive number of seconds")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="./run.sh", description="Manage local telesurgery services"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "stop"):
        sub = commands.add_parser(command)
        sub.add_argument("role", choices=ROLES, nargs="?")
        sub.add_argument("--workspace", type=Path, default=Path("workspace"))
        sub.add_argument("--port", type=int, help="select a patient or surgeon dashboard")
        sub.add_argument("--name", help="select a node")
        if command == "stop":
            sub.add_argument("--all", action="store_true", help="stop all matching local services")
            sub.add_argument(
                "--timeout", type=positive_seconds, default=30, help="grace period (30s)"
            )
            sub.add_argument(
                "--force", action="store_true", help="kill if the grace period expires"
            )
    args = parser.parse_args(argv)
    if args.port is not None and (
        args.role not in {"patient", "surgeon"} or not 1 <= args.port <= 65535
    ):
        parser.error("--port requires patient or surgeon and a port between 1 and 65535")
    if args.name is not None and args.role != "node":
        parser.error("--name requires node")
    if args.command == "stop" and not (args.role or args.all):
        parser.error("choose patient, surgeon, node, or --all")
    workspace = args.workspace.expanduser().resolve()
    instances, errors = [], []
    for discover in (native_instances, docker_instances):
        try:
            instances.extend(discover(workspace))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
            source = "native services" if discover == native_instances else "Docker"
            errors.append(f"Could not check {source}: {exc}")
    instances = [
        item
        for item in instances
        if (args.role is None or item["role"] == args.role)
        and (args.port is None or item["instance"] == str(args.port))
        and (args.name is None or item["instance"] == args.name)
    ]
    instances.sort(
        key=lambda item: (("surgeon", "node", "patient").index(item["role"]), item["instance"])
    )
    for error in errors:
        print(error, file=sys.stderr)
    if args.command == "status":
        show(instances)
        if not instances:
            print(f"No tracked services running in {workspace}.")
        return int(bool(errors))
    if len(instances) > 1 and not args.all:
        show(instances)
        print("Multiple instances match; select --port / --name, or use --all.", file=sys.stderr)
        return 1
    if not instances:
        print(
            "No matching services found; discovery was incomplete."
            if errors
            else "Already stopped (no matching tracked service)."
        )
    failed = bool(errors)
    for item in instances:
        print(f"Stopping: {describe(item)}", flush=True)
        try:
            stop = stop_native if item["mode"] == "native" else stop_docker
            stop(item, args.timeout, args.force)
            print(f"Stopped: {describe(item)}", flush=True)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"Failed to stop {describe(item)}: {exc}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
