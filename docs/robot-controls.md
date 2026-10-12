# Robot controls

The patient connects robots and grants surgeon access. A surgeon's first input takes the exclusive robot lock. **Stop / Esc** requests a hold and releases that lock. **Disconnect**, on the patient side, releases the controller connection without powering off the robot.

The surgeon lists connected robots automatically. Use the panel's pop-out icon to open the native controller beside Holoviz; keep that window focused for keyboard or gamepad input. The icon changes to **Dock robot controls**; click it or close the window to return controls and speed settings to the dashboard. **Pop out all**, beside Fullscreen, opens selected live or stale streams in Holoviz and opens the native robot controller. **Dock all** returns browser-compatible views and controls to the dashboard and closes the native windows. You can also launch controls with `./run.sh controller --server http://127.0.0.1:8002`. The window runs on the surgeon service's desktop, using its existing approved session; native setup installs Python Tk and SDL2 for keyboard and gamepad input.

## Keyboard and gamepad

**Arm-base directions:** Franka and CMR tool movement uses the selected arm’s fixed base: forward is +X, left is +Y, and up is +Z. These directions stay fixed when the tool or camera rotates. CMR arms face different directions, so the same input can move opposing arms in opposite directions on screen. “Left arm” identifies an arm; it does not define the movement direction. MIRA tool mode uses its robot-base X/Y/Z axes; joint mode increases or decreases the labeled joint.

In joint mode, tap a key or click its on-screen button for a short move. Hold it to move continuously after 450 ms; the target advances without waiting for the previous move to finish. Tool mode starts continuous motion immediately. Releasing held input requests a smooth stop.

MIRA has independent **Arm speed**, **Roll speed**, and **Grip speed** sliders, shared by keyboard, gamepad and on-screen controls. Their defaults are **20%, 50%, and 40%**, respectively. Percentages are relative to the node's configured limits; they set the requested rate, not measured robot speed. Arm and roll increments account for elapsed input time and stay within the node's per-command limit. Changing a speed stops active input and requires a fresh enable/key press. The keyboard shows both arms side by side; gamepad joint positions stay visible in compact left/right rows below the controls.

Franka uses one **Arm speed** slider, defaulting to **20%**, for keyboard, gamepad, on-screen controls, and Home. On current physical and simulation nodes, all three inputs move the configured tool tip in space; inverse kinematics coordinates all seven joints. Joint positions remain visible below the tool controls, and active directions highlight. Both keyboard and gamepad offer **Tool movement** and **Individual joints (advanced)** in the browser and native controller. CMR Versius uses the same choices. Switching modes stops motion; release held controls before resuming. Older nodes without Cartesian support retain joint controls. The joint speed limit is 4°/s at 20% and 20°/s at 100%; acceleration, joint configuration, and short moves can reduce actual speed. Joint-mode keyboard step limits are:

| Robot                          | Default step        | Maximum step | Default speed              |
| ------------------------------ | ------------------- | ------------ | -------------------------- |
| Franka, physical or simulation | 0.2° at 20%         | 5°           | 4°/s at 20%; up to 20°/s   |
| Physical MIRA                  | Arm 0.2°; roll 0.5° | 1°           | Vendor controller          |
| Simulated MIRA                 | Arm 1°; roll 2.5°   | 5°           | Simulation controller      |

Franka and CMR tool-mode keyboard mappings match the gamepad's arm-base directions:

| Motion | Keys |
| --- | --- |
| Forward / back | W / S |
| Left / right | A / D |
| Up / down | R / F |
| Turn left / right | Q / E |
| Tilt left / right | ← / → |
| Tilt forward / back | ↑ / ↓ |

Hold keys or on-screen buttons to move; release to stop. Multiple axes can be held together. Commands refresh immediately without the joint-mode repeat delay, and slow replies never queue old directions. After an interruption, release and press again.

In joint mode, keys increase/decrease the corresponding joint:

| Robot / arm | J1    | J2    | J3    | J4    | J5    | J6    | J7    |
| ----------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Franka      | Q / A | W / S | E / D | R / F | T / G | Y / H | U / J |
| MIRA left   | Q / A | W / S | E / D | R / F | —     | —     | —     |
| MIRA right  | U / J | I / K | O / L | P / ; | —     | —     | —     |

