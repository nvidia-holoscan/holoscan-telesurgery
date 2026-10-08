# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared simulation and physical robot reference poses, in joint degrees."""

# Operator-selected physical reset pose, ordered J1–J7; the gripper is independent.
FRANKA_HOME = (-24.475, -18.378, 13.651, -106.151, 9.422, 90.758, -21.335)
FRANKA_SPEED = {"min": 0.2, "max": 20.0, "default": 10.0}
