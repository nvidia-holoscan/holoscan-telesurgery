# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile shared stages into SDK 4 operators."""

from holoscan.core import Application, Operator
from telesurgery_runtime.sdk4.channel import LatestChannel
from telesurgery_runtime.sdk4.operators import (
    configure_scheduler,
    latest_input,
    latest_output,
    source_conditions,
)


def build(name, stages, hz=30):
    class Pipeline(Application):
        def compose(self):
            previous = incoming = None
            for index, stage in enumerate(stages):
                outgoing = LatestChannel() if index < len(stages) - 1 else None

                def operator(stage, incoming, outgoing):
                    class Step(Operator):
                        def setup(self, spec):
                            if incoming is not None:
                                latest_input(spec)
                            if outgoing is not None:
                                latest_output(spec)

                        def start(self):
                            if method := getattr(stage, "start", None):
                                method()

                        def compute(self, op_input, op_output, context):
                            if incoming is None:
                                result = stage.compute()
                            else:
                                value = incoming.receive(op_input)
                                if value is None:
                                    return
                                result = stage.compute(value)
                            if outgoing is not None and result is not None:
                                outgoing.send(op_output, result)

                        def stop(self):
                            if method := getattr(stage, "stop", None):
                                method()

                    return Step

                step = operator(stage, incoming, outgoing)(
                    self,
                    *(source_conditions(self, hz) if index == 0 else []),
                    name=f"stage_{index}",
                )
                if previous is not None:
                    self.add_flow(previous, step, {("out", "in")})
                else:
                    self.add_operator(step)
                previous, incoming = step, outgoing

    app = Pipeline(argv=[name])
    configure_scheduler(app)
    return app
