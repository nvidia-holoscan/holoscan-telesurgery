# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A completed CMR pickup permits one replay-only, measured gripper release."""

import math
import time

import numpy as np
from telesurgery.controller.haply import CartesianHaply
from telesurgery_core.control.access import Ownership


def at_pose(state, pose):
    try:
        position, rotation = CartesianHaply.pose(state)
        target, desired = CartesianHaply.pose({"tool_pose": pose})
        error = np.clip((np.trace(desired @ rotation.T) - 1) / 2, -1, 1)
        return (
            state["tool_pose"]["frame"] == pose["frame"]
            and state["tool_pose"].get("end_effector") == pose.get("end_effector")
            and np.linalg.norm(position - target) <= 0.001
            and math.acos(float(error)) <= math.radians(1)
        )
    except (KeyError, TypeError, ValueError):
        return False


def grasped(state):
    # Empty jaws cannot authorize a transfer. These bounds describe the
    # calibrated simulation needle, not a physical grasp sensor.
    opening = state.get("grippers", {}).get("hand")
    return (
        type(opening) in (int, float)
        and 0.01 <= opening <= 0.25
        and state.get("control_active") is False
    )


class ReplayHandoff:
    def __init__(self, owners, call, clock=time.monotonic):
        self.owners, self.call, self.clock = owners, call, clock
        self.offers = {}

    def owned(self, offer):
        owner = self.owners.get(offer["key"])
        return bool(
            owner
            and owner.owner == offer.get("release_peer", offer["peer"])
            and owner.token == offer.get("release_token", offer["token"])
            and owner.token
            and not owner.expired()
        )

    def available(self, offer):
        owner = self.owners.get(offer["key"])
        if offer.get("receiver"):
            return self.owned(offer)
        return bool(
            owner
            and owner.ready
            and (owner.owner is None or owner.owner == offer["peer"] and not owner.expired())
        )

    async def prepare(self, context):
        if not context or context["role"] != "right":
            return
        donor = context["key"].rsplit(":", 1)[0] + ":left"
        offer = self.offers.get(donor)
        owner = self.owners.setdefault(donor, Ownership(clock=self.clock))
        # A browser refresh, released control, or patient restart does not move
        # a held simulation tool. Recover the presentation only for an unowned
        # arm at this recording's measured handoff pose. Never take another
        # surgeon's arm merely because its pose happens to match.
        if offer is None and owner and owner.ready and owner.owner is None:
            offer = {
                "key": donor,
                "peer": None,
                "token": None,
                "group": context["group"],
                "run": context["run"] + ":presentation",
                "pose": context.get("donor_pose"),
            }
        ready = False
        if offer and offer["group"] == context["group"] and self.available(offer):
            state = await self.call(donor, "robot.state", {})
            ready = grasped(state) and at_pose(state, offer["pose"])
        if not ready:
            raise RuntimeError(
                "Left arm must hold the needle at the pickup replay's final position "
                "before starting the right transfer"
            )
        self.offers[donor] = offer
        context["donor_run"] = offer["run"]

    async def released(self, key):
        # A completed, stationary presentation belongs to the scene, not the
        # browser lease. Releasing during an opening still cancels that action.
        offer = self.offers.get(key)
        if offer and not offer.get("receiver"):
            return
        await self.clear(key)

    async def clear_scene(self, key):
        prefix = key.rsplit(":", 1)[0] + ":"
        for donor in list(self.offers):
            if donor.startswith(prefix):
                await self.clear(donor)

    async def clear(self, key):
        for donor, offer in list(self.offers.items()):
            if key not in {donor, offer.get("receiver")}:
                continue
            del self.offers[donor]
            if offer.get("receiver_context"):
                offer["receiver_context"]["interrupted"] = True
            if offer.get("receiver") and self.owned(offer):
                if offer.get("temporary"):
                    await self.call(
                        donor,
                        "handoff.release",
                        {"peer": offer["release_peer"], "token": offer["release_token"]},
                    )
                else:
                    await self.call(donor, "robot.hold", {"token": offer["release_token"]})

    async def update(self, context, state, *, finished=False, take=False):
        if not context:
            if take:
                raise ValueError("This replay does not support independent handoff")
            return False
        if context.get("interrupted"):
            raise RuntimeError("Replay stopped: automatic release was interrupted")
        key = context["key"]
        if context["role"] == "left":
            if take:
                raise ValueError("Only the right replay can take the needle")
            if finished and not context.get("offered"):
                if not grasped(state) or not at_pose(state, context["pose"]):
                    raise RuntimeError("Left pickup did not retain the needle at its handoff pose")
                context["offered"] = True
                self.offers[key] = dict(context)
            return False
        if context["role"] != "right":
            if take:
                raise ValueError("Only the right replay can take the needle")
            return False
        if context.get("transferred"):
            return take
        donor = key.rsplit(":", 1)[0] + ":left"
        offer = self.offers.get(donor)
        if (
            not context.get("donor_run")
            or not offer
            or offer["run"] != context["donor_run"]
            or offer["group"] != context["group"]
            or not self.available(offer)
        ):
            raise RuntimeError("Replay stopped: presented needle is no longer available")
        if not take:
            return False
        actual = await self.call(donor, "robot.state", {})
        if any(s.get("cartesian_feedback", {}).get("ready") is False for s in (state, actual)):
            started = context.setdefault("feedback_wait_started", self.clock())
            if offer.get("receiver") and self.owned(offer):
                await self.call(donor, "robot.hold", {"token": offer["release_token"]})
            if self.clock() - started >= 1:
                await self.clear(key)
                raise TimeoutError("Simulator feedback did not recover for needle transfer")
            return False
        context.pop("feedback_wait_started", None)
        if not grasped(state) or not at_pose(state, context["pose"]):
            if offer.get("receiver"):
                await self.clear(key)
                raise RuntimeError("Replay stopped: right grasp changed during release")
            raise RuntimeError(
                "Right arm did not grasp the presented needle; left grip kept closed"
            )
        if not at_pose(actual, offer["pose"]):
            await self.clear(donor)
            raise RuntimeError("Replay stopped: left handoff position changed")
        if not offer.get("receiver"):
            if not grasped(actual):
                self.offers.pop(donor, None)
                raise RuntimeError("Left arm no longer holds the presented needle")
            owner = self.owners[donor]
            if owner.owner is None:
                acquired = await self.call(donor, "handoff.acquire", {"peer": context["peer"]})
                offer["temporary"] = True
                token = acquired["token"]
            else:
                token = owner.token
            offer.update(
                release_peer=owner.owner,
                release_token=token,
                receiver=key,
                receiving_run=context["run"],
                receiver_context=context,
                started=self.clock(),
            )
            if offer.get("temporary") and (
                not grasped(acquired["state"]) or not at_pose(acquired["state"], offer["pose"])
            ):
                await self.clear(key)
                raise RuntimeError("Left handoff position or grasp changed before release")
        if offer["receiving_run"] != context["run"]:
            raise RuntimeError("A different replay is releasing this needle")
        if self.clock() - offer["started"] > 10:
            await self.clear(key)
            raise TimeoutError("Replay stopped: left gripper did not open")
        # The right replay's validated polling renews only this short opening
        # lease. Its cancellation and the usual node watchdog both stop it.
        self.owners[donor].validate(offer["release_peer"], offer["release_token"])
        result = await self.call(
            donor, "robot.replay_release", {"token": offer["release_token"], "sent_at": time.time()}
        )
        if result["done"]:
            self.offers.pop(donor, None)
            if offer.get("temporary"):
                await self.call(
                    donor,
                    "handoff.release",
                    {"peer": offer["release_peer"], "token": offer["release_token"]},
                )
            context["transferred"] = True
        return result["done"]
