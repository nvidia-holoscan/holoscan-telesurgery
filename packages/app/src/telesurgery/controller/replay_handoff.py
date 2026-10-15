# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A completed CMR pickup permits one replay-only, measured gripper release."""

import math
import time

import numpy as np
from telesurgery.controller.haply import CartesianHaply


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
    # A fully closed, empty jaw is a shadow pickup, not a reason to release
    # the donor. These bounds describe the calibrated simulation needle.
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
            and owner.owner == offer["peer"]
            and owner.token == offer["token"]
            and not owner.expired()
        )

    async def prepare(self, context):
        if not context or context["role"] != "right":
            return
        donor = context["key"].rsplit(":", 1)[0] + ":left"
        offer = self.offers.get(donor)
        ready = False
        if offer and offer["group"] == context["group"] and self.owned(offer):
            state = await self.call(donor, "robot.renew", {"token": offer["token"]})
            ready = grasped(state) and at_pose(state, offer["pose"])
        context["shadow"] = not ready
        if ready:
            context["donor_run"] = offer["run"]

    async def clear(self, key):
        for donor, offer in list(self.offers.items()):
            if key not in {donor, offer.get("receiver")}:
                continue
            del self.offers[donor]
            if offer.get("receiver_context"):
                offer["receiver_context"]["interrupted"] = True
            if offer.get("receiver") and self.owned(offer):
                await self.call(donor, "robot.hold", {"token": offer["token"]})

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
                context["offered"] = True
                if grasped(state) and at_pose(state, context["pose"]):
                    self.offers[key] = dict(context)
            return False
        if context["role"] != "right":
            if take:
                raise ValueError("Only the right replay can take the needle")
            return False
        if context.get("shadow"):
            return take
        donor = key.rsplit(":", 1)[0] + ":left"
        offer = self.offers.get(donor)
        if (
            context.get("donor_run")
            and not context.get("transferred")
            and (not offer or offer["run"] != context["donor_run"] or not self.owned(offer))
        ):
            raise RuntimeError("Replay stopped: presented needle is no longer available")
        if not take:
            return False
        if not offer or offer["group"] != context["group"]:
            return True  # Independent right action: complete the empty pickup.
        if not self.owned(offer):
            self.offers.pop(donor, None)
            return True
        if not grasped(state) or not at_pose(state, context["pose"]):
            if offer.get("receiver"):
                await self.clear(key)
                raise RuntimeError("Replay stopped: right grasp changed during release")
            return True
        actual = await self.call(donor, "robot.renew", {"token": offer["token"]})
        if not at_pose(actual, offer["pose"]):
            await self.clear(donor)
            raise RuntimeError("Replay stopped: left handoff position changed")
        if not offer.get("receiver"):
            if not grasped(actual):
                self.offers.pop(donor, None)
                return True
            offer.update(
                receiver=key,
                receiving_run=context["run"],
                receiver_context=context,
                started=self.clock(),
            )
        if offer["receiving_run"] != context["run"]:
            raise RuntimeError("A different replay is releasing this needle")
        if self.clock() - offer["started"] > 10:
            await self.clear(key)
            raise TimeoutError("Replay stopped: left gripper did not open")
        result = await self.call(
            donor, "robot.replay_release", {"token": offer["token"], "sent_at": time.time()}
        )
        if result["done"]:
            self.offers.pop(donor, None)
            context["transferred"] = True
        return result["done"]
