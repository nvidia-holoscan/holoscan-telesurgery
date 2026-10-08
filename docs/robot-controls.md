# Robot controls

The patient connects robots and grants surgeon access. A surgeon's first input takes the exclusive robot lock. **Stop / Esc** requests a hold and releases that lock. **Disconnect**, on the patient side, releases the controller connection without powering off the robot.

The surgeon lists connected robots automatically. Use the panel's pop-out icon to place controls beside Holoviz; keep that window focused for keyboard or gamepad input. Dock or close it to return controls to the dashboard. **Pop out all**, beside Fullscreen, opens every live stream in Holoviz and detaches the selected robot controls. **Dock all** returns H.264 views and controls to the dashboard and closes other native viewers.

## Keyboard and gamepad

Tap a key or click its on-screen button for one step. Hold it to move continuously after 450 ms; the target advances without waiting for the previous step to finish. Releasing held input requests a smooth stop. Adjust **Step** for distance per input and **Speed** for Franka's maximum joint speed.

| Robot                          | Default step | Maximum step | Default speed              |
| ------------------------------ | ------------ | ------------ | -------------------------- |
| Franka, physical or simulation | 1°           | 5°           | 10°/s; adjustable to 20°/s |
| Physical MIRA                  | 1°           | 1°           | Vendor controller          |
| Simulated MIRA                 | 1°           | 5°           | Simulation controller      |

Keys increase/decrease the corresponding joint:

| Robot / arm | J1    | J2    | J3    | J4    | J5    | J6    | J7    |
| ----------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Franka      | Q / A | W / S | E / D | R / F | T / G | Y / H | U / J |
| MIRA left   | Q / A | W / S | E / D | R / F | —     | —     | —     |
| MIRA right  | U / J | I / K | O / L | P / ; | —     | —     | —     |

Both MIRA arms accept input simultaneously. These are joint controls, not Cartesian tool movement. Typing in a field, opening a dialog, losing focus or losing access stops input. Release and press again to resume.

MIRA tool roll uses **T / G** on the left and **Y / H** on the right. Tap to step or hold to rotate; the application limits roll to ±180°.

For a gamepad, press a button and select its name in the input dropdown. Compatible Xbox and PlayStation controllers use the browser's standard mapping:

- Center the sticks, then hold **LB/L1** to enable input. Release it to stop and release the lock.
- **MIRA:** each stick controls its arm's J1–J2; **RB/R1** selects J3–J4. Hold **L3 / R3** and move that stick up/down to roll the tool. Release LB/L1 and center the sticks before changing controls.
- **Franka:** select a joint group; the sticks control its first four joints.

Input sends the latest command at up to 20 Hz without queuing moves. Franka's local loop expires held input after 200 ms without a fresh command. A lost controller or permission cannot resume motion automatically.

## Franka

Docker includes the Franka adapter. For native execution, run `./scripts/build_franka.sh` after setup, then start the node from a new login session. It installs libfranka 0.15.2 (protocol 9) and realtime scheduling permissions. Use a [firmware-compatible libfranka](https://frankarobotics.github.io/docs/compatibility.html), a realtime kernel and FCI enabled in Desk.

Add to the node's `devices.yaml`:

```yaml
robots:
  - id: franka
    name: Franka
    kind: franka
    address: 172.16.0.3
    connection_enabled: false
    motion_enabled: true
```

Click **Connect** on the patient dashboard. The native controller runs synchronized Ruckig position trajectories at 1 kHz; simulation uses the same motion limits. Feedback shows measured joints separately from targets. Choose **Disconnect** before using Desk tasks.

**Home** uses the configured reset pose for physical and simulated Franka: `[-24.475, -18.378, 13.651, -106.151, 9.422, 90.758, -21.335]°`. It leaves the gripper unchanged. Verify the path with an operator present; **Stop / Esc** interrupts it. Physical Home and sustained motion still need supervised validation. Motor enable, fault recovery and gripper control are not exposed.

## MIRA

**Home** returns both arms to the vendor nominal pose `[15.7, 80.6, 45, 98.9]°`, also used at simulation startup. Tool roll and grasp stay unchanged. Physical Home blocks manual input until the reported joints reach the target; **Stop** requests a hold.

Hold **Z / X** to close/open the left gripper, or **N / M** for the right. The matching buttons work with keyboard or gamepad selected. Release to stop; **Grip speed** controls speed independently of arm Step. Both simulation and physical MIRA use these controls. Physical grippers require successful tool homing through the vendor controller; arm **Home** does not calibrate tools or bypass this requirement.

Use the **Virtual Incision MIRA API** supplied by the vendor. Request the current Linux API and POD firmware documentation from [Virtual Incision](https://virtualincision.com/customer-support/); `mira-project.org` is unrelated middleware.

The patient can start the supplied controller in Docker, then connect to its loopback WebSocket API. Vendor startup can enable motor power, so the dashboard requires operator confirmation. Add to `devices.yaml`:

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
      image: holoscan-telesurgery:sdk5
```

Install the executable and image first. Omit `controller` when managing the API externally. The supplied ARM64 build uses POD address `192.168.0.10:10000` (UDP), with node interface `192.168.0.1/24`; confirm these against your vendor package.

Physical jogs use reported joint positions; tool roll uses the vendor's absolute roll command. Release requests the measured position as a hold target. The vendor API does not provide a verified stop acknowledgement or hardware feedback timestamp; Home, tool operation and network-loss behavior still need supervised hardware validation. Keep a physical stop available. Set `motion_enabled: false` for feedback only.

## Adding a robot

Device configuration lives in `workspace/nodes/NAME/devices.yaml` on the robot's node, under the directory supplied with `--workspace`.

1. Implement the [adapter contract](../packages/robots/src/telesurgery_robots/adapters/base.py): `read`, `jog`, `hold`, `close`, plus advertised joint groups and motion limits. Constructors must not enable motors. Bound device calls and never replay failed motion.
2. Register the class in the `telesurgery.robots` package entry points. Optional `step` and `home` methods expose those actions; an optional controller factory supports patient-managed startup.
3. Add its `kind` and connection settings to `devices.yaml`. Shared Holoscan graphs handle admission, ownership, commands and feedback.

Report `joints_deg` as measurements and `targets_deg` as targets. Feedback is polled at up to 10 Hz independently of camera streams; stale feedback disables input. `observed_at` is the node's receipt time, not a hardware timestamp.

Temporary feedback errors recover after valid feedback and a successful hold. Recovery never replays motion; release the input and press again. Vendor faults and unhomed tools require attention at the controller.
