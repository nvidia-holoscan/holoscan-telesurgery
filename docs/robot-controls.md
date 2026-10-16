# Robot controls

The patient connects robots and grants surgeon access. Choose **Acquire** to take exclusive control; the status changes from **Available** to **Active** with the surgeon's name. Neutral input, **Stop / Esc**, and focus loss stop movement while keeping control. The **Release control** icon beside the status frees the robot for another surgeon. The patient can use **Force release robot control** if needed; this ends ownership without removing access. Closing the controller, disconnecting, or losing the control heartbeat also releases ownership. **Disconnect**, on the patient side, releases the controller connection without powering off the robot.

The browser remembers your input device for each robot and patient connection, including before acquiring control. Normal refresh and Ctrl+Refresh restore that choice once the device is detected; refresh does not acquire control or resume movement. Choosing Keyboard replaces the saved device preference.

The surgeon lists connected robots automatically. Changing the robot in the browser or native controller pauses input. If you have control, confirm **Release control and switch**; the selection changes only after release succeeds. **Cancel** keeps the current robot selected and motion paused. Acquire the new robot separately.

Use the panel's pop-out icon to open the native controller beside Holoviz; keep that window focused for keyboard or gamepad input. The icon changes to **Dock robot controls**. Popping out and docking pause movement and transfer your existing control lease for the same robot; there is no need to Acquire again. The receiving interface starts with fresh input, and Haply requires Start. A failed lease validation never acquires control automatically. Closing the native window with its window-manager close button still releases control. **Pop out all**, beside Fullscreen, opens selected live or stale streams in Holoviz and opens the native robot controller. **Dock all** returns browser-compatible views and controls to the dashboard and closes the native windows. You can also launch controls with `./run.sh controller --server http://127.0.0.1:8002`. The window runs on the surgeon service's desktop, using its existing approved session; native setup installs Python Tk and SDL2 for keyboard and gamepad input.

Every simulation has a **Reset scene** icon beside Home in the browser and native controller. After acquiring control, use it to restore the robot and movable task objects to their starting positions and clear motion. The node and camera streams stay running. In CMR Versius, resetting from any arm restores all four arms and the shared needle. Reset is available only while you control the selected arm and every other arm in that scene has been released and stopped, including the assistant and endoscope. The patient service enforces this rule when the request arrives. Each scene’s tooltip describes what will reset; CMR also explains when another arm blocks it. Haply stays paused until you press Start again.

The browser and native controller also show **Replay inputs** when you own a simulation arm with a verified recording for the selected keyboard, gamepad or Haply input. Reset the scene before replaying, then select Replay to run the saved task. Replay progress appears below the toolbar. For MIRA, Franka and CMR, keyboard keys and gamepad sticks, rotation and gripper controls highlight the bindings corresponding to the command being dispatched. Checkpoint replays derive these indicators from live corrections toward measured poses; older device recordings show their saved inputs. These are control indicators, not operating-system key injection. The display follows tool/joint mode automatically and restores your manual mode when replay ends. A checkpoint can move both gamepad joint groups together, so each group displays its own active stick directions. Highlights clear on release, completion or Stop. Haply has no replay input highlights. Stop/Esc cancels playback while keeping control. Changing input or robot, hiding or closing the controller, or losing control permission stops replay. A visible native controller can keep replaying while Holoviz has focus. For CMR, the left replay picks up the needle and completes while holding it. Keep its control lease, then start the right replay whenever ready. Once the right replay grasps the presented needle, it automatically opens the left gripper before lifting; the left arm stays in place. If no completed left pickup is available when the right replay starts, it performs an empty pickup 3 cm to the side, clear of the left tool at Home, and completes. Each side can independently use keyboard, gamepad or Haply. Automatic release applies only to replay; manual control retains its normal behavior. See [saved controller replays](../examples/controller-replays/README.md) for the tasks and setup.

## Keyboard and gamepad

