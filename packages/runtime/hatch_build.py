# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Mark wheels containing the native SDK 5 camera extension as platform-specific."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if list(Path(self.root, "src/telesurgery_runtime/backends/sdk5").glob("*.so")):
            build_data["pure_python"] = False
            build_data["infer_tag"] = True
