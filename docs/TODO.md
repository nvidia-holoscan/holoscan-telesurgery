# TODO

- [ ] **Gamepad control:** device selection, axis/button mappings, dead zones and a hold-to-enable button. Route input through the existing permission, robot lock and Holoscan command path; release control on device disconnect.
- [ ] **Haptic devices:** a surgeon-side device bridge for pose/button input and force feedback, with calibration, clutching and bounded feedback. Robot controllers remain on patient nodes.
- [ ] **Physical robots:** MIRA/Franka adapters with measured state, motion limits and acknowledged hold/stop behavior. The current adapters support simulation only.
- [ ] **Robot feedback:** report measured simulator joint positions alongside commanded targets, then measure command-to-feedback latency at P50/P95/P99/P99.9.
- [ ] **Hardware validation:** verify control handover, input loss, network loss, lease expiry and the controller's stop behavior with actual gamepads, haptic devices and robots.
- [ ] **Intel RealSense cameras:** test discovery, RGB streaming, supported resolutions/FPS and codecs on SDK 5 and SDK 4, with Holoviz and WebRTC viewing. Measure latency and assess depth-stream support separately.
- [ ] **Different-city testing:** run patient and surgeon services in different cities over the public internet. Measure P50/P95/P99/P99.9 latency, FPS, bandwidth, jitter, packet loss and clock uncertainty; verify Holoviz/WebRTC viewing, simulated robot control and recovery after disconnection.