**Arm-base directions:** Franka and CMR tool movement uses the selected arm’s fixed base: forward is +X, left is +Y, and up is +Z. These directions stay fixed when the tool or camera rotates. CMR arms face different directions, so the same input can move opposing arms in opposite directions on screen. “Left arm” identifies an arm; it does not define the movement direction. MIRA tool mode uses its robot-base X/Y/Z axes; joint mode increases or decreases the labeled joint.

In joint mode, tap a key or click its on-screen button for a short move. Hold it to move continuously after 450 ms; the target advances without waiting for the previous move to finish. Tool mode starts continuous motion immediately. Releasing held input requests a smooth stop.

**Arm speed**, **Rotation speed**, and **Grip speed** are percentages of the selected robot's configured operating rates. At 50%, the requested rate is half its 100% rate; the same free travel takes approximately twice as long after acceleration. Physical and simulated robots may use different maxima. Contact, joint limits, acceleration and short travel can reduce measured speed. Changing a speed stops active input and requires fresh input. Controls appear only for supported motions and installed grippers.

Physical MIRA defaults to **70% arm, 90% rotation, 90% grip**. MIRA simulation defaults to **20%, 50%, 40%**. Physical Franka defaults to **75% arm**; Franka/CMR simulation defaults to **20% arm**. Their tool rotation defaults to **50%**, and available grippers to **40%**. Saved user choices take precedence. The browser and native controller use the same rates for keyboard, gamepad and Haply.

| Robot | Joint rate at 100% | Rotation rate at 100% | Grip rate at 100% |
| --- | --- | --- | --- |
| Physical MIRA | 20°/s | 40°/s tool roll | 100% of vendor command range/s |
| MIRA simulation | 30°/s | 100°/s tool roll | 50% of full travel/s |
| Franka physical / simulation; CMR simulation | 20°/s joint envelope | 30°/s tool orientation, subject to joint envelope | 50% of full travel/s, where supported |

