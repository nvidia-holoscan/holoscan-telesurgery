# TODO

Reviewed 2026-10-12 against the implementation and operator confirmation. Hardware and different-city functional checks below are closed based on operator verification; quantitative results still need to be recorded.

## Completed

- [x] **Franka motion:** sustained control, Ruckig Home and soft Stop verified on hardware.
- [x] **MIRA controls:** Home, 1° jogs, tool roll and grippers verified on hardware, including tool homing.
- [x] **Controller validation:** physical Xbox/PlayStation gamepads, hotplug, wireless/network loss, lease expiry and control handover verified on real robots.
- [x] **Continuous keyboard controls:** shared key-repeat handling prevents control-panel flicker and interrupted holds across robots; operator verified the fix in Edge. Versius exposes all eight joints together and shows measured gripper opening.
- [x] **Native robot controller:** Python desktop window with matching keyboard/gamepad controls, speed settings, feedback, Home and Stop. The pop-out icon switches to Dock; Pop out all and Dock all include the controller alongside Holoviz. Home restores each robot's configured starting pose and supported tools. Native mouse/keyboard Home verified in MIRA, Franka and Versius simulations; SDL virtual-gamepad control, interruption and disconnect checks passed.
- [x] **Franka Cartesian controls:** bounded tool movement and robot-specific kinematics implemented for physical Franka and Isaac Sim, with keyboard, gamepad and on-screen controls. See [robot controls](robot-controls.md#keyboard-and-gamepad) and [Cartesian tests](../tests/robots/test_franka_cartesian.py).
- [x] **Intel RealSense validation:** RGB/depth resolutions, FPS and codecs verified on both SDKs with Holoviz and WebRTC.
- [x] **Different-city functional testing:** public-internet operation, recovery and simulated control verified.

- [x] **MIRA API review:** reviewed the supplied vendor API and verified its FK/IK contract using the vendor binary in NoPOD mode. Motion notifications acknowledge neither arrival nor Stop, and cached positions have no hardware timestamp; these limits are reflected in feedback and [robot controls](robot-controls.md#mira).
- [x] **Optional MIRA Cartesian controls:** bounded XYZ/elbow controls reuse vendor FK/IK and absolute targets, with keyboard/gamepad input, independent roll/grippers, release/Stop and 200 ms input expiry. Isaac Sim uses measured joint kinematics; both arms and all four tool axes were verified in simulation.
- [x] **Surgical Neural Tokenizer trial:** automatic public Hugging Face model caching, 720p/1080p encode/decode, live encoding changes, GPU RGB viewing in Holoviz and browser preview conversion.
- [x] **Depth preview pairing:** matched color/depth frames remain visible across packet reordering and video jitter; concurrent RealSense streams and the Franka room stream verified.

- [x] **CMR Versius simulation:** four independently controlled arms (three instruments and one endoscope), 1080p procedure/room streams and a shared suture pad. Two surgeon sessions verified pickup, handoff and target placement through live WebRTC; endoscope motion updates the procedure view.

- [x] **EA3 benchmarks:** reran all 48 SDK 5 configurations (74 camera results) on public `5.0.0a3`, with 30-second warmup and 60-second measurements. Updated raw records, tables, charts and the [SDK comparison](BENCHMARK_COMPARISON.md); SDK 4 remains the historical baseline.

## Remaining

- [ ] **Franka home calibration:** support a calibrated home pose per installation. Physical and simulated Franka currently share a fixed [reset pose](../packages/robots/src/telesurgery_robots/franka/poses.py).
- [ ] **MIRA hardware follow-up:** verify the new Cartesian mode with an operator present; obtain vendor support for hardware timestamps and an acknowledged stop/watchdog before claiming those guarantees.
- [ ] **Haptic devices:** add calibrated pose/button input, clutching and bounded force feedback.
- [ ] **Physical CMR Versius:** integrate the vendor hardware control interface; the Isaac Sim adapter is implemented.
- [ ] **Robot metrics:** measure command-to-measured-feedback latency at P50/P95/P99/P99.9.
- [ ] **Validation measurements:** record RealSense depth overhead and different-city latency percentiles, bandwidth, jitter, loss and clock uncertainty. Functional checks are complete; collect any measurements not captured during those tests.
