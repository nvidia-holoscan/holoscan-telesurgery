# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""JSON boundaries reject non-finite numbers, including overflowing exponents."""

import json
import math


def _constant(value):
    raise ValueError("JSON numbers must be finite")


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numbers must be finite")
    return number


def loads(value):
    return json.loads(value, parse_constant=_constant, parse_float=_float)