Both MIRA arms accept input simultaneously. MIRA starts in joint mode; choose **Tool movement · X/Y/Z + elbow** to map the first four keys for each arm to X, Y, Z and elbow angle. Tool roll and gripper bindings stay the same. Gamepad tool mode uses LB/L1 for X/Y and LB/L1 + RB/R1 for Z/elbow, with the same enable and release behavior as joint mode. Typing in a field, opening a dialog, losing focus or losing access stops input. Release and press again to resume.

MIRA tool roll uses **T / G** on the left and **Y / H** on the right. Tap to step or hold to rotate; the application limits roll to ±180°.

For a gamepad, press a button and select its name in the input dropdown. Compatible Xbox, PlayStation and Nintendo Switch controllers use standard button positions. Labels and icons follow the selected controller in the browser and native window:

| Binding | PlayStation | Xbox | Nintendo Switch |
| --- | --- | --- | --- |
| Enable / second joint group | L1 / R1 | LB / RB | L / R |
| Close / open CMR or MIRA right gripper | □ / ○ | X / B | Y / A |
| Increase / decrease MIRA right tool roll | △ / ✕ | Y / A | X / B |
| Home shortcuts (hold 1s) | PS / Options | Xbox / Menu | Home / + |

Below, LB/L1 means the enable shoulder (Nintendo L), and RB/R1 means the other shoulder (Nintendo R). Switch 2 Pro USB startup is configured automatically by `setup.sh`. Xbox hardware verification is pending.

- Center the sticks and release tool buttons before starting. MIRA and direct-joint Franka controls use **LB/L1** to enable input; release it to stop and release the lock. Franka tool controls work directly from neutral, without a shoulder button.
- **MIRA J1–J2:** hold **LB/L1** and move each stick to control its arm. Horizontal movement controls J1; vertical movement controls J2.
- **MIRA J3–J4:** with both sticks centered and tool buttons released, hold **LB/L1 + RB/R1** in either order, then move the sticks. Keep both shoulder buttons held: horizontal movement controls J3; vertical movement controls J4. RB/R1 alone does not enable motion. While input is armed and idle, adding or releasing RB/R1 switches joint pairs without releasing LB/L1. Changing pairs during movement, with a tool button held, or with a command still pending stops input and requires releasing LB/L1 and centering the controls before enabling again. Changing RB/R1 cannot resume input after a loss of focus, permission, or connection.
- **MIRA tool roll:** while holding **LB/L1**, hold **D-pad up / down** to increase/decrease left tool roll, or **Triangle / Cross** (Xbox **Y / A**, Nintendo **X / B**) for right tool roll. Release the roll button to stop that tool; opposite directions together cancel. **Roll speed** sets the rotation rate independently of arm speed. Sticks continue controlling J1–J4; there is no roll mode switch or stick-click binding.
- **MIRA grippers:** while holding **LB/L1**, hold **D-pad left / right** to close/open the left gripper, and **Square / Circle** (Xbox **X / B**, Nintendo **Y / A**) to close/open the right. Release the gripper button to stop that gripper; release LB/L1 to stop all gamepad motion. Opposite directions together cancel. Release all gripper buttons and center the sticks before enabling. **Grip speed** applies to controller buttons as well as keyboard and on-screen input.
- **Franka tool movement:** move the controls directly; **LB/L1 is not required**. The **left stick** moves left/right and forward/back; **right stick up/down** raises/lowers the tool, and **right stick left/right** turns it. **D-pad left/right** tilts sideways; **D-pad up/down** tilts forward/back. Center the sticks and release D-pad to stop. After Stop/Esc, a speed change, loss of focus, or reconnection, return all controls to neutral before moving again. No joint groups or stick clicks are needed. Left turn is +Z rotation; D-pad left is +X rotation and D-pad up is −Y rotation. **Arm speed** scales translation and rotation together: at 20%, requested maxima are 0.02 m/s and 6°/s, additionally bounded by the joint speed limit.
- **Simulated Franka grip, when available:** press **Square** (Xbox **X**, Nintendo **Y**) to toggle open/closed. **Stop / Esc** interrupts the motion, and **Grip speed** sets the rate. Keyboard uses **Z / X**, and on-screen buttons remain available. The Healthcare scene on Spark has a **fixed surgical instrument**, so it exposes no gripper controls; its actual **TCP** is the controlled tool tip.
- **CMR Versius grip:** hold **Square** (Xbox **X**, Nintendo **Y**) to close, or **Circle** (Xbox **B**, Nintendo **A**) to open. Release to stop; pressing both cancels. No shoulder button is needed in tool mode. **Grip speed** sets the rate; keyboard uses **Z / X**. The native and browser controllers use the same bindings.
- **Franka / CMR individual joints:** select **Individual joints (advanced)**. Hold **LB/L1** for J1–J4 (left stick J1/J2, right stick J3/J4), or **LB/L1 + RB/R1** for the remaining joints (left stick J5/J6, right stick J7/J8 where available). Hold **LB/L1 + Square / Circle** (Xbox **X / B**, Nintendo **Y / A**) to close/open a hand gripper. Changing groups during motion requires releasing LB/L1 and centering the sticks. Older Franka nodes without Cartesian support retain joint controls; physical nodes must rebuild the native adapter before advertising tool control.
- **Home:** use the on-screen house button, or, with sticks centered and tool buttons released, hold the **PS / Xbox logo button** or Nintendo **Home** button for one second. MIRA and direct-joint Franka also require LB/L1 released. If the operating system intercepts the logo button, use **Options** (PlayStation, right of the touchpad), **Menu ☰ / Start** (Xbox, right of the Xbox logo), or Nintendo **+**. A countdown appears before the request. A tap does nothing; release and hold again for another request. Switching or overlapping Home shortcuts cancels the hold; release both before retrying. The same availability checks apply as the on-screen Home button. **Stop / Esc** interrupts Home.

