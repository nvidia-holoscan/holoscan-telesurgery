# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stop real native processes and exercise Docker discovery without touching user services."""

import json
import os
import select
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from telesurgery.application import lifecycle


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setattr(lifecycle, "docker_instances", lambda workspace: iter(()))
    processes = []

    def start(workspace, role="patient", instance="8000", *, ignore_term=False, legacy=False):
        directory = workspace / (f"nodes/{instance}" if role == "node" else f"{role}-{instance}")
        code = textwrap.dedent("""\
            import contextlib, fcntl, pathlib, signal, sys, time
            from telesurgery.application.lifecycle import register
            role, directory, instance, ignore, legacy = sys.argv[1:]
            directory = pathlib.Path(directory)
            directory.mkdir(parents=True)
            stopped = False
            def stop(*args):
                global stopped
                stopped = True
            signal.signal(signal.SIGTERM, signal.SIG_IGN if ignore == 'True' else stop)
            with (directory / 'service.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                context = (
                    contextlib.nullcontext() if legacy == 'True'
                    else register(directory, role, instance)
                )
                with context:
                    print('ready', flush=True)
                    while not stopped:
                        signal.pause()
                    time.sleep(0.05)
                    (directory / 'cleaned').touch()
        """)
        module = workspace / "fixture"
        module.mkdir(parents=True, exist_ok=True)
        # Use the real command shape for legacy discovery, without importing any GPU runtime.
        if legacy:
            code = code.replace("from telesurgery.application.lifecycle import register", "")
            (module / "telesurgery.py").write_text(code)
        command = ["-m", "telesurgery"] if legacy else ["-c", code]
        process = subprocess.Popen(
            [
                sys.executable,
                *command,
                role,
                str(directory),
                instance,
                str(ignore_term),
                str(legacy),
            ],
            cwd=module if legacy else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "TELESURGERY_CONTAINER": "", "TELESURGERY_LOG": "/test/service.log"},
        )
        processes.append(process)
        assert select.select([process.stdout], [], [], 10)[0], "service did not start"
        assert process.stdout.readline() == b"ready\n", process.stderr.read().decode()
        return process, directory

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_status_and_graceful_stop(services, tmp_path, capsys):
    process, directory = services(tmp_path)
    assert lifecycle.main(["status", "--workspace", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert f"patient 8000 (native {process.pid})" in output
    assert "/test/service.log" in output
    assert (directory / "service.json").stat().st_mode & 0o777 == 0o600
    assert lifecycle.main(["stop", "patient", "--workspace", str(tmp_path)]) == 0
    assert process.wait(timeout=5) == 0
    assert (directory / "cleaned").exists()
    assert not (directory / "service.json").exists()
    assert lifecycle.main(["stop", "patient", "--workspace", str(tmp_path)]) == 0
    assert "Already stopped" in capsys.readouterr().out


def test_selection_and_workspace_scope(services, tmp_path, capsys):
    workspace = tmp_path / "selected workspace"
    one, _ = services(workspace, "surgeon", "8002")
    two, _ = services(workspace, "surgeon", "8003")
    patient, _ = services(workspace)
    node, _ = services(workspace, "node", "room-mira")
    other, _ = services(tmp_path / "other")
    options = ["--workspace", str(workspace)]
    assert lifecycle.main(["stop", "surgeon", *options]) == 1
    assert "Multiple instances" in capsys.readouterr().err
    assert one.poll() is None and two.poll() is None
    assert lifecycle.main(["stop", "surgeon", "--port", "8003", *options]) == 0
    assert two.wait(timeout=5) == 0
    assert one.poll() is None
    assert lifecycle.main(["stop", "node", "--name", "room-mira", *options]) == 0
    assert node.wait(timeout=5) == 0
    assert patient.poll() is None
    assert lifecycle.main(["stop", "--all", *options]) == 0
    assert one.wait(timeout=5) == patient.wait(timeout=5) == 0
    assert other.poll() is None


@pytest.mark.parametrize("field,value", [("start", "wrong"), ("boot", "old-boot")])
def test_stale_record_never_signals_reused_pid(services, tmp_path, field, value):
    process, _ = services(tmp_path / "unrelated")
    workspace = tmp_path / "stale"
    directory = workspace / "patient-8000"
    directory.mkdir(parents=True)
    (directory / "service.lock").touch()
    record = {
        **lifecycle.host_identity(),
        **lifecycle.process_identity(process.pid),
        "role": "patient",
        "instance": "8000",
        field: value,
    }
    path = directory / "service.json"
    path.write_text(json.dumps(record))
    assert lifecycle.main(["stop", "patient", "--force", "--workspace", str(workspace)]) == 0
    assert process.poll() is None
    assert not path.exists()


def test_recheck_identity_after_discovery(services, tmp_path):
    process, _ = services(tmp_path)
    (item,) = lifecycle.native_instances(tmp_path)
    item["start"] = "reused-pid"
    lifecycle.stop_native(item, 0.01, True)
    assert process.poll() is None


@pytest.mark.parametrize("role,instance", [("surgeon", "8002"), ("node", "room-mira")])
def test_preexisting_native_service_can_be_found_and_stopped(services, tmp_path, role, instance):
    process, directory = services(tmp_path, role, instance, legacy=True)
    assert not (directory / "service.json").exists()
    (item,) = lifecycle.native_instances(tmp_path)
    assert item["legacy"] and item["pid"] == process.pid
    assert item["role"] == role and item["instance"] == instance
    assert lifecycle.main(["stop", role, "--workspace", str(tmp_path)]) == 0
    assert process.wait(timeout=5) == 0
    assert (directory / "cleaned").exists()


def test_legacy_stop_rechecks_lock_owner(services, tmp_path, monkeypatch):
    process, _ = services(tmp_path, legacy=True)
    (item,) = lifecycle.native_instances(tmp_path)
    monkeypatch.setattr(lifecycle, "lock_owners", lambda: {})
    lifecycle.stop_native(item, 0.01, True)
    assert process.poll() is None


def test_timeout_and_explicit_force(services, tmp_path, capsys):
    process, directory = services(tmp_path, ignore_term=True)
    options = ["stop", "patient", "--workspace", str(tmp_path), "--timeout", "0.02"]
    assert lifecycle.main(options) == 1
    assert "still running" in capsys.readouterr().err
    assert process.poll() is None
    assert lifecycle.main([*options, "--force"]) == 0
    assert process.wait(timeout=5) == -signal.SIGKILL
    assert not (directory / "cleaned").exists()
    assert not (directory / "service.json").exists()


def test_standalone_python_on_older_libc_uses_pidfd_syscalls(services, tmp_path, monkeypatch):
    process, _ = services(tmp_path)
    libc = lifecycle.ctypes.CDLL(None, use_errno=True)
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)
    monkeypatch.setattr(
        lifecycle.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(syscall=libc.syscall)
    )
    assert lifecycle.main(["stop", "patient", "--workspace", str(tmp_path)]) == 0
    assert process.wait(timeout=5) == 0


def test_container_never_registers_host_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("TELESURGERY_CONTAINER", "1")
    with lifecycle.register(tmp_path, "node", "room"):
        assert not (tmp_path / "service.json").exists()


@pytest.fixture
def docker_services(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(lifecycle.shutil, "which", lambda command: "/mock/docker")
    containers, calls = {}, []

    def add(identifier, *, role="node", instance="room", workspace=tmp_path, uid=None):
        containers[identifier] = {
            "Id": identifier,
            "State": {"Running": True},
            "Config": {
                "Labels": {
                    f"{lifecycle.LABEL}.role": role,
                    f"{lifecycle.LABEL}.instance": instance,
                    f"{lifecycle.LABEL}.workspace": str(workspace),
                    f"{lifecycle.LABEL}.uid": str(os.getuid() if uid is None else uid),
                }
            },
        }

    def docker(*args):
        calls.append(args)
        if args[0] == "context":
            return "unix:///var/run/docker.sock"
        if args[0] == "ps":
            return "\n".join(
                json.dumps({"ID": identifier, "Image": "holoscan-telesurgery:0.1.0"})
                for identifier in containers
            )
        if args[0] == "inspect":
            return json.dumps([containers[args[1]]]) if args[1] in containers else "[]"
        if args[0] == "kill":
            container = containers[args[-1]]
            if args[2] == "KILL" or not container.get("ignore_term"):
                del containers[args[-1]]  # --rm removes the exited application container.
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(lifecycle, "docker", docker)
    return add, containers, calls


def test_docker_discovery_and_graceful_stop(docker_services, tmp_path, capsys):
    add, containers, calls = docker_services
    add("node-container")
    add("another-workspace", workspace=tmp_path / "other")
    add("another-user", uid=os.getuid() + 1)
    add("unrelated-role", role="simulation")
    options = ["--workspace", str(tmp_path)]
    assert lifecycle.main(["status", *options]) == 0
    assert "node room (docker node-contain)" in capsys.readouterr().out
    assert lifecycle.main(["stop", "node", "--name", "room", *options]) == 0
    assert ("kill", "--signal", "TERM", "node-container") in calls
    assert set(containers) == {"another-workspace", "another-user", "unrelated-role"}
    assert all(call[0] in {"context", "ps", "inspect", "kill"} for call in calls)


def test_docker_force_is_opt_in(docker_services, tmp_path):
    add, containers, calls = docker_services
    add("stuck-container")
    containers["stuck-container"]["ignore_term"] = True
    options = ["stop", "node", "--timeout", "0.01", "--workspace", str(tmp_path)]
    assert lifecycle.main(options) == 1
    assert not any("KILL" in call for call in calls)
    assert lifecycle.main([*options, "--force"]) == 0
    assert ("kill", "--signal", "KILL", "stuck-container") in calls
    assert not containers


def test_preexisting_docker_service_scope(docker_services, tmp_path):
    add, containers, calls = docker_services
    add("old-launcher")
    containers["old-launcher"].update(
        Config={
            "Entrypoint": ["python", "-m", "telesurgery"],
            "Cmd": ["node", "--patient", "localhost", "--sim=mira"],
            "User": f"{os.getuid()}:{os.getgid()}",
            "Hostname": "workstation",
            "WorkingDir": "/project",
        },
        Mounts=[{"Source": str(tmp_path), "Destination": "/project/workspace"}],
    )
    (item,) = lifecycle.docker_instances(tmp_path)
    assert item["role"] == "node" and item["instance"] == "workstation-mira"
    assert not list(lifecycle.docker_instances(tmp_path / "other"))
    assert lifecycle.main(["stop", "node", "--workspace", str(tmp_path)]) == 0
    assert ("kill", "--signal", "TERM", "old-launcher") in calls


@pytest.mark.parametrize("endpoint", ["ssh://remote-host", "tcp://10.137.144.162:2376"])
def test_remote_docker_host_is_never_contacted(docker_services, tmp_path, monkeypatch, endpoint):
    _, _, calls = docker_services
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    with pytest.raises(RuntimeError, match="Remote Docker endpoints"):
        list(lifecycle.docker_instances(tmp_path))
    assert not calls


def test_remote_docker_context_takes_precedence_over_local_host(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle.shutil, "which", lambda command: "/mock/docker")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    calls = []

    def docker(*args):
        calls.append(args)
        assert args[:3] == ("context", "inspect", "remote")
        return "ssh://remote-host"

    monkeypatch.setattr(lifecycle, "docker", docker)
    with pytest.raises(RuntimeError, match="Remote Docker endpoints"):
        list(lifecycle.docker_instances(tmp_path))
    assert len(calls) == 1


def test_docker_failure_reported_while_native_stop_completes(
    services, tmp_path, monkeypatch, capsys
):
    process, _ = services(tmp_path)

    def unavailable(workspace):
        raise RuntimeError("daemon unavailable")

    monkeypatch.setattr(lifecycle, "docker_instances", unavailable)
    assert lifecycle.main(["stop", "--all", "--workspace", str(tmp_path)]) == 1
    assert process.wait(timeout=5) == 0
    assert "daemon unavailable" in capsys.readouterr().err


def test_run_management_without_sdk_or_image(tmp_path, services):
    process, directory = services(tmp_path, "surgeon", "8012")
    root = Path(__file__).parents[2]
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    # An empty Docker installation, and no SDK Python. No build or launch is permitted.
    docker = bin_path / "docker"
    docker.write_text(
        '#!/bin/sh\ncase "$1" in\n'
        'context) echo "unix:///var/run/docker.sock";;\nps) ;;\n*) exit 90;;\nesac\n'
    )
    docker.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(bin_path) + os.pathsep + os.environ["PATH"],
        "TELESURGERY_PYTHON": "/does/not/exist",
    }
    for command in (["status"], ["stop", "--all"]):
        result = subprocess.run(
            ["bash", str(root / "run.sh"), "--docker", *command, "--workspace", str(tmp_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        if command == ["status"]:
            assert f"surgeon 8012 (native {process.pid})" in result.stdout
    assert process.wait(timeout=5) == 0
    assert (directory / "cleaned").exists()
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize(
    "options",
    [[], ["node", "--port", "8000"], ["patient", "--name", "room"], ["--all", "--timeout", "nan"]],
)
def test_invalid_stop_arguments(options):
    with pytest.raises(SystemExit) as exc:
        lifecycle.main(["stop", *options])
    assert exc.value.code == 2
