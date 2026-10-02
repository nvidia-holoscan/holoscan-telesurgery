# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared SDK 4 scheduling conditions and bounded operator ports."""

from holoscan.conditions import BooleanCondition, PeriodicCondition
from holoscan.core import ConditionType, IOSpec
from holoscan.schedulers import EventBasedScheduler


def latest_input(spec, name="in"):
    return spec.input(name, policy=IOSpec.QueuePolicy.POP)


def latest_output(spec, name="out"):
    # Capture must keep draining the device even when downstream processing is busy.
    return (
        spec.output(name)
        .condition(ConditionType.NONE)
        .connector(IOSpec.ConnectorType.DOUBLE_BUFFER, capacity=1, policy=0)
    )


def source_conditions(app, hz=None):
    gate = BooleanCondition(app, enable_tick=True)
    app.stop_conditions.append(gate)
    conditions = [gate]
    if hz is not None:
        conditions.append(PeriodicCondition(app, recess_period=1_000_000_000 // hz))
    return conditions


def configure_scheduler(app):
    app.stop_conditions = []
    app.scheduler(
        EventBasedScheduler(
            app,
            worker_thread_number=4,
            stop_on_deadlock=True,
            stop_on_deadlock_timeout=100,
            name="scheduler",
        )
    )
