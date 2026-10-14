# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared Versius room with independent arms and selectable operator views."""

import gc
import json
import queue
import threading
import time
from concurrent.futures import Future


def run(app, args):
    import cv2
    import numpy as np
    import omni.timeline
    import omni.usd
    import zmq
    from isaacsim.core.experimental.prims import RigidPrim
    from isaacsim.sensors.experimental.rtx import CameraSensor, RtxCamera
    from pxr import Gf, PhysxSchema, UsdGeom, UsdLux, UsdPhysics
    from telesurgery_core.transport.protocol import MAX_FRAME, VideoHeader
    from telesurgery_core.transport.zmq import open_socket
    from telesurgery_core.video.depth import attach
    from telesurgery_core.video.formats import encode_raw
    from telesurgery_core.video.model import Frame
    from telesurgery_robots.simulation.state import SimRobot
    from telesurgery_robots.versius import ARMS
    from telesurgery_sim.environments.assets import fetch, place_static
    from telesurgery_sim.environments.needle import configure_needle_contacts
    from telesurgery_sim.environments.presets import HEALTHCARE, PRESETS, RESOLUTIONS
    from telesurgery_sim.environments.versius import build
    from telesurgery_sim.runtime.feedback import JointFeedback
    from telesurgery_sim.runtime.franka import FrankaFeedback
    from websockets.sync.server import serve

    context = omni.usd.get_context()
    context.new_stage()
    stage = context.get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, "Z")
    UsdGeom.Xform.Define(stage, "/World")
    scene = UsdPhysics.Scene.Define(stage, "/World/Physics")
    physics = PhysxSchema.PhysxSceneAPI.Apply(scene.GetPrim())
    physics.CreateTimeStepsPerSecondAttr(120)
    # Four small articulations run faster on CPU than GPU dynamics. Avoid
    # GPU solver overhead making wall-clock input outrun simulated motion.
    physics.CreateEnableGPUDynamicsAttr(False)
    physics.CreateBroadphaseTypeAttr("MBP")
    physics.CreateEnableCCDAttr(True)
    (args.directory / "progress").write_text("Building Versius arms from supplied URDFs")
    rigs = build(stage, args.versius_assets)
    robots = {arm: SimRobot("versius") for arm in rigs}
    robots["endoscope"].gripper_ranges = {}
    feedback, tools = {}, {}
    for arm, rig in rigs.items():
        feedback[arm] = JointFeedback(stage, rig["root"], rig["drives"], 8)
        tools[arm] = FrankaFeedback(feedback[arm], {})

    def box(name, position, size, color):
        cube = UsdGeom.Cube.Define(stage, "/World/" + name)
        cube.CreateSizeAttr(1)
        cube.AddTranslateOp().Set(Gf.Vec3d(*position))
        cube.AddScaleOp().Set(Gf.Vec3f(*size))
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        contact = PhysxSchema.PhysxCollisionAPI.Apply(cube.GetPrim())
        contact.CreateContactOffsetAttr(0.0002)
        contact.CreateRestOffsetAttr(0.0)
        return cube

    box("Floor", (0, 0, -0.05), (12, 12, 0.1), (0.12, 0.18, 0.24))
    box("ProcedureTable", (0, 0, 0.445), (0.55, 0.65, 0.06), (0.18, 0.23, 0.28))
    box("TableSupport", (0, 0, 0.2075), (0.22, 0.35, 0.415), (0.18, 0.23, 0.28))
    pad = fetch(HEALTHCARE + "/Props/SuturePad/suture_pad.usd", args.directory / "assets")
    place_static(stage, "/World/SuturePad", pad, (0, 0, 0.477), (0, 0, 0), (1.35, 1.45, 1))
    # A solid contact surface beneath the pad's detailed visual mesh keeps
    # the small needle on the work area after release.
    surface = box("PadContact", (0, 0, 0.489), (0.19, 0.15, 0.02), (0.5, 0.2, 0.2))
    surface.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
    # A shallow groove beneath the free needle provides lower-jaw clearance
    # for first pickup. Both sides of the groove physically support the curve.
    for index, (y, length) in enumerate(((-0.0345, 0.017), (-0.051, 0.004))):
        box(f"NeedleRest{index}", (0, y, 0.5015), (0.024, length, 0.005), (0.28, 0.08, 0.06))
    asset = fetch(HEALTHCARE + "/Props/SutureNeedle/needle_sdf.usd", args.directory / "assets")
    while context.get_stage_loading_status()[2] > 0:
        app.update()
    # Scale the supplied curved needle to a 25 mm training object. Keep the
    # dynamic body's frame unscaled and centred for measured physics feedback.
    needle = UsdGeom.Xform.Define(stage, "/World/TrainingNeedle")
    needle.AddTranslateOp().Set(Gf.Vec3d(0, -0.04, 0.5047))
    visual = UsdGeom.Xform.Define(stage, "/World/TrainingNeedle/Asset")
    visual.GetPrim().GetReferences().AddReference(asset)
    visual.GetPrim().RemoveAPI(UsdPhysics.RigidBodyAPI)
    visual.ClearXformOpOrder()
    visual.AddTranslateOp().Set(Gf.Vec3d(-0.022784 * 0.25, 0.000283 * 0.25, -0.000957 * 0.25))
    visual.AddScaleOp().Set(Gf.Vec3f(0.25))
    UsdPhysics.RigidBodyAPI.Apply(needle.GetPrim())
    configure_needle_contacts(stage, "/World/TrainingNeedle", mass=0.0001875, contact_offset=0.0001)
    training_object = RigidPrim("/World/TrainingNeedle")
    # A visible destination makes the cooperative pickup/handoff/place task clear.
    for name, position, size in (
        ("Left", (0.035, 0.04, 0.4995), (0.002, 0.034, 0.001)),
        ("Right", (0.065, 0.04, 0.4995), (0.002, 0.034, 0.001)),
        ("Near", (0.05, 0.024, 0.4995), (0.03, 0.002, 0.001)),
        ("Far", (0.05, 0.056, 0.4995), (0.03, 0.002, 0.001)),
    ):
        box("PlacementTarget" + name, position, size, (0.05, 0.45, 0.8))
    scene_state = {}
    UsdLux.DomeLight.Define(stage, "/World/Light").CreateIntensityAttr(1000)
    cameras, publishers, manifests = [], [], []
    preset = PRESETS["versius"]
    width, height = preset["resolution"]
    depth_enabled = [False] * len(preset["cameras"])
    for key, name in preset["cameras"]:
        eye, target, focal_length = preset["camera_views"][key]
        path = (
            rigs["endoscope"]["root"] + "/TCP/Camera"
            if key == "procedure"
            else f"/World/{key}_camera"
        )
        parent = UsdGeom.XformCache().GetLocalToWorldTransform(
            stage.GetPrimAtPath(path.rsplit("/", 1)[0])
        )
        if eye is None:
            eye = parent.Transform(Gf.Vec3d(0, 0, 0.006))
        camera = UsdGeom.Camera.Define(stage, path)
        camera.CreateClippingRangeAttr((0.001, 20))
        camera.CreateFocalLengthAttr(focal_length)
        camera.CreateFStopAttr(0)
        matrix = (
            Gf.Matrix4d()
            .SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
            .GetInverse()
        ) * parent.GetInverse()
        camera.AddTranslateOp().Set(matrix.ExtractTranslation())
        camera.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(matrix.ExtractRotationQuat())
        camera.GetPrim().ApplyAPI("OmniSensorAPI")
        cameras.append(
            CameraSensor(
                RtxCamera(path, tick_rate=0, reset_xform_op_properties=False),
                resolution=(height, width),
                annotators=["rgb"],
            )
        )
        endpoint = f"ipc://{args.directory}/{key}.sock"
        publishers.append(open_socket(zmq.PUB, endpoint, bind=True, max_size=MAX_FRAME))
        (args.directory / f"{key}.sock").chmod(0o660)
        manifests.append(
            {
                "id": key,
                "name": name,
                "kind": "Isaac Sim",
                "source": f"gateway:{endpoint}",
                "width": width,
                "height": height,
                "fps": 30,
                "depth_supported": True,
                "depth_source": "simulated",
                "prim_path": path,
                "control_uri": f"ws://127.0.0.1:{args.api_port}",
                "modes": [{"width": w, "height": h, "fps": [30]} for w, h in RESOLUTIONS],
            }
        )
    if args.gui:
        from omni.kit.viewport.utility import get_active_viewport

        get_active_viewport().camera_path = manifests[0]["prim_path"]
    (args.directory / "progress").write_text("Warming up Versius camera rendering")
    lock, pending = threading.Lock(), queue.Queue(maxsize=8)
    observed, sequence, commands = time.monotonic(), 0, 0

    def handle(socket):
        nonlocal commands
        arm = socket.request.path.strip("/")
        for raw in socket:
            request = {}
            try:
                request = json.loads(raw)
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValueError("Expected JSON-RPC 2.0")
                if request.get("method") == "get_scene_state":
                    with lock:
                        result = dict(scene_state)
                elif request.get("method") == "camera.configure":
                    future = Future()
                    pending.put_nowait((time.monotonic(), request["params"], future))
                    result = future.result(timeout=10)
                else:
                    if arm not in robots:
                        raise ValueError("Choose a Versius arm endpoint")
                    with lock:
                        if time.monotonic() - observed > 1:
                            robots[arm].apply({"method": "hold"})
                            raise ValueError("Simulator physics feedback is stale")
                        result = robots[arm].apply(request)
                        if request.get("method", "").startswith(("set_", "jog_")):
                            commands += 1
                reply = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
            except (ValueError, TypeError, KeyError, queue.Full, TimeoutError) as exc:
                reply = {
                    "jsonrpc": "2.0",
                    "id": request.get("id") if isinstance(request, dict) else None,
                    "error": {"code": -32602, "message": str(exc)},
                }
            socket.send(json.dumps(reply))

    server = serve(handle, "127.0.0.1", args.api_port, max_size=4096)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    import carb.settings
    from omni.kit.loop import _loop

    _loop.acquire_loop_interface().set_manual_mode(False)
    carb.settings.get_settings().set_bool("/app/player/useFixedTimeStepping", False)
    carb.settings.get_settings().set_int("/persistent/simulation/minFrameRate", 10)
    omni.timeline.get_timeline_interface().play()
    ready = set()
    try:
        while app.is_running() and not (args.directory / "stop").exists():
            started = time.monotonic()
            for _ in range(8):
                try:
                    received, params, future = pending.get_nowait()
                except queue.Empty:
                    break
                try:
                    size = (params["width"], params["height"])
                    if time.monotonic() - received > 5 or size not in RESOLUTIONS:
                        raise ValueError("Expired or unsupported camera configuration")
                    index = next(i for i, m in enumerate(manifests) if m["id"] == params["id"])
                    enabled = bool(params.get("depth", False))
                    if cameras[index].resolution != size[::-1] or depth_enabled[index] != enabled:
                        depth_enabled[index] = enabled
                        cameras[index] = CameraSensor(
                            cameras[index].authoring_object,
                            resolution=size[::-1],
                            annotators=["rgb", "distance_to_image_plane"] if enabled else ["rgb"],
                        )
                        gc.collect()
                    future.set_result(True)
                except (ValueError, KeyError, StopIteration) as exc:
                    future.set_exception(ValueError(str(exc)))
            with lock:
                for arm, robot in robots.items():
                    robot.advance()
                    positions, velocities = {}, {}
                    for index, drive in rigs[arm]["drives"]["joints"].items():
                        path = str(drive.GetPath())
                        positions[path] = np.deg2rad(robot.pose["joints"][index])
                        velocities[path] = np.deg2rad(robot.joint_target_velocity[index])
                    opening = robot.finger_target / 0.04 * 35
                    for name, sign in (("yoke_jaw_left", 1), ("yoke_jaw_right", -1)):
                        if name in rigs[arm]["fingers"]:
                            path = str(rigs[arm]["fingers"][name].GetPath())
                            positions[path], velocities[path] = np.deg2rad(sign * opening), 0.0
                    feedback[arm].apply_targets(positions, velocities)
            app.update()
            for arm in robots:
                measured = feedback[arm].read()
                measured.update(tools[arm].read(measured))
                if measured.get("joints_deg") and rigs[arm]["fingers"]:
                    view = feedback[arm].views[0]
                    paths, positions = view.dof_paths[0], view.get_dof_positions().numpy()[0]
                    jaws = [
                        float(
                            abs(positions[paths.index(str(rigs[arm]["fingers"][name].GetPath()))])
                        )
                        for name in ("yoke_jaw_left", "yoke_jaw_right")
                    ]
                    measured["grippers"] = {
                        "hand": float(np.clip(np.mean(jaws) / np.deg2rad(35), 0, 1))
                    }
                with lock:
                    robots[arm].feedback = measured
                    robots[arm].kinematics = tools[arm].kinematics
            with lock:
                observed = time.monotonic()
                scene_state = {
                    "training_object_position_m": training_object.get_world_poses()[0]
                    .numpy()[0]
                    .tolist()
                }
            for index, camera in enumerate(cameras):
                pixels, _ = camera.get_data("rgb")
                if pixels is None:
                    continue
                rgb = np.asarray(pixels.numpy(), np.uint8)
                if not rgb.size:
                    continue
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                header = VideoHeader(
                    sequence,
                    time.time_ns(),
                    bgr.shape[1],
                    bgr.shape[0],
                    sim_command_sequence=commands,
                )
                header, data = encode_raw(Frame(header, bgr))
                if depth_enabled[index]:
                    distances, _ = camera.get_data("distance_to_image_plane")
                    if distances is not None:
                        header, data = attach(
                            header,
                            data,
                            np.asarray(distances.numpy(), np.float32).reshape(bgr.shape[:2]),
                        )
                try:
                    publishers[index].send_multipart([header.encode(), data], zmq.NOBLOCK)
                except zmq.Again:
                    pass
                ready.add(index)
            sequence += 1
            manifest = args.directory / "devices.json"
            if len(ready) == len(cameras) and not manifest.exists():
                temporary = manifest.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "cameras": manifests,
                            "robots": [
                                {
                                    "id": arm,
                                    "name": f"Versius {ARMS[arm].lower()} arm",
                                    "kind": "versius-sim",
                                    "uri": f"ws://127.0.0.1:{args.api_port}/{arm}",
                                }
                                for arm in rigs
                            ],
                        },
                        indent=2,
                    )
                )
                temporary.replace(manifest)
                print(
                    f"versius ready: {len(cameras)} cameras and four independent arm controllers",
                    flush=True,
                )
            time.sleep(max(0, 1 / 30 - (time.monotonic() - started)))
    finally:
        server.shutdown()
        for publisher in publishers:
            publisher.close()