These are application operating limits, not certified hardware maximum ratings. MIRA simulation's 30°/s arm and 100°/s roll limits are shared with its PhysX drives; the 40° jaw range and 20°/s jaw cap correspond to 50% travel/s. Physical MIRA's roll and grip operating rates are twice their previous 20°/s and 50% travel/s settings. At the 90% defaults they request 36°/s roll and 90% of the vendor command range per second for grip. The supplied vendor source (`~/mira/api_backend_src/crates/api/src/main.rs`) has a 150°/s software limiter for the first four joints during target approach, and tool-drive ranges of 1150/1350 counts. That limiter is not a documented roll/gripper rating, and those counts are travel, not speed. The public [MIRA product information](https://virtualincision.com/mira/) does not specify numerical joint/roll/gripper speed ratings; vendor-confirmed limits should replace the operating caps only after review.

MIRA joint input sends requested rates to a local acceleration/jerk-limited planner. Physical MIRA polls that planner on a 10 ms schedule rather than stepping once per network reply. Physical targets stay within 1° of measured arm joints and 2° of measured tool roll, equivalent to 50 ms at their maximum rates. Simulation keeps a 1° lead for every joint. Feedback lead clamps preserve the velocity ramp; only an outward request at a mechanical boundary resets it. Input expires after 200 ms without refresh; delayed input cannot accumulate deferred travel. Gripper lead is limited to 100 ms of the requested rate. Legacy delta commands remain supported. MIRA Home completes once all arm/roll joints are within 1° and jaws within 1% of travel, with a stable pose for 250 ms. A 30-second timeout still requests a hold.

Franka and CMR tool movement uses **Arm speed** for translation (0.10 m/s at 100%) and **Rotation speed** for orientation independently. Inverse kinematics coordinates the arm within the configured joint envelope. Joint mode and Home use Arm speed for their joint rate. Both keyboard and gamepad offer **Tool movement** and **Individual joints (advanced)**. Switching modes stops motion; release held controls before resuming. Franka joint taps retain bounded steps (maximum 5°); MIRA joint keys now request motion while held, including short taps. Older recorded commands without an independent rotation limit retain their original coupled rate mapping.

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

MIRA tool roll uses **T / G** on the left and **Y / H** on the right. Hold to rotate and release to stop; the application limits roll to ±180°.

For a gamepad, press a button and select its name in the input dropdown. Compatible Xbox, PlayStation and Nintendo Switch controllers use standard button positions. Labels and icons follow the selected controller in the browser and native window:

| Binding | PlayStation | Xbox | Nintendo Switch |
| --- | --- | --- | --- |
| Enable / second joint group | L1 / R1 | LB / RB | L / R |
| Close / open CMR or MIRA right gripper | □ / ○ | X / B | Y / A |
| Increase / decrease MIRA right tool roll | △ / ✕ | Y / A | X / B |
| Home shortcuts (hold 1s) | PS / Options | Xbox / Menu | Home / + |

Below, LB/L1 means the enable shoulder (Nintendo L), and RB/R1 means the other shoulder (Nintendo R). Switch 2 Pro USB startup is configured automatically by `setup.sh`. Xbox hardware verification is pending.

- After acquiring control, center the sticks and release tool buttons before starting. MIRA and direct-joint Franka controls use **LB/L1** to enable input; release it to stop motion while keeping ownership. Franka tool controls work directly from neutral, without a shoulder button.
- **MIRA J1–J2:** hold **LB/L1** and move each stick to control its arm. Horizontal movement controls J1; vertical movement controls J2.
- **MIRA J3–J4:** with both sticks centered and tool buttons released, hold **LB/L1 + RB/R1** in either order, then move the sticks. Keep both shoulder buttons held: horizontal movement controls J3; vertical movement controls J4. RB/R1 alone does not enable motion. While input is armed and idle, adding or releasing RB/R1 switches joint pairs without releasing LB/L1. Changing pairs during movement, with a tool button held, or with a command still pending stops input and requires releasing LB/L1 and centering the controls before enabling again. Changing RB/R1 cannot resume input after a loss of focus, permission, or connection.
- **MIRA tool roll:** while holding **LB/L1**, hold **D-pad up / down** to increase/decrease left tool roll, or **Triangle / Cross** (Xbox **Y / A**, Nintendo **X / B**) for right tool roll. Release the roll button to stop that tool; opposite directions together cancel. **Rotation speed** sets the rotation rate independently of arm speed. Sticks continue controlling J1–J4; there is no roll mode switch or stick-click binding.
- **MIRA grippers:** while holding **LB/L1**, hold **D-pad left / right** to close/open the left gripper, and **Square / Circle** (Xbox **X / B**, Nintendo **Y / A**) to close/open the right. Release the gripper button to stop that gripper; release LB/L1 to stop all gamepad motion. Opposite directions together cancel. Release all gripper buttons and center the sticks before enabling. **Grip speed** applies to controller buttons as well as keyboard and on-screen input.
- **Franka tool movement:** move the controls directly; **LB/L1 is not required**. The **left stick** moves left/right and forward/back; **right stick up/down** raises/lowers the tool, and **right stick left/right** turns it. **D-pad left/right** tilts sideways; **D-pad up/down** tilts forward/back. Center the sticks and release D-pad to stop. After Stop/Esc, a speed change, loss of focus, or reconnection, return all controls to neutral before moving again. No joint groups or stick clicks are needed. Left turn is +Z rotation; D-pad left is +X rotation and D-pad up is −Y rotation. **Arm speed** scales translation; **Rotation speed** scales orientation. At 50% each, requested maxima are 0.05 m/s and 15°/s, additionally bounded by the joint envelope.
- **Simulated Franka grip, when available:** press **Square** (Xbox **X**, Nintendo **Y**) to toggle open/closed. **Stop / Esc** interrupts the motion, and **Grip speed** sets the rate. Keyboard uses **Z / X**, and on-screen buttons remain available. The Healthcare scene on Spark has a **fixed surgical instrument**, so it exposes no gripper controls; its actual **TCP** is the controlled tool tip.
- **CMR Versius grip:** hold **Square** (Xbox **X**, Nintendo **Y**) to close, or **Circle** (Xbox **B**, Nintendo **A**) to open. Release to stop; pressing both cancels. No shoulder button is needed in tool mode. **Grip speed** sets the rate; keyboard uses **Z / X**. The native and browser controllers use the same bindings.
- **Franka / CMR individual joints:** select **Individual joints (advanced)**. Hold **LB/L1** for J1–J4 (left stick J1/J2, right stick J3/J4), or **LB/L1 + RB/R1** for the remaining joints (left stick J5/J6, right stick J7/J8 where available). Hold **LB/L1 + Square / Circle** (Xbox **X / B**, Nintendo **Y / A**) to close/open a hand gripper. Changing groups during motion requires releasing LB/L1 and centering the sticks. Older Franka nodes without Cartesian support retain joint controls; physical nodes must rebuild the native adapter before advertising tool control.
- **Home:** use the on-screen house button, or, with sticks centered and tool buttons released, hold the **PS / Xbox logo button** or Nintendo **Home** button for one second. MIRA and direct-joint Franka also require LB/L1 released. If the operating system intercepts the logo button, use **Options** (PlayStation, right of the touchpad), **Menu ☰ / Start** (Xbox, right of the Xbox logo), or Nintendo **+**. A countdown appears before the request. A tap does nothing; release and hold again for another request. Switching or overlapping Home shortcuts cancels the hold; release both before retrying. The same availability checks apply as the on-screen Home button. **Stop / Esc** interrupts Home.

Input sends the latest command at up to 20 Hz without queuing moves. Franka's simulator expires tool input after 500 ms without a fresh command, allowing for the 300 ms command transport window plus refresh/render scheduling; physical Franka tool input and joint jogging retain their 200 ms deadline. Releasing input or pressing Stop sends a hold immediately. A lost controller or permission cannot resume motion automatically.

The Franka simulator derives the tool Jacobian and pose from live PhysX feedback. Damped inverse kinematics limits velocities near singularities; joint speed, acceleration, jerk, and joint-range limits still apply. Missing/stale physics feedback or excessive target tracking error initiates a smooth stop. Cartesian jogging does not plan collision-free paths.

The MIRA and Franka scenes follow wall time with 60 Hz physics and bounded catch-up after slow frames. Cameras render the newest state once per update. Franka position drives receive both the planned position and velocity so damping does not resist commanded motion. Isaac's default standalone update advances only 1/60 second per camera update, which would let real-time joystick targets outrun physics in this 30 Hz camera loop.

The Healthcare Franka scene uses inertia-scaled drives, 0.01 kg·m² joint armature, and a 30°/s physics velocity bound to stabilize aligned shoulder axes. These simulator settings follow the [PhysX articulation stability guidance](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.0/dev_guide/guides/articulation_stability_guide.html) and do not apply to physical Franka. Cartesian acceleration and jerk limits are 1 rad/s² and 10 rad/s³, giving a planned full-speed release ramp under half a second. Home retains its slower position trajectory.

## Haply · MIRA, Franka and Versius

Connect the Inverse3 base USB cable and wireless VerseGrip dongle to the **surgeon service's host**. External base power is not required for this tracking-only input. Native `setup.sh` reuses an installed Haply Hub, or installs Haply Inverse Service 3.5.6 on Ubuntu 22.04/24.04. On Ubuntu 26.04, install [Haply Hub](https://develop.haply.co/) before running setup. Keep Hub open on the surgeon host while using Haply input so its embedded service stays running. Docker includes the standalone service and passes through the connected Haply USB devices. Connect both USB devices before starting Docker; restart the surgeon container after reconnecting a device.

**Haply Inverse3** appears for adapters that expose Cartesian control when its USB base or dongle is detected on the surgeon host. This includes MIRA and Franka simulation and hardware, and the Versius simulation. Physical adapters expose this option only after motion is enabled in their device profile. Select it to check the base, grip, connection and calibration, before acquiring control. Calibrate the base at its magnetic calibration point and wake the grip with its power button. See [Haply's illustrated setup](https://docs.haply.co/docs/quick-start/). Input starts paused; MIRA selects the left arm. The browser and native controller show the active arm, measured **Arm tip · mm** coordinates, one XYZ direction diagram, and calibration or tracking issues. Browser input uses the device on the surgeon host, including when viewing that dashboard from another machine. Selecting Haply never acquires control or starts motion.

For every supported robot, select **Calibrate movement range** and sweep the pen through its comfortable left/right, forward/back and up/down travel while the robot stays stopped. Acquiring control is not required. Select **Save range**, then center the pen before Start. The browser and native controller share the range saved on the surgeon host for that base and mounting configuration, so switching robots does not require another sweep. Recalibrate after changing the mount or usable travel. A missing range prevents Start; saving, cancelling or reconnecting never starts motion. Hub's magnetic calibration remains a separate device setup step.

All supported adapters map the calibrated pen endpoints to robot-specific Cartesian operating extents. Start and clutch release anchor the mapping at the current pen and arm positions without a jump. Physical Franka calculates its extents with libfranka's model and configured tool frames; Franka and Versius simulations use the loaded articulation's kinematics and limits; physical MIRA queries the vendor's read-only IK; MIRA simulation uses its USD geometry. These calculations never move a physical robot. A missing range prevents Start and displays the reason. The robot range is refreshed while idle after repositioning or changing tool orientation. Physical Franka requires rebuilding the native adapter with `./scripts/build_franka.sh` before restarting the node.

These are axis travel extents at a reference orientation, not a collision-free box. Combined-axis movement, tool rotation or contact can constrain travel before an endpoint. Existing robot-side joint, speed, watchdog and collision protections remain in force. A pen sweep does not expand the physical robot's reach or raise its speed limits.

Tap the **single-dot button nearest the ball connector** to start/stop movement, and tap the **two-dot button just behind it** to switch left/right arms. While movement is active, hold single-dot to **close** the selected gripper or two-dot to **open** it. Gripping starts after 0.6 seconds at **Grip speed** and stops when you release; a hold does not also trigger a tap action. The three-dot button remains the grip's calibration button; no button combinations are needed. Move the pen to move the selected tool, tilt it up/down to angle the tool through MIRA’s elbow motion, and twist it along its length for tool roll. Arm speed limits translation and tilt; Roll speed limits twist. Tilt is relative to the pen angle when you start or switch arms and is independent of axial roll. Sideways pen rotation is not mapped to an independent tool orientation because MIRA exposes XYZ, elbow and roll. Orientation tracking uses the grip’s local Y axis, as described in [Haply’s orientation example](https://docs.haply.co/inverseSDK/service/tutorials/06-combined/). Tool movement pauses while pressing either button and resumes from a fresh pen reference on release. In the MIRA scene, pen right/forward/up follows the work area’s right/forward/up axes.

For Franka and Versius, tap single-dot to start/pause. Move the pen for XYZ translation and tilt or twist it to orient the tool. Starting captures the current tool and pen orientations; there is no pen button for switching robots. Once following, reaching the pen target sends zero velocity while fresh tracking continues, so resting the pen does not repeatedly stop and restart the Cartesian controller. You do not need to hold a pen button to stay active. In Versius, each surgeon acquires one independent arm; hold single-dot to close its gripper and two-dot to open it. Gripper input is available only when the adapter advertises a gripper: the Franka ultrasound probe and current physical Franka adapter do not. Pause and reposition the pen when you reach the edge of its workspace, then resume from a fresh reference.

Stop/Esc, changing speeds, lost focus, stale tracking or reconnection pauses motion. Tap the single-dot button to start again. Switching arms preserves whether movement is started or stopped. Each resume or arm switch captures the current pen and robot positions, so it does not jump. Tracking continuity is checked between device samples, rather than between slower browser or network updates: a continuous fast twist does not become a false tracking jump. A discontinuity remains detectable even if it occurs between control polls. Tracking and delayed-input pause reasons remain visible until movement resumes. This is position/orientation input without force feedback.

Haply tracking is sampled at about 100 Hz and remote targets update at up to 20 Hz. MIRA's patient-side follower moves toward the latest absolute target at the simulation servo rate; fewer network updates no longer reduce speed to a fixed distance per request. Faster pen movement produces faster tool movement within the configured limits. In the scaled simulation, the default 20% Arm speed caps translation at 300 mm/s and joint motion at 36°/s, with acceleration and measured tracking limits; a fast pen can still outrun the robot. Axial roll has its own tracking limit so a blocked roll does not prevent the tool from retreating. If contact displaces the tool outside its tracking margin, a step reducing the error is allowed. Stop or a 200 ms target timeout discards pending travel. Stale physics or persistent inability to follow still stops motion. Physical MIRA uses measured vendor FK and its existing bounded Cartesian jog/IK contract; physical Franka uses measured FCI pose and its existing native Cartesian loop. Simulation speeds and workspace extents are not applied to hardware. Both the surgeon service and patient node/simulation must be restarted after updating. Older physical nodes without workspace feedback must be updated before Haply Start; there is no silent fixed-gain fallback.

Haply support is selected by control capabilities, not a list of robot names. New Cartesian adapters publish `controls.cartesian` with `linear_speed_m_s` and `angular_speed_deg_s`, accept the existing bounded `translation`/`rotation` jog command, and provide `state.tool_pose.position_m` plus `orientation_matrix` in the robot base frame. Publish `state.cartesian_workspace.hand` with `frame`, `unit: "m"`, and three-element `min`/`max` arrays in the same base frame as the tool pose. Dual-arm adapters use `left`/`right` keys. The shared workspace calculator accepts model FK/Jacobians and joint limits; range calculation runs outside the servo loop. Optional `input_basis` configures the pen-to-base axes; the default maps pen right/forward/up to base −Y/+X/+Z. Hand and robot extents determine the distance ratio independently on each side of the Start position. The direction diagram uses that same basis. Grippers use the advertised `controls.grippers` keys and measured `state.grippers` values. MIRA's distinct XYZ/elbow/roll contract has its own mapping strategy. Device reading, saved hand-range calibration, continuity checks, start/pause, clutching, gripping, acquisition rules and the browser/native UI remain shared. Add a mapping strategy only for a genuinely different command contract, not for each new robot or simulated scene.

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
    motion_enabled: true
```

The node connects automatically after admission. Use **Connect** to retry a failed connection. Physical tool jogging uses the configured end-effector Jacobian from libfranka in the native 1 kHz loop. Damped inverse kinematics feeds synchronized Ruckig joint velocity trajectories, with the same tool mapping and speed scale as simulation. The planner slows before joint limits and limits acceleration to 1 rad/s² and jerk to 10 rad/s³. Home and advanced joint moves keep their existing position trajectories. The native loop stops on missing input after 200 ms; release/Stop requests braking immediately. Desk collision thresholds, motor enable and fault recovery remain under the operator’s control. Feedback shows measured joints separately from targets. Choose **Disconnect** before using Desk tasks.

**Home** uses the shared fixed reset pose for physical and simulated Franka: `[-24.475, -18.378, 13.651, -106.151, 9.422, 90.758, -21.335]°`. Simulated grippers, when advertised, return to their open starting position; Home waits for measured gripper completion. Physical Franka gripper control is not exposed. Verify the path with an operator present; **Stop / Esc** interrupts it. Physical sustained control, Home and soft Stop were operator-verified on the tested setup; per-installation home calibration remains on the [TODO list](TODO.md). Motor enable and fault recovery are not exposed.

## MIRA

The simulation starts with both tool tips approximately 5 cm above the suture pad and 10 cm apart. **Home** returns to this simulation pose. The mounted endoscope aims at the pad center, framing the needle and both tools. The needle rests on a raised support above the pad for left-arm pickup and lift practice; physical MIRA retains its vendor home pose.

Use **Reset scene** when the needle falls off the pad. The square **Stop** icon stops motion; **Esc** does the same.

**Home** on physical MIRA returns both arms to `[15.7, 80.6, 45, 98.9]°`, resets tool roll to 0°, and closes both grippers. Both physical and simulated Home block manual input until arms and tools reach their targets; **Stop** cancels Home and holds measured positions. Physical Home also requests a hold after a timeout or failed tool command.

With Keyboard selected, hold **Z / X** to close/open the left gripper, or **N / M** for the right. With a gamepad selected, the panel shows that controller's gripper bindings instead. The on-screen buttons work in either mode. Release to stop; **Grip speed** is independent of arm and roll speed. Both simulation and physical MIRA use these controls. Physical grippers require successful tool homing through the vendor controller; arm **Home** does not calibrate tools or bypass this requirement.

The opening meter uses the installed tool's confirmed closed/open endpoints. The vendor API scales gripper commands to 1150 left and 1350 right drive counts; those values need not match an installed jaw's full opening. Set `robot.gripper_calibration` in `workspace/profiles/mira.yaml` (or the manual robot specification) for each tool needing a different feedback range, then restart its node. For example, a left tool confirmed fully open around 650 counts, with 15 counts of endpoint variation, uses:

```yaml
gripper_calibration:
  left:
    closed: 0
    open: 650
    tolerance: 15
```

All values are drive counts. Endpoint tolerance snaps nearby feedback to 0% or 100% and is limited to 5% of the calibrated span. Omitted arms retain the vendor range. This is an opening measurement calibration: jog rates, vendor command scaling, Home and measured-position holds continue using the vendor units. A full-scale physical grip request remains 1150 left / 1350 right counts per second; 50% requests half those rates. Calibration is saved per installation and must be reviewed when its tool changes; it is never inferred automatically from a stalled jaw.

Use the **Virtual Incision MIRA API** supplied by the vendor. Request the current Linux API and POD firmware documentation from [Virtual Incision](https://virtualincision.com/customer-support/); `mira-project.org` is unrelated middleware.

Tool mode uses the vendor forward-kinematics and inverse-kinematics queries, followed by a bounded absolute joint target. It does not accumulate the vendor's persistent Cartesian delta target. Coordinates use the MIRA base frame: XYZ in millimeters, elbow and roll in degrees. Each command is limited to 0.5 mm translation, 1° elbow and 2° roll, with at most 1° change per arm joint. Invalid, unreachable or discontinuous IK results are rejected. Release/Stop requests a measured-position hold; missing tool input expires after 200 ms. Isaac Sim derives its own Jacobian from the loaded asset and measured joints, using the asset's base frame and the same input units. Simulation allows up to 5 mm per command and bounds unfinished target travel to 10 mm and joint lead to 1°; physical MIRA retains its smaller command bounds.

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

After patient admission, the node starts the supplied controller in Docker and connects to its loopback WebSocket API automatically. Vendor startup can enable motor power, so launching this physical node is an intentional robot bring-up action. There is no additional dashboard confirmation. If startup fails, use **Start controller** to retry. The July 2025 API generates its lookup table on first controller startup; allow extra time and about 503 MB of disk space. Generated data and logs persist in the node's controller directory.

Native node execution supports the same profile options, but the managed MIRA controller still requires Docker and the matching image locally: `holoscan-telesurgery:0.1.0` for SDK 5 or `holoscan-telesurgery:0.1.0-sdk4` for SDK 4.

For an existing manual setup, the equivalent `devices.yaml` entry is:

```yaml
robots:
  - id: mira
    name: MIRA
    kind: mira
    uri: ws://127.0.0.1:8081
    motion_enabled: true
    controller:
      executable: /absolute/path/MiraAPI-linux-arm64-2025-07-18
      pod_interface: 192.168.0.1
```

Install the executable and image first when configuring manually. Omit `controller` when managing the API externally. Remove the manual robot entry before selecting a profile with the same robot ID.

Physical jogs use reported joint positions; tool roll uses the vendor's absolute roll command. Release requests the measured position as a hold target. Home, tool operation and network-loss behavior were operator-verified on the tested setup. Review of the supplied July 2025 API and its backend found that motion methods are notifications, position queries return the vendor's cached POD state without a hardware timestamp, and no acknowledged stop or POD-side command watchdog is exposed. A query reply establishes communication, not completion or freshness of physical motion. The adapter reports these limits explicitly and never replays a failed move. Precise arrival and an independent hardware stop/watchdog require vendor support. Keep a physical stop available. Set `motion_enabled: false` for feedback only.

## Versius simulation

Each simulated Versius arm is a separate robot with its own exclusive surgeon lock, feedback and Stop. The scene follows the four-bedside-unit layout in the [CMR user manual](https://cmrsurgical.com/wp-content/uploads/2022/11/U-00009v15-VersiusSurgicalSystem-UserManual-English-UK.pdf): three instrument arms and one endoscope arm share a suture pad and curved needle. The real system has one 3D HD endoscopic camera assembly; this simulation provides six selectable views: the mounted endoscope feed, the central room overview, and a view from behind each of the four arms. Each surgeon can choose and arrange their own feeds, including an arm view alongside the room and endoscope views. All six support optional depth. The left and right needle holders are intended for two-surgeon pickup, handoff and placement practice; the assistant arm carries a grasper. The procedure camera moves with the endoscope arm, whose shaft is a simple simulation proxy because the supplied archive has no endoscope asset. Tool movement uses the live PhysX Jacobian and measured pose in each arm’s base frame, with the same keyboard/gamepad mapping as Franka; the opposing bases have opposing X/Y directions. Gripper controls open and close the needle-holder jaws. Needle pickup uses contact between the needle and jaws, without proximity attachments. Contact parameters are simulation training settings, not measured surgical material properties. This is an asset-based simulation; no physical Versius protocol or private CMR kinematics library is required.

Versius views default to 720p. Physics runs at 120 Hz on CPU; cameras render on GPU. A raised, grooved needle rest provides lower-jaw clearance for pickup. See [saved controller replays](../examples/controller-replays/README.md) for repeatable input recordings.

## Saved device profiles

Profiles live in `workspace/profiles/mira.yaml` and `workspace/profiles/franka.yaml`, under `--workspace` when supplied. Edit the profile's `robot` settings to change its ID, display name, endpoint or motion permission, then restart the node. Pass a new `--mira-api` or replace `workspace/mira-api` to install a replacement API on the next node start.

Combine physical devices with `--profile franka --profile mira`. The selection is remembered per node name, so later starts of that node can omit `--profile`. An explicit selection replaces the saved selection; `--profile none` clears it. Physical profiles cannot be combined with `--sim`.

Connections remain node-local. A new node process connects configured robots by default. Disconnect stays effective for the rest of that node session. Set `auto_connect: false` in a robot specification to require a manual Connect at startup. Configured vendor controllers start once after patient admission; an already running controller is reused. A startup failure is shown for manual retry, without an automatic restart loop. `auto_connect: false` also disables automatic controller startup. Cameras and manually configured robots continue to use `devices.yaml`; duplicate robot IDs are rejected.

## Adding a robot

Device configuration lives in `workspace/nodes/NAME/devices.yaml` on the robot's node, under the directory supplied with `--workspace`.

1. Implement the [adapter contract](../packages/robots/src/telesurgery_robots/adapters/base.py): `read`, `jog`, `hold`, `close`, plus advertised joint groups and motion limits. Constructors must not enable motors. Bound device calls and never replay failed motion.
2. Register the class in the `telesurgery.robots` package entry points. Optional `step` and `home` methods expose those actions; an optional controller factory supports patient-managed startup.
3. Add its `kind` and connection settings to `devices.yaml`. Shared Holoscan graphs handle admission, ownership, commands and feedback.

Report `joints_deg` as measurements and `targets_deg` as targets. Feedback is polled at up to 10 Hz independently of camera streams; stale feedback disables input. `observed_at` is the node's receipt time, not a hardware timestamp.

Temporary feedback errors recover after valid feedback and a successful hold. Recovery never replays motion; release the input and press again. Vendor faults and unhomed tools require attention at the controller.
