# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Select one installed Holoscan backend per process."""

import importlib
import os


def require_sdk():
    try:
        import holoscan as hs
    except ImportError as exc:
        command = "./setup.sh --sdk 4" if os.environ.get("TELESURGERY_SDK") == "4" else "./setup.sh"
        raise RuntimeError(f"Holoscan is unavailable; run {command}") from exc
    major = str(hs.__version__).split(".")[0]
    expected = os.environ.get("TELESURGERY_SDK", major)
    if major not in {"4", "5"} or major != expected:
        raise RuntimeError(
            f"Requested SDK {expected}, but this Python has Holoscan {hs.__version__}"
        )
    return hs


def backend(module):
    major = require_sdk().__version__.split(".")[0]
    if module == "camera" and major != "4":
        raise RuntimeError(
            "HSB capture needs the camera runtime. Run ./setup.sh with the board connected, "
            "then restart the node through ./run.sh so it can select camera support."
        )
    return importlib.import_module(f"telesurgery_runtime.backends.sdk{major}.{module}")


def ApplicationSession(graph):
    return backend("session").ApplicationSession(graph)
