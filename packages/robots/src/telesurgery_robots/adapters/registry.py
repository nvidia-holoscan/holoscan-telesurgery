# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Robot adapters loaded from installed workspace or vendor packages."""

from functools import cache
from importlib.metadata import entry_points


@cache
def adapter_type(kind):
    matches = list(entry_points(group="telesurgery.robots", name=kind))
    if not matches:
        raise ValueError(f"No controller adapter installed for {kind}")
    if len(matches) != 1:
        raise ValueError(f"Multiple controller adapters registered for {kind}")
    return matches[0].load()
