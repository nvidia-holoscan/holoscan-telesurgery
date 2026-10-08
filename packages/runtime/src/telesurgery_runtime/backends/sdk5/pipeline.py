# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile shared stages into SDK 5 operators."""

import holoscan as hs
from telesurgery_runtime.backends.sdk5.operators import PeriodicOp, connect


def build(name, stages, hz=30):
    graph = hs.Graph(name, default_clock=hs.RealtimeClock)
    previous = None
    for index, stage in enumerate(stages):

        def operator(stage, source, sink):
            class Step(PeriodicOp if source else hs.Operator):
                inp = hs.Input("in", hs.pyobject)
                out = hs.Output("out", hs.pyobject)

                def setup(self, spec):
                    if not source:
                        spec.input(self.inp, queue_depth=1)
                    if not sink:
                        spec.output(self.out)

                def start(self):
                    if method := getattr(stage, "start", None):
                        method()

                def compute(self, context):
                    result = stage.compute() if source else stage.compute(self.inp.receive_data())
                    if not sink and result is not None:
                        self.out.emit(result)

                def stop(self):
                    if method := getattr(stage, "stop", None):
                        method()

            return Step

        step = graph.op(
            operator(stage, index == 0, index == len(stages) - 1),
            f"stage_{index}",
            **({"hz": hz} if index == 0 else {}),
        )
        if previous is not None:
            connect(graph, previous.out, step["in"])
        graph.partition(f"lane_{index}").add(step)
        previous = step
    return graph
