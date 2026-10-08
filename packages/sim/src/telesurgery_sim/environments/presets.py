# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Named simulation rooms. Each owns its asset, camera layout, and controller."""

from telesurgery_robots.franka.poses import FRANKA_HOME

ASSETS = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac"
HEALTHCARE = ASSETS + "/Healthcare/0.5.0/132c82d"
PRESETS = {
    "mira": {
        # Robot and built-in endoscope from i4h-workflows v0.7.0 telesurgery.
        "asset": HEALTHCARE + "/Robots/MIRA/mira-bipo-size-experiment-smoothing.usd",
        "cameras": [("procedure", "MIRA procedure camera"), ("room", "MIRA room camera")],
        "robot": "MIRA",
        "root": "/World/A5_GUI_MODEL",
        "mounted_camera": "/World/A5_GUI_MODEL/A5_GUI_MODEL_001/C_ASM_6543210"
        "/C_ASM_654321/C_ASM_65432/C_ASM_6543/C_ASM_654/C_ASM_65/C_ASM_6/Camera_Tip/Camera",
        "focal_length": 5.0,
        # MIRA is authored in centimetres with Y up; these props use metres and Z up.
        "props": [
            (
                "SuturePad",
                HEALTHCARE + "/Props/SuturePad/suture_pad.usd",
                (13.4, 20.0, 0.0),
                (-90.0, 0.0, 0.0),
                # 20.32 cm square footprint; preserve the asset's thickness.
                (20.32 / 0.1626, 20.32 / 0.1242, 100.0),
            ),
            (
                "SutureNeedle",
                HEALTHCARE + "/Props/SutureNeedle/needle_sdf.usd",
                (6.0, 23.6, 0.0),
                (-90.0, 0.0, 0.0),
                100.0,
            ),
        ],
    },
    "franka": {
        "asset": HEALTHCARE + "/Robots/Franka/Collected_panda_assembly/panda_assembly.usda",
        "cameras": [("wrist", "Franka wrist camera"), ("room", "Franka room camera")],
        "robot": "Franka Panda",
        "root": "/World/Robot",
        "fixed_base": "/World/Robot/panda_link0",
        "joints": list(FRANKA_HOME),
        "mounted_camera": "/World/Robot/D405_rigid/D405/Camera_OmniVision_OV9782_Color",
        "room_view": ((1.65, -1.75, 1.3), (0.3, 0.0, 0.2)),
        "floor": -0.86,
        "props": [
            (
                "PatientTable",
                HEALTHCARE + "/Props/VentionTable/BlackCover/table_with_cover.usd",
                (0.4804, 0.02017, -0.84415),
                (0.0, 0.0, -90.0),
                1.0,
            ),
            (
                "AbdominalPhantom",
                HEALTHCARE + "/Props/ABDPhantom/phantom.usda",
                (0.6, 0.0, 0.09),
                (0.0, 0.0, 180.0),
                1.0,
            ),
        ],
    },
}


RESOLUTIONS = ((640, 480), (1280, 720), (1920, 1080), (2560, 1440), (3840, 2160))
