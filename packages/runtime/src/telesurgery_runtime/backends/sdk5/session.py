# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SDK 5 validation and deterministic ownership of a compiled graph session."""


def require_sdk():
    try:
        import holoscan as hs
    except ImportError as exc:
        raise RuntimeError("Holoscan SDK 5 is unavailable; see README.md.") from exc
    version = str(getattr(hs, "__version__", "unknown"))
    if not version.startswith("5.") or not hasattr(hs, "pyobject"):
        raise RuntimeError(
            f"This application requires SDK 5 with native Python operators; found {version}."
        )
    return hs


class ApplicationSession:
    """Compile once, propagate runtime failures, and join before releasing devices."""

    def __init__(self, graph, options=None):
        self.graph = graph
        self.options = options

    def __enter__(self):
        self.hs = require_sdk()
        plan = (
            self.hs.compile(self.graph, self.options)
            if self.options
            else self.hs.compile(self.graph)
        )
        if not plan.ok:
            raise RuntimeError(f"SDK 5 graph compilation failed: {plan.errors}")
        self.session = self.hs.run_async(plan)
        return self

    def _check(self):
        if self.session.termination is self.hs.RunTermination.FAILED:
            details = [
                item.detail.error.message if item.detail is not None else item.token
                for item in self.session.diagnostics
            ]
            raise RuntimeError("SDK 5 graph failed: " + "; ".join(details))

    def is_running(self):
        finished = self.session.wait(timeout=0.0)
        if finished:
            self._check()
        return not finished

    def __exit__(self, exc_type, exc, traceback):
        self.session.request_stop()
        if not self.session.wait(timeout=5.0):
            raise RuntimeError("SDK 5 graph did not stop within five seconds")
        self._check()