Input sends the latest command at up to 20 Hz without queuing moves. Franka's simulator expires tool input after 500 ms without a fresh command, allowing for the 300 ms command transport window plus refresh/render scheduling; physical Franka tool input and joint jogging retain their 200 ms deadline. Releasing input or pressing Stop sends a hold immediately. A lost controller or permission cannot resume motion automatically.

The Franka simulator derives the tool Jacobian and pose from live PhysX feedback. Damped inverse kinematics limits velocities near singularities; joint speed, acceleration, jerk, and joint-range limits still apply. Missing/stale physics feedback or excessive target tracking error initiates a smooth stop. Cartesian jogging does not plan collision-free paths.

The Franka scene follows wall time with 120 Hz physics and bounded catch-up after slow frames. Cameras render the newest state once per update. Position drives receive both the planned position and velocity so damping does not resist commanded motion. Isaac's default standalone update advances only 1/60 second per camera update, which would let real-time joystick targets outrun physics in this 30 Hz camera loop.

The Healthcare Franka scene uses inertia-scaled drives, 0.01 kg·m² joint armature, and a 30°/s physics velocity bound to stabilize aligned shoulder axes. These simulator settings follow the [PhysX articulation stability guidance](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.0/dev_guide/guides/articulation_stability_guide.html) and do not apply to physical Franka. Cartesian acceleration and jerk limits are 1 rad/s² and 10 rad/s³, giving a planned full-speed release ramp under half a second. Home retains its slower position trajectory.

## Franka

