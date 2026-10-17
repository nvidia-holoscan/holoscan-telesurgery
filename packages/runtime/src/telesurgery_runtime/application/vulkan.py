# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Diagnose graphics-driver discovery before starting a native viewer graph."""

import ctypes


class Extension(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 256), ("version", ctypes.c_uint32)]


def extensions():
    library = ctypes.CDLL("libvulkan.so.1")
    enumerate_extensions = library.vkEnumerateInstanceExtensionProperties
    enumerate_extensions.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    enumerate_extensions.restype = ctypes.c_int32
    count = ctypes.c_uint32()
    if enumerate_extensions(None, ctypes.byref(count), None) != 0 or not 0 < count.value < 4096:
        raise RuntimeError("Vulkan driver enumeration failed")
    values = (Extension * count.value)()
    if enumerate_extensions(None, ctypes.byref(count), values) != 0:
        raise RuntimeError("Vulkan driver enumeration failed")
    return {value.name.decode() for value in values}


def check(*, maintenance=True):
    try:
        available = extensions()
    except (OSError, AttributeError, RuntimeError) as exc:
        raise RuntimeError(
            "Holoviz unavailable: Vulkan loader or driver could not load. "
            "Check the host NVIDIA driver and container graphics support."
        ) from exc
    if "VK_KHR_surface" not in available:
        raise RuntimeError(
            "Holoviz unavailable: no usable Vulkan display driver. Check both the NVIDIA "
            "Vulkan ICD and GLVND EGL vendor manifests and matching driver libraries; "
            "restart through ./run.sh --docker."
        )
    if maintenance and not available & {
        "VK_EXT_surface_maintenance1",
        "VK_KHR_surface_maintenance1",
    }:
        raise RuntimeError(
            "Holoviz unavailable: the Vulkan driver lacks surface maintenance support. "
            "Check the host NVIDIA driver version and container graphics injection."
        )
