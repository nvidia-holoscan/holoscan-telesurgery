# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native GPU display graph for SDK 4."""

from holoscan.core import Application, Operator
from holoscan.operators import HolovizOp
from telesurgery_runtime.backends.sdk4.operators import (
    configure_scheduler,
    latest_output,
    source_conditions,
)
from telesurgery_runtime.backends.sdk4.session import ApplicationSession


def build(source, width, height, title):
    class ReceiveDecode(Operator):
        def setup(self, spec):
            latest_output(spec)

        def start(self):
            source.start()

        def compute(self, op_input, op_output, context):
            image = source.compute()
            if image is not None:
                op_output.emit({"image": image}, "out")
                source.submitted()

        def stop(self):
            source.stop()

    class Viewer(Application):
        def compose(self):
            conditions = source_conditions(self, 1000)
            receive = ReceiveDecode(self, *conditions, name="receive_decode")
            display = HolovizOp(
                self,
                name="display",
                window_title=title,
                width=min(width, 1280),
                height=min(height, 720),
                tensors=[{"name": "image", "type": "color"}],
                window_close_condition=conditions[0],
                vsync=False,
            )
            self.add_flow(receive, display, {("out", "receivers")})

    app = Viewer(argv=["telesurgery-holoviz"])
    configure_scheduler(app)
    return ApplicationSession(app)
