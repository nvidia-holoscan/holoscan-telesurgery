# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persist physical device profiles and resolve them for a named node."""

import fcntl
import ipaddress
import logging
import sys
from copy import deepcopy

from telesurgery_core.configuration import load, save
from telesurgery_robots.mira.binary import install


def _address(value):
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback:
        raise ValueError("Use a non-loopback IPv4 address for the physical robot network")
    return str(address)


def _mira(workspace, profile, source, pod_interface):
    if not profile:
        profile = {
            "robot": {
                "id": "mira",
                "name": "MIRA",
                "kind": "mira",
                "uri": "ws://127.0.0.1:8081",
                "motion_enabled": True,
                "controller": {"pod_interface": "192.168.0.1"},
            }
        }
    settings = profile["robot"]["controller"]
    if pod_interface is not None:
        settings["pod_interface"] = _address(pod_interface)
    else:
        _address(settings["pod_interface"])
    default = workspace / "mira-api"
    if source is None:
        if default.is_file():
            source = default
        elif sys.stdin.isatty():
            try:
                source = input("Path to the vendor MIRA API executable: ").strip()
            except EOFError as exc:
                raise ValueError("MIRA API input cancelled; use --mira-api PATH") from exc
            if not source:
                raise ValueError("MIRA API path is required; use --mira-api PATH")
        else:
            raise ValueError(
                "MIRA needs the vendor API executable: use --mira-api PATH "
                "or copy the binary to workspace/mira-api (under --workspace)"
            )
    settings.update(install(workspace, source))
    return profile


def prepare(workspace, directory, names=None, *, mira_api=None, pod_interface=None, franka_ip=None):
    """Prepare configuration only; vendor startup remains a patient dashboard action."""
    previous = load(directory / "profiles.yaml")
    names = previous.get("selected", []) if names is None else names
    if names == ["none"]:
        names = []
    if len(names) != len(set(names)) or any(name not in {"mira", "franka"} for name in names):
        raise ValueError("Select each profile once; --profile none must be used alone")
    if (mira_api is not None or pod_interface is not None) and "mira" not in names:
        raise ValueError("MIRA settings require --profile mira or a saved MIRA profile selection")
    if franka_ip is not None and "franka" not in names:
        raise ValueError("--franka-address requires --profile franka or a saved Franka selection")
    if not names and not previous:
        return
    root = workspace / "profiles"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prepared, robots = {}, []
        for name in names:
            profile = load(root / f"{name}.yaml")
            if profile and (
                not isinstance(profile.get("robot"), dict)
                or (name == "mira" and not isinstance(profile["robot"].get("controller"), dict))
            ):
                raise ValueError(f"Invalid robot settings in {root / f'{name}.yaml'}")
            if name == "mira":
                profile = _mira(workspace, profile, mira_api, pod_interface)
            else:
                if not profile:
                    profile = {
                        "robot": {
                            "id": "franka",
                            "name": "Franka",
                            "kind": "franka",
                            "motion_enabled": True,
                        }
                    }
                if franka_ip is not None:
                    profile["robot"]["address"] = _address(franka_ip)
                _address(profile["robot"].setdefault("address", "172.16.0.3"))
            spec = deepcopy(profile["robot"])
            if spec.get("kind") != name or not isinstance(spec.get("id"), str) or not spec["id"]:
                raise ValueError(f"Invalid robot kind or id in {root / f'{name}.yaml'}")
            spec.pop("connection_enabled", None)
            spec["profile"] = name
            if "executable" in spec.get("controller", {}):
                spec["controller"]["executable"] = str(
                    (workspace / spec["controller"]["executable"]).resolve()
                )
            prepared[name] = profile
            robots.append(spec)
        manual = load(directory / "devices.yaml").get("robots", [])
        ids = [item["id"] for item in [*manual, *robots]]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate robot id across profiles and devices.yaml; remove the matching "
                "manual entry or assign distinct ids in workspace/profiles/"
            )
        # Preserve connection choices only for unchanged device settings. A new profile,
        # endpoint or API version always requires a fresh Connect on the patient dashboard.
        connections = load(directory / "connections.yaml")
        old = {item["id"]: item for item in previous.get("robots", [])}
        for spec in robots:
            if old.get(spec["id"]) != spec:
                connections[spec["id"]] = False
        for name, profile in prepared.items():
            save(root / f"{name}.yaml", profile)
        save(directory / "connections.yaml", connections)
        save(directory / "profiles.yaml", {"selected": names, "robots": robots})
        if names:
            logging.info("Node device profiles: %s", ", ".join(names))


def devices(directory):
    """Return saved profile devices with node-local connection state."""
    connections = load(directory / "connections.yaml")
    return [
        {**spec, "connection_enabled": connections.get(spec["id"], False)}
        for spec in load(directory / "profiles.yaml").get("robots", [])
    ]
