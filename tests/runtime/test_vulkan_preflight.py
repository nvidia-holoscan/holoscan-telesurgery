# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Separate missing driver injection from an unsupported display driver."""

import pytest
from telesurgery_runtime.application import vulkan


@pytest.mark.parametrize(
    "extension", ["VK_EXT_surface_maintenance1", "VK_KHR_surface_maintenance1"]
)
def test_supported_driver(extension, monkeypatch):
    monkeypatch.setattr(vulkan, "extensions", lambda: {"VK_KHR_surface", extension})
    vulkan.check()


def test_missing_icd_explains_both_required_manifests(monkeypatch):
    monkeypatch.setattr(vulkan, "extensions", lambda: {"VK_KHR_portability_enumeration"})
    with pytest.raises(RuntimeError, match="Vulkan ICD and GLVND EGL"):
        vulkan.check()


def test_old_driver_has_distinct_error(monkeypatch):
    monkeypatch.setattr(vulkan, "extensions", lambda: {"VK_KHR_surface"})
    with pytest.raises(RuntimeError, match="lacks surface maintenance"):
        vulkan.check()
