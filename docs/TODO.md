# TODO

Reviewed 2026-10-12 against the implementation and operator confirmation. Hardware and different-city functional checks below are closed based on operator verification; quantitative results still need to be recorded.

## Completed

- [x] **Franka motion:** sustained control, Ruckig Home and soft Stop verified on hardware.
- [x] **MIRA controls:** Home, 1° jogs, tool roll and grippers verified on hardware, including tool homing.
- [x] **Controller validation:** physical Xbox/PlayStation gamepads, hotplug, wireless/network loss, lease expiry and control handover verified on real robots.
- [x] **Franka Cartesian controls:** bounded tool movement and robot-specific kinematics implemented for physical Franka and Isaac Sim, with keyboard, gamepad and on-screen controls. See [robot controls](robot-controls.md#keyboard-and-gamepad) and [Cartesian tests](../tests/robots/test_franka_cartesian.py).
- [x] **Intel RealSense validation:** RGB/depth resolutions, FPS and codecs verified on both SDKs with Holoviz and WebRTC.
- [x] **Different-city functional testing:** public-internet operation, recovery and simulated control verified.

- [x] **MIRA API review:** reviewed the supplied vendor API and verified its FK/IK contract using the vendor binary in NoPOD mode. Motion notifications acknowledge neither arrival nor Stop, and cached positions have no hardware timestamp; these limits are reflected in feedback and [robot controls](robot-controls.md#mira).
- [x] **Optional MIRA Cartesian controls:** bounded XYZ/elbow controls reuse vendor FK/IK and absolute targets, with keyboard/gamepad input, independent roll/grippers, release/Stop and 200 ms input expiry. Isaac Sim uses measured joint kinematics; both arms and all four tool axes were verified in simulation.
- [x] **Surgical Neural Tokenizer trial:** automatic public Hugging Face model caching, 720p/1080p encode/decode, live encoding changes, GPU RGB viewing in Holoviz and browser preview conversion.
- [x] **Depth preview pairing:** matched color/depth frames remain visible across packet reordering and video jitter; concurrent RealSense streams and the Franka room stream verified.

- [x] **CMR Versius simulation:** four independently controlled arms (three instruments and one endoscope), 1080p procedure/room streams and a shared suture pad. Two surgeon sessions verified pickup, handoff and target placement through live WebRTC; endoscope motion updates the procedure view.

## Remaining

- [ ] **Franka home calibration:** support a calibrated home pose per installation. Physical and simulated Franka currently share a fixed [reset pose](../packages/robots/src/telesurgery_robots/franka/poses.py).
- [ ] **MIRA hardware follow-up:** verify the new Cartesian mode with an operator present; obtain vendor support for hardware timestamps and an acknowledged stop/watchdog before claiming those guarantees.
- [ ] **Haptic devices:** add calibrated pose/button input, clutching and bounded force feedback.
- [ ] **Physical CMR Versius:** integrate the vendor hardware control interface; the Isaac Sim adapter is implemented.
- [ ] **Robot metrics:** measure command-to-measured-feedback latency at P50/P95/P99/P99.9.
- [ ] **Validation measurements:** record RealSense depth overhead and different-city latency percentiles, bandwidth, jitter, loss and clock uncertainty. Functional checks are complete; collect any measurements not captured during those tests.
- [ ] **EA3 benchmarks:** rerun the recorded SDK 5 matrix on public EA3 before publishing an updated SDK comparison. The runtime already uses EA3; the [published measurements](BENCHMARK_COMPARISON.md) predate it.
