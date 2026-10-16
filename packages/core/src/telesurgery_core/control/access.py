# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patient-owned admission and exclusive robot control, independent of UI and SDK."""

import hashlib
import re
import secrets
import time
from dataclasses import asdict, dataclass

from telesurgery_core.configuration import load, save


@dataclass
class Surgeon:
    id: str
    name: str
    requested_robot: bool
    status: str = "pending"
    robot: bool = False


class Access:
    def __init__(self, path=None):
        self.surgeons = {}
        self.identities = {}
        self.path = path
        self.remembered = load(path) if path else {}
        if any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or type(entry.get("robot")) is not bool
            for entry in self.remembered.values()
        ):
            raise ValueError("Invalid saved surgeon approval")

    def request(self, peer, name, robot=False, credential=None):
        if type(robot) is not bool:
            raise ValueError("Robot access must be true or false")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Enter a name between 1 and 80 characters")
        if peer in self.surgeons:
            raise ValueError("This connection already requested access")
        identity = None
        if credential is not None:
            if not isinstance(credential, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{43}", credential
            ):
                raise ValueError("Invalid surgeon identity")
            identity = hashlib.sha256(credential.encode()).hexdigest()
            if identity in self.identities.values():
                raise ValueError("This surgeon service is already connected")
        self.surgeons[peer] = Surgeon(peer, name.strip(), bool(robot))
        if identity:
            self.identities[peer] = identity
            known = self.remembered.get(identity)
            if known and (not robot or known["robot"]):
                self.surgeons[peer].status = "approved"
                self.surgeons[peer].robot = bool(robot and known["robot"])
        return self.status(peer)

    def approve(self, peer, robot=False):
        if type(robot) is not bool:
            raise ValueError("Robot access must be true or false")
        surgeon = self.surgeons[peer]
        if surgeon.status != "pending":
            raise ValueError("Only pending requests can be approved")
        surgeon.robot = bool(robot and surgeon.requested_robot)
        surgeon.status = "approved"
        identity = self.identities.get(peer)
        if identity and self.path:
            self.remembered[identity] = {"name": surgeon.name, "robot": surgeon.robot}
            save(self.path, self.remembered)

    def revoke(self, peer):
        identity = self.identities.get(peer)
        if peer.startswith("remembered:"):
            identity = peer.removeprefix("remembered:")
        if identity in self.remembered:
            self.remembered.pop(identity)
            save(self.path, self.remembered)
        affected = {
            key
            for key, value in self.identities.items()
            if identity is not None and value == identity
        }
        if peer in self.surgeons:
            affected.add(peer)
        for key in affected:
            self.surgeons[key].status, self.surgeons[key].robot = "revoked", False
        return sorted(affected)

    def disconnect(self, peer):
        self.surgeons.pop(peer, None)
        self.identities.pop(peer, None)

    def require(self, peer, *, robot=False):
        surgeon = self.surgeons.get(peer)
        if surgeon is None or surgeon.status != "approved":
            raise PermissionError("Patient approval is required")
        if robot and not surgeon.robot:
            raise PermissionError("Robot access was not granted")
        return surgeon

    def status(self, peer):
        surgeon = self.surgeons.get(peer)
        return asdict(surgeon) if surgeon else {"status": "disconnected"}

    def list(self):
        return [asdict(surgeon) for surgeon in self.surgeons.values()] + [
            {
                "id": "remembered:" + identity,
                "name": saved["name"],
                "status": "offline",
                "robot": saved["robot"],
                "requested_robot": saved["robot"],
            }
            for identity, saved in self.remembered.items()
            if identity not in self.identities.values()
        ]


class Ownership:
    """Called only on the patient endpoint's serialized control path."""

    def __init__(self, clock=time.monotonic, lease=300.0):
        self.clock, self.lease = clock, lease
        self.owner = self.token = None
        self.identity = self.name = None
        self.expires = 0
        self.sequence = -1
        self.ready = True

    def acquire(self, peer):
        if not self.ready:
            raise RuntimeError("Robot is not ready for control")
        if self.owner is not None and self.owner != peer:
            raise PermissionError("Robot is controlled by another surgeon")
        if self.owner is None:
            self.owner, self.token = peer, secrets.token_urlsafe(32)
            self.sequence = -1
        self.activity()
        return self.token

    def activity(self):
        """Only acquisition and accepted input extend the inactivity deadline."""
        self.expires = self.clock() + self.lease

    def validate(self, peer, token, sequence=None):
        if (
            self.owner != peer
            or not isinstance(token, str)
            or not self.token
            or not secrets.compare_digest(self.token, token)
            or self.clock() >= self.expires
        ):
            raise PermissionError("Robot control has expired or belongs to another surgeon")
        if sequence is not None:
            if type(sequence) is not int or sequence <= self.sequence:
                raise ValueError("Stale robot command")
            self.sequence = sequence

    def expired(self):
        return self.owner is not None and self.clock() >= self.expires

    def release(self):
        self.owner = self.token = None
        self.identity = self.name = None
        self.expires = 0
        self.sequence = -1