Docker includes the Franka adapter. For native execution, run `./setup.sh --profile franka`, then start the node from a new login session. It installs libfranka 0.15.2 (protocol 9) and realtime scheduling permissions. Use a [firmware-compatible libfranka](https://frankarobotics.github.io/docs/compatibility.html), a realtime kernel and FCI enabled in Desk.

Create and save a physical device profile on first use:

```bash
./run.sh --docker node --patient PATIENT_IP --profile franka
```

The default address is `172.16.0.3`. Supply `--franka-address ROBOT_IP` to save a different address; later starts reuse it without the option. Alternatively, add to the node's `devices.yaml`:

```yaml
robots:
  - id: franka
    name: Franka
    kind: franka
    address: 172.16.0.3
    connection_enabled: false
    motion_enabled: true
```

Click **Connect** on the patient dashboard. Physical tool jogging uses the configured end-effector Jacobian from libfranka in the native 1 kHz loop. Damped inverse kinematics feeds synchronized Ruckig joint velocity trajectories, with the same tool mapping and speed scale as simulation. The planner slows before joint limits and limits acceleration to 1 rad/s² and jerk to 10 rad/s³. Home and advanced joint moves keep their existing position trajectories. The native loop stops on missing input after 200 ms; release/Stop requests braking immediately. Desk collision thresholds, motor enable and fault recovery remain under the operator’s control. Feedback shows measured joints separately from targets. Choose **Disconnect** before using Desk tasks.

**Home** uses the shared fixed reset pose for physical and simulated Franka: `[-24.475, -18.378, 13.651, -106.151, 9.422, 90.758, -21.335]°`. Simulated grippers, when advertised, return to their open starting position; Home waits for measured gripper completion. Physical Franka gripper control is not exposed. Verify the path with an operator present; **Stop / Esc** interrupts it. Physical sustained control, Home and soft Stop were operator-verified on the tested setup; per-installation home calibration remains on the [TODO list](TODO.md). Motor enable and fault recovery are not exposed.

## MIRA

**Home** returns both arms to `[15.7, 80.6, 45, 98.9]°`, resets tool roll to 0°, and closes both grippers, matching simulation startup. Both physical and simulated Home block manual input until arms and tools reach their targets; **Stop** cancels Home and holds measured positions. Physical Home also requests a hold after a timeout or failed tool command.

With Keyboard selected, hold **Z / X** to close/open the left gripper, or **N / M** for the right. With a gamepad selected, the panel shows that controller's gripper bindings instead. The on-screen buttons work in either mode. Release to stop; **Grip speed** is independent of arm and roll speed. Both simulation and physical MIRA use these controls. Physical grippers require successful tool homing through the vendor controller; arm **Home** does not calibrate tools or bypass this requirement.

Use the **Virtual Incision MIRA API** supplied by the vendor. Request the current Linux API and POD firmware documentation from [Virtual Incision](https://virtualincision.com/customer-support/); `mira-project.org` is unrelated middleware.

Tool mode uses the vendor forward-kinematics and inverse-kinematics queries, followed by a bounded absolute joint target. It does not accumulate the vendor's persistent Cartesian delta target. Coordinates use the MIRA base frame: XYZ in millimeters, elbow and roll in degrees. Each command is limited to 0.5 mm translation and 1° elbow/roll, with at most 1° change per arm joint. Invalid, unreachable or discontinuous IK results are rejected. Release/Stop requests a measured-position hold; missing tool input expires after 200 ms. Isaac Sim derives its own Jacobian from the loaded asset and measured joints, using the asset's base frame with the same input units and bounds.

Start with the MIRA profile:

```bash
./run.sh --docker node --patient PATIENT_IP --profile mira
```

Copy the vendor API executable to `workspace/mira-api` first (`PATH/mira-api` with `--workspace PATH`). If it is missing on first use in a terminal, the launcher asks for its path. For scripts or unattended startup, supply the path directly:

```bash
./run.sh --docker node --patient PATIENT_IP --profile mira \
  --mira-api /path/to/MiraAPI-linux-arm64-2025-07-18
```

The profile checks the executable's ELF architecture, saves it as `workspace/mira-api`, marks it executable, and records its SHA-256 checksum. The vendor binary stays local in the workspace; it is not fetched, uploaded or embedded in the Docker image. Docker mounts an explicitly supplied file read-only during installation.

Later starts reuse the saved executable without prompting:

```bash
./run.sh --docker node --patient PATIENT_IP --profile mira
```

The node's POD-facing address defaults to `192.168.0.1`. Set `--mira-pod-interface IP` to save a different address; this does not configure the host's network interface or change the POD address embedded in the vendor API. The supplied July build targets `192.168.0.10:10000` (UDP). Configure the node interface as `192.168.0.1/24` for that package.

The robot initially appears disconnected. The patient can start the supplied controller in Docker, then connect to its loopback WebSocket API. Vendor startup can enable motor power, so the dashboard requires operator confirmation. The July 2025 API generates its lookup table on first controller startup; allow extra time and about 503 MB of disk space. Generated data and logs persist in the node's controller directory.

Native node execution supports the same profile options, but the managed MIRA controller still requires Docker and the matching image locally: `holoscan-telesurgery:0.1.0` for SDK 5 or `holoscan-telesurgery:0.1.0-sdk4` for SDK 4.

For an existing manual setup, the equivalent `devices.yaml` entry is:

```yaml
robots:
  - id: mira
    name: MIRA
    kind: mira
    uri: ws://127.0.0.1:8081
    connection_enabled: false
    motion_enabled: true
    controller:
      executable: /absolute/path/MiraAPI-linux-arm64-2025-07-18
      pod_interface: 192.168.0.1
```

Install the executable and image first when configuring manually. Omit `controller` when managing the API externally. Remove the manual robot entry before selecting a profile with the same robot ID.

Physical jogs use reported joint positions; tool roll uses the vendor's absolute roll command. Release requests the measured position as a hold target. Home, tool operation and network-loss behavior were operator-verified on the tested setup. Review of the supplied July 2025 API and its backend found that motion methods are notifications, position queries return the vendor's cached POD state without a hardware timestamp, and no acknowledged stop or POD-side command watchdog is exposed. A query reply establishes communication, not completion or freshness of physical motion. The adapter reports these limits explicitly and never replays a failed move. Precise arrival and an independent hardware stop/watchdog require vendor support. Keep a physical stop available. Set `motion_enabled: false` for feedback only.

## Versius simulation

Each simulated Versius arm is a separate robot with its own exclusive surgeon lock, feedback and Stop. The scene follows the four-bedside-unit layout in the [CMR user manual](https://cmrsurgical.com/wp-content/uploads/2022/11/U-00009v15-VersiusSurgicalSystem-UserManual-English-UK.pdf): three instrument arms and one endoscope arm share a suture pad and curved needle. The real system has one 3D HD endoscopic camera assembly; this simulation provides a 1080p procedure view with optional depth and an additional 1080p room observer view. The left and right needle holders support a two-surgeon pickup, handoff and placement demonstration; the assistant arm carries a grasper. The procedure camera moves with the endoscope arm, whose shaft is a simple simulation proxy because the supplied archive has no endoscope asset. Tool movement uses the live PhysX Jacobian and measured pose in each arm’s base frame, with the same keyboard/gamepad mapping as Franka; the opposing bases have opposing X/Y directions. Gripper controls open and close the needle-holder jaws. Closing near the training object attaches a proximity grasp constraint; the other arm can receive it when the first opens. This provides a repeatable handoff demonstration without modeling surgical contact forces. This is an asset-based simulation; no physical Versius protocol or private CMR kinematics library is required.

## Saved device profiles

Profiles live in `workspace/profiles/mira.yaml` and `workspace/profiles/franka.yaml`, under `--workspace` when supplied. Edit the profile's `robot` settings to change its ID, display name, endpoint or motion permission, then restart the node. Pass a new `--mira-api` or replace `workspace/mira-api` to install a replacement API on the next node start.

Combine physical devices with `--profile franka --profile mira`. The selection is remembered per node name, so later starts of that node can omit `--profile`. An explicit selection replaces the saved selection; `--profile none` clears it. Physical profiles cannot be combined with `--sim`.

Connections remain node-local. Restarting with unchanged settings preserves the patient's connection choice; adding or changing a profile resets that robot to disconnected. Selecting a profile never starts the vendor controller. Cameras and manually configured robots continue to use `devices.yaml`; duplicate robot IDs are rejected.

## Adding a robot

Device configuration lives in `workspace/nodes/NAME/devices.yaml` on the robot's node, under the directory supplied with `--workspace`.

1. Implement the [adapter contract](../packages/robots/src/telesurgery_robots/adapters/base.py): `read`, `jog`, `hold`, `close`, plus advertised joint groups and motion limits. Constructors must not enable motors. Bound device calls and never replay failed motion.
2. Register the class in the `telesurgery.robots` package entry points. Optional `step` and `home` methods expose those actions; an optional controller factory supports patient-managed startup.
3. Add its `kind` and connection settings to `devices.yaml`. Shared Holoscan graphs handle admission, ownership, commands and feedback.

Report `joints_deg` as measurements and `targets_deg` as targets. Feedback is polled at up to 10 Hz independently of camera streams; stale feedback disables input. `observed_at` is the node's receipt time, not a hardware timestamp.

Temporary feedback errors recover after valid feedback and a successful hold. Recovery never replays motion; release the input and press again. Vendor faults and unhomed tools require attention at the controller.
