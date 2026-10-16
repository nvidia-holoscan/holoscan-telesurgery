# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Named simulation rooms. Each owns its asset, camera layout, and controller."""

from telesurgery_robots.franka.poses import FRANKA_HOME

ASSETS = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac"
HEALTHCARE = ASSETS + "/Healthcare/0.5.0/132c82d"
# Shared work-area center (cm, Y up, Z = 0), matched to MIRA_SIM_HOME's tool tips.
MIRA_WORK_X, MIRA_WORK_Y = 53.0, 100.0
PRESETS = {
    "versius": {
        "resolution": (1280, 720),
        "cameras": [
            ("procedure", "Versius endoscope camera"),
            ("room", "Versius room camera"),
            ("left", "Versius left arm view"),
            ("right", "Versius right arm view"),
        ],
        # Eye, target (metres, Z up), and focal length (mm). Arm views frame
        # the jaws and shared work area from beside each instrument shaft.
        # The mounted procedure camera derives its eye from the endoscope TCP.
        "camera_views": {
            "procedure": (None, (0, 0, 0.505), 19),
            # Demonstration overview: keep all four bedside units in frame.
            "room": ((2.25, -2.65, 2.3), (0, 0, 0.28), 31),
            "left": ((-0.48, -0.30, 0.88), (0, -0.025, 0.525), 38),
            "right": ((0.48, 0.30, 0.88), (0, -0.025, 0.525), 38),
        },
        "robot": "CMR Versius",
    },
    "mira": {
        # Robot and built-in endoscope from i4h-workflows v0.7.0 telesurgery.
        "asset": HEALTHCARE + "/Robots/MIRA/mira-bipo-size-experiment-smoothing.usd",
        "cameras": [("procedure", "MIRA procedure camera"), ("room", "MIRA room camera")],
        "robot": "MIRA",
        "root": "/World/A5_GUI_MODEL",
        "mounted_camera": "/World/A5_GUI_MODEL/A5_GUI_MODEL_001/C_ASM_6543210"
        "/C_ASM_654321/C_ASM_65432/C_ASM_6543/C_ASM_654/C_ASM_65/C_ASM_6/Camera_Tip/Camera",
        "focal_length": 4.0,
        "camera_target": (MIRA_WORK_X, MIRA_WORK_Y + 4.0, 0.0),
        # Put the optical center beyond the housing lip when looking down at the pad.
        "camera_offset": (2.0, 0.0, 0.0),
        # Oblique front view of the hands and pad after physics settles (cm, Y up).
        "room_view": (
            (MIRA_WORK_X + 132.0, MIRA_WORK_Y + 90.0, -95.0),
            (MIRA_WORK_X - 8.0, MIRA_WORK_Y + 25.0, 0.0),
        ),
        # MIRA is authored in centimetres with Y up; these props use metres and Z up.
        "props": [
            (
                "SuturePad",
                HEALTHCARE + "/Props/SuturePad/suture_pad.usd",
                (MIRA_WORK_X, MIRA_WORK_Y - 3.35, 0.0),
                (-90.0, 0.0, 0.0),
                # 20.32 cm square footprint; preserve the asset's thickness.
                (20.32 / 0.1626, 20.32 / 0.1242, 100.0),
            ),
            (
                "SutureNeedle",
                HEALTHCARE + "/Props/SutureNeedle/needle_sdf.usd",
                (MIRA_WORK_X - 2.78, MIRA_WORK_Y + 2.35, 0.0),
                (-90.0, 0.0, 0.0),
                100.0,
            ),
        ],
        "dynamic_props": ["SutureNeedle"],
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
