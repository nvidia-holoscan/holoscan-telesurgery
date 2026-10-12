# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Sim entry point: one room, several cameras, one loopback controller."""

import argparse
import gc
import json
import queue
import re
import threading
import time
import traceback
from concurrent.futures import Future
from pathlib import Path

from telesurgery_core.video.config import Config
from telesurgery_sim.environments.presets import PRESETS, RESOLUTIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim", choices=PRESETS, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--versius-assets", type=Path)
    args = parser.parse_args()
    width, height = Config.width, Config.height

    def progress(message):
        temporary = args.directory / "progress.tmp"
        temporary.write_text(message)
        temporary.replace(args.directory / "progress")
        print(message, flush=True)

    progress("Starting Isaac Sim")
    from isaacsim import SimulationApp

    app = SimulationApp(
        {
            "headless": not args.gui,
            "width": width,
            "height": height,
            "window_width": 1280,
            "window_height": 900,
            "multi_gpu": False,
        }
    )
    server = None
    publishers = []
    try:
        if args.sim == "versius":
            from telesurgery_sim.runtime.versius import run

            run(app, args)
            return
        import cv2
        import numpy as np
        import omni.timeline
        import omni.usd
        import zmq
        from isaacsim.sensors.experimental.rtx import CameraSensor, RtxCamera
        from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdLux, UsdPhysics
        from telesurgery_core.transport.protocol import MAX_FRAME, VideoHeader
        from telesurgery_core.transport.zmq import open_socket
        from telesurgery_core.video.formats import encode_raw
        from telesurgery_core.video.model import Frame
        from telesurgery_robots.simulation.state import SimRobot
        from telesurgery_sim.runtime.feedback import JointFeedback
        from websockets.sync.server import serve

        progress("Loading environment assets")
        from telesurgery_sim.environments.assets import fetch, place_static

        preset = PRESETS[args.sim]
        asset = fetch(preset["asset"], args.directory / "assets")
        props = [
            (name, fetch(url, args.directory / "assets"), position, rotation, scale)
            for name, url, position, rotation, scale in preset.get("props", [])
        ]
        context = omni.usd.get_context()
        if args.sim == "mira":
            if not context.open_stage(asset):
                raise RuntimeError("Could not load MIRA asset")
        else:
            context.new_stage()
            stage = context.get_stage()
            UsdGeom.SetStageMetersPerUnit(stage, 1.0)
            UsdGeom.SetStageUpAxis(stage, "Z")
            UsdGeom.Xform.Define(stage, "/World")
            robot = UsdGeom.Xform.Define(stage, "/World/Robot")
            robot.GetPrim().GetReferences().AddReference(asset)
            UsdPhysics.Scene.Define(stage, "/World/Physics")
        while context.get_stage_loading_status()[2] > 0:
            app.update()
        progress("Building room and cameras")
        stage = context.get_stage()
        UsdGeom.Xform.Define(stage, "/Telesurgery")
        if "fixed_base" in preset:
            mount = UsdPhysics.FixedJoint.Define(stage, preset["root"] + "/WorldAnchor")
            mount.CreateBody1Rel().SetTargets([preset["fixed_base"]])
            articulation = PhysxSchema.PhysxArticulationAPI.Apply(
                stage.GetPrimAtPath(preset["root"])
            )
            articulation.CreateSolverPositionIterationCountAttr(64)
            articulation.CreateSolverVelocityIterationCountAttr(4)
        for name, path, position, rotation, scale in props:
            place_static(stage, f"/Telesurgery/{name}", path, position, rotation, scale)
        if stage.GetPrimAtPath("/Needle"):
            stage.GetPrimAtPath("/Needle").SetActive(False)
        for prim in stage.Traverse():
            if prim.HasAPI(UsdLux.LightAPI):
                UsdLux.LightAPI(prim).GetIntensityAttr().Set(0.0)
        dome = UsdLux.DomeLight.Define(stage, "/Telesurgery/RoomLight")
        dome.CreateIntensityAttr(900)
        if args.sim == "mira":
            from telesurgery_sim.environments.mira import enable_tool_roll

            enable_tool_roll(stage)
        drives = {"left": {}, "right": {}} if args.sim == "mira" else {"joints": {}}
        fingers = {}
        for prim in stage.Traverse():
            if args.sim == "mira":
                match = re.fullmatch(r"([LR])J([1-6])(?:_1)?_joint", prim.GetName())
                if match and prim.HasAPI(UsdPhysics.DriveAPI, "angular"):
                    drives["left" if match[1] == "L" else "right"][int(match[2]) - 1] = (
                        UsdPhysics.DriveAPI.Get(prim, "angular")
                    )
            else:
                match = re.fullmatch(r"panda_joint([1-7])", prim.GetName())
                if match:
                    index = int(match[1]) - 1
                    drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
                    # Inertia-scaled drives stay well damped as the shoulder
                    # and elbow axes align. Fixed force gains oscillate in
                    # these configurations even at low commanded speeds.
                    drive.CreateTypeAttr(UsdPhysics.Tokens.acceleration)
                    drive.CreateStiffnessAttr(1600)
                    drive.CreateDampingAttr(80)
                    drive.CreateMaxForceAttr(87 if index < 4 else 12)
                    drive.CreateTargetVelocityAttr(0)
                    # Bound the physics response as well as the commanded
                    # trajectory, especially near aligned articulation axes.
                    joint_physics = PhysxSchema.PhysxJointAPI.Apply(prim)
                    joint_physics.CreateMaxJointVelocityAttr(30)
                    # Small reflected motor inertia prevents nearly aligned
                    # shoulder axes from becoming numerically ill-conditioned.
                    joint_physics.CreateArmatureAttr(0.01)
                    drives["joints"][index] = drive
                finger = re.fullmatch(r"panda_finger_joint([12])", prim.GetName())
                if finger:
                    drive = UsdPhysics.DriveAPI.Apply(prim, "linear")
                    drive.CreateStiffnessAttr(10000)
                    drive.CreateDampingAttr(200)
                    drive.CreateMaxForceAttr(40)
                    fingers[int(finger[1])] = drive
        expected = 6 if args.sim == "mira" else 7
        if any(len(group) != expected for group in drives.values()):
            raise RuntimeError(f"Robot asset has unexpected joint drives: {drives}")
        robot = SimRobot(args.sim)
        if "joints" in preset:
            robot.pose["joints"] = list(preset["joints"])
        cache = UsdGeom.BBoxCache(0, ["default", "render"])
        bounds = Gf.Range3d()
        for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
            if prim.IsA(UsdGeom.Mesh) and str(prim.GetPath()).startswith(preset["root"] + "/"):
                bounds.UnionWith(cache.ComputeWorldBound(prim).ComputeAlignedRange())
        if bounds.IsEmpty():
            raise RuntimeError("Robot asset has no visible geometry")
        center = bounds.GetMidpoint()
        radius = max(bounds.GetSize())
        up_axis = 1 if UsdGeom.GetStageUpAxis(stage) == "Y" else 2
        up = Gf.Vec3d(0, 1, 0) if up_axis == 1 else Gf.Vec3d(0, 0, 1)

        def box(name, position, scale, color):
            prim = UsdGeom.Cube.Define(stage, f"/Telesurgery/{name}")
            prim.CreateSizeAttr(1)
            prim.AddTranslateOp().Set(Gf.Vec3d(*position))
            prim.AddScaleOp().Set(Gf.Vec3f(*scale))
            prim.CreateDisplayColorAttr([color])
            UsdPhysics.CollisionAPI.Apply(prim.GetPrim())

        floor_position = list(center)
        floor_position[up_axis] = preset.get("floor", bounds.GetMin()[up_axis] - radius * 0.12)
        scale = [radius * 3] * 3
        scale[up_axis] = radius * 0.02
        box("Floor", floor_position, scale, (0.12, 0.18, 0.24))
        if args.sim == "mira":
            box("ProcedureTable", (13.4, 18.0, 0.0), (32.0, 4.0, 32.0), (0.16, 0.21, 0.25))
        cameras = []
        depth_enabled = []
        manifests = []
        for index, (key, name) in enumerate(preset["cameras"]):
            path = preset.get("mounted_camera") if index == 0 else None
            existing = bool(path)
            path = path or f"/Telesurgery/{key}"
            if existing and not stage.GetPrimAtPath(path).IsA(UsdGeom.Camera):
                raise RuntimeError(f"Missing asset camera: {path}")
            camera = UsdGeom.Camera.Define(stage, path)
            if not existing:
                camera.CreateClippingRangeAttr((max(0.001, radius * 0.001), radius * 20))
                camera.CreateFocalLengthAttr(22)
            elif "focal_length" in preset:
                camera.CreateFocalLengthAttr(preset["focal_length"])
            camera.CreateFStopAttr(0.0)
            offset = (0.9, -1.2, 0.5) if index else (0.55, -0.65, 0.85)
            if up_axis == 1:
                offset = (offset[0], offset[2], offset[1])
            eye = center + Gf.Vec3d(*(radius * v for v in offset))
            target = center - up * radius * 0.15 if args.sim == "franka" else center
            if index and "room_view" in preset:
                eye, target = (Gf.Vec3d(*point) for point in preset["room_view"])
            matrix = Gf.Matrix4d().SetLookAt(eye, target, up).GetInverse()
            if not existing:
                camera.AddTranslateOp().Set(matrix.ExtractTranslation())
                camera.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(
                    matrix.ExtractRotationQuat()
                )
            prim = camera.GetPrim()
            prim.ApplyAPI("OmniSensorAPI")
            cameras.append(
                CameraSensor(
                    # Franka uses wall-clock physics catch-up. Render the
                    # newest state once per camera loop, never older sensor
                    # ticks accumulated during a slow frame.
                    RtxCamera(
                        path,
                        tick_rate=0 if args.sim == "franka" else 30,
                        reset_xform_op_properties=False,
                    ),
                    resolution=(height, width),
                    annotators=["rgb"],
                )
            )
            endpoint = f"ipc://{args.directory}/{key}.sock"
            depth_enabled.append(False)
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
            import omni.appwindow
            from omni.kit.viewport.utility import get_active_viewport

            if not omni.appwindow.get_default_app_window():
                raise RuntimeError(
                    "Isaac Sim could not open the desktop display; check simulator.log"
                )
            viewport = get_active_viewport()
            viewport.camera_path = manifests[0]["prim_path"]
            viewport.fill_frame = False
            viewport.resolution = (width, height)
        # Arm and roll feedback use the articulation; jaw feedback is separate.
        feedback = JointFeedback(
            stage,
            preset["root"],
            drives,
            5 if args.sim == "mira" else 7,
            gripper_joints={arm: str(joints[5].GetPath()) for arm, joints in drives.items()}
            if args.sim == "mira"
            else None,
        )
        cartesian_feedback = None
        if args.sim == "mira":
            from telesurgery_sim.runtime.mira import MiraFeedback

            cartesian_feedback = MiraFeedback(stage, drives)
        if args.sim == "franka":
            from telesurgery_sim.runtime.franka import FrankaFeedback

            if fingers and len(fingers) != 2:
                raise RuntimeError("Incomplete Franka finger drives")
            robot.gripper_ranges = {"hand": (0.0, 0.04)} if fingers else {}
            cartesian_feedback = FrankaFeedback(feedback, fingers)
        timeline = omni.timeline.get_timeline_interface()
        if args.sim == "franka":
            import carb.settings
            from omni.kit.loop import _loop

            # Isaac's standalone loop runner defaults to 1/60 s per update,
            # regardless of camera rendering time. Follow wall time like the
            # jog controller, with bounded physics catch-up after slow frames.
            _loop.acquire_loop_interface().set_manual_mode(False)
            settings = carb.settings.get_settings()
            settings.set_bool("/app/player/useFixedTimeStepping", False)
            settings.set_int("/persistent/simulation/minFrameRate", 10)
            physics = PhysxSchema.PhysxSceneAPI.Apply(stage.GetPrimAtPath("/World/Physics"))
            physics.CreateTimeStepsPerSecondAttr(120)
        timeline.play()
        progress("Warming up camera rendering")
        pending = queue.Queue(maxsize=8)
        sequence = 0
        command_sequence = 0
        robot_lock = threading.Lock()
        feedback_at = time.monotonic()

        def handle(socket):
            nonlocal command_sequence
            for raw in socket:
                request = {}
                try:
                    request = json.loads(raw)
                    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                        raise ValueError("Expected JSON-RPC 2.0")
                    if request.get("method") == "camera.configure":
                        future = Future()
                        pending.put_nowait((time.monotonic(), request, future))
                        result = future.result(timeout=10)
                    else:
                        # Camera rendering must not delay input or hold requests.
                        # Only pure controller state is touched on this thread;
                        # USD drives and physics stay on the Isaac thread.
                        with robot_lock:
                            if time.monotonic() - feedback_at > 1:
                                robot.apply({"method": "hold"})
                                raise ValueError("Simulator physics feedback is stale")
                            result = robot.apply(request)
                            if request.get("method", "").startswith(("set_", "jog_")):
                                command_sequence += 1
                    reply = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
                except (ValueError, TypeError, KeyError, queue.Full, TimeoutError) as exc:
                    reply = {
                        "jsonrpc": "2.0",
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32602, "message": str(exc)},
                    }
                socket.send(json.dumps(reply))

        server = serve(handle, "127.0.0.1", args.api_port, max_size=4096)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        ready = set()
        while app.is_running() and not (args.directory / "stop").exists():
            frame_started = time.monotonic()
            applied = []
            for _ in range(8):
                try:
                    received, request, future = pending.get_nowait()
                except queue.Empty:
                    break
                try:
                    if time.monotonic() - received > 5:
                        raise ValueError("Expired simulator command")
                    params = request["params"]
                    size = (params["width"], params["height"])
                    if size not in RESOLUTIONS:
                        raise ValueError("Unsupported simulation resolution")
                    index = next(
                        (i for i, m in enumerate(manifests) if m["id"] == params["id"]), None
                    )
                    if index is None:
                        raise ValueError("Unknown simulation camera")
                    with_depth = params.get("depth", False)
                    if (
                        cameras[index].resolution != (size[1], size[0])
                        or depth_enabled[index] != with_depth
                    ):
                        cameras[index] = CameraSensor(
                            cameras[index].authoring_object,
                            resolution=(size[1], size[0]),
                            annotators=["rgb", "distance_to_image_plane"]
                            if with_depth
                            else ["rgb"],
                        )
                        depth_enabled[index] = with_depth
                        gc.collect()  # Release the previous render product on the Isaac thread.
                        print(f"{params['id']}: rendering at {size[0]} × {size[1]}", flush=True)
                    result = True
                    applied.append((future, result))
                except (ValueError, TypeError, KeyError) as exc:
                    future.set_exception(exc)
            with robot_lock:
                robot.advance()
                targets = {arm: list(pose) for arm, pose in robot.pose.items()}
                finger_target = robot.finger_target
                joint_velocity = robot.joint_target_velocity
                applied_sequence = command_sequence
            for arm, joints in drives.items():
                for index, drive in joints.items():
                    drive.GetTargetPositionAttr().Set(targets[arm][index])
                    if args.sim == "franka":
                        # Feed forward the same bounded trajectory velocity.
                        # A zero velocity target makes drive damping resist a
                        # held jog and leaves the tool trailing its target.
                        drive.GetTargetVelocityAttr().Set(joint_velocity[index])
            for drive in fingers.values():
                drive.GetTargetPositionAttr().Set(finger_target)
            for future, result in applied:
                future.set_result(result)
            app.update()
            measured = feedback.read()
            if cartesian_feedback:
                measured.update(cartesian_feedback.read(measured))
            with robot_lock:
                robot.feedback = measured
                if cartesian_feedback:
                    robot.kinematics = cartesian_feedback.kinematics
                feedback_at = time.monotonic()
            for index, camera in enumerate(cameras):
                pixels, _ = camera.get_data("rgb")
                capture_started = time.monotonic_ns()
                if pixels is None:
                    continue
                rgb = np.asarray(pixels.numpy(), dtype=np.uint8)
                if not rgb.size:
                    continue
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                header = VideoHeader(
                    sequence,
                    time.time_ns(),
                    bgr.shape[1],
                    bgr.shape[0],
                    sim_command_sequence=applied_sequence,
                    source_started_ns=capture_started,
                )
                header, data = encode_raw(Frame(header, bgr))
                if depth_enabled[index]:
                    from telesurgery_core.video.depth import attach

                    distances, _ = camera.get_data("distance_to_image_plane")
                    if distances is not None:
                        values = np.asarray(distances.numpy(), dtype=np.float32).reshape(
                            bgr.shape[:2]
                        )
                        header, data = attach(header, data, values)
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
                                    "id": args.sim,
                                    "name": preset["robot"],
                                    "kind": args.sim + "-sim",
                                    "uri": f"ws://127.0.0.1:{args.api_port}",
                                }
                            ],
                        },
                        indent=2,
                    )
                )
                temporary.replace(manifest)
                print(f"{args.sim} ready: {len(cameras)} cameras and robot controller", flush=True)
            time.sleep(max(0, 1 / 30 - (time.monotonic() - frame_started)))
        (args.directory / "result.json").write_text(
            json.dumps(
                {"frames": sequence, "commands": command_sequence, "drive_targets": robot.pose},
                indent=2,
            )
        )
    except Exception:
        traceback.print_exc()
        raise
    finally:
        if server:
            server.shutdown()
        for publisher in publishers:
            publisher.close()
        app.close(wait_for_replicator=False)


if __name__ == "__main__":
    main()
