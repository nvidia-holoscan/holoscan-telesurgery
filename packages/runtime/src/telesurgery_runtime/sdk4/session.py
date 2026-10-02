# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ownership of an asynchronous SDK 4 application."""

import threading
from concurrent.futures import TimeoutError


class ApplicationSession:
    """Always stop and join the SDK before releasing devices or UI resources."""

    def __init__(self, application):
        self.application = application

    def __enter__(self):
        from holoscan.conditions import CountCondition
        from holoscan.core import Operator

        ready = threading.Event()

        class ReadyOp(Operator):
            def compute(self, op_input, op_output, context):
                ready.set()

        # A scheduled callback proves GXF has initialized every source condition.
        # Stopping before then could be undone by the condition's initial arguments.
        self.application.add_operator(
            ReadyOp(self.application, CountCondition(self.application, 1), name="runtime_ready")
        )
        self.application.compose_graph()
        self.future = self.application.run_async()
        while not ready.wait(0.01):
            if self.future.done():
                self.application.shutdown_async_executor()
                self.future.result()
                break
        return self

    def is_running(self):
        if self.future.done():
            # SDK 4 also handles SIGINT/SIGTERM itself and can finish normally.
            self.future.result()
            return False
        return True

    def __exit__(self, exc_type, exc, traceback):
        try:
            if not self.future.done():
                for condition in self.application.stop_conditions:
                    condition.disable_tick()
            self.future.result(timeout=5)
        except TimeoutError as error:
            raise RuntimeError("Holoscan application did not stop within five seconds") from error
        finally:
            self.application.shutdown_async_executor(wait=self.future.done())
