# TODO

- [ ] **Franka motion:** validate sustained control, Ruckig Home and soft Stop on hardware; support a calibrated home pose per installation.
- [ ] **MIRA API:** validate Home, 1° jogs, tool roll and grippers on hardware, including tool homing. Review the current vendor SDK; verify precise return, feedback freshness and an acknowledged stop/watchdog.
- [ ] **Controller validation:** test physical Xbox/PlayStation gamepads, hotplug, wireless/network loss, lease expiry and control handover on real robots.
- [ ] **Haptic devices:** add calibrated pose/button input, clutching and bounded force feedback.
- [ ] **Cartesian controls:** add robot-specific kinematics and bounded tool movement using Isaac Lab-style keyboard mappings.
- [ ] **Optional shared MIRA control:** assess one surgeon per arm, with coordinated commands and a whole-robot Stop. Keep one surgeon per robot as the default.
- [ ] **CMR Versius:** add physical and Isaac Sim adapters.
- [ ] **Robot metrics:** measure command-to-measured-feedback latency at P50/P95/P99/P99.9.
- [ ] **Intel RealSense:** validate RGB/depth resolutions, FPS and codecs on both SDKs with Holoviz and WebRTC; measure depth overhead.
- [ ] **Different-city testing:** measure latency percentiles, bandwidth, jitter, loss and clock uncertainty over the public internet; verify recovery and simulated control.
- [ ] **EA3 benchmarks:** rerun the recorded SDK 5 matrix on public EA3 before publishing an updated SDK comparison.
- [ ] **Surgical Neural Tokenizer for Telesurgery:** integrate into the Holoscan pipeline.
