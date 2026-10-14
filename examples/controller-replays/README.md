# Controller replays

Saved simulation tasks for keypad/keyboard, gamepad and Haply, grouped by environment and device. All nine bundled recordings use version 2 feedback-paced checkpoints. Each manifest describes the starting scene, reference recording and verification result. These are normalized task checkpoints using each selected device’s normal motion bounds, not physical-device captures. The `*-100hz.jsonl.gz` files are archival Haply samples from the earlier tasks; the current manifests do not use them.

| Environment          | Task                                        | Streams         |
| -------------------- | ------------------------------------------- | --------------- |
| MIRA                 | Right-arm needle pickup from above and lift | `mira`          |
| Franka               | Probe approach and torso scan               | `franka`        |
| Versius              | Needle pickup and two-surgeon handoff       | `left`, `right` |

After updating the checkout, restart both patient and surgeon services so their replay catalogs and handoff protocol match. On the surgeon dashboard or native controller, acquire control and select an input device. A Replay icon appears beside Home and Reset scene when a verified recording matches that device and simulation arm. Restore the recorded starting scene first. Use **Reset scene** to restore the robot and task objects before repeating a replay; Home only moves the robot. For Versius, reset before the second surgeon acquires an arm; every other arm must be released and stopped for the shared scene to reset. Start the left arm’s replay first. It picks up the needle and holds it at the handoff position while waiting. When ready, the second surgeon acquires the right arm, selects the same recording device, and starts Replay to take the needle. Both replays may also be started together; the right arm waits for the left pickup before approaching. Keep the first controller visible and replay running while the second surgeon prepares. During the task, measured checkpoints synchronize the left pickup, right grasp, left release/withdrawal, and right lift. A fast participant waits for its peer instead of advancing on the recording’s clock. Stop or Esc cancels both streams while each surgeon keeps their own control lease.

All MIRA recordings use the established keyboard task with the right arm. During the initial right-arm preparation, it moves the left gripper about 3 cm outward and leaves it parked clear of the lifted needle. The right arm opens the jaws, approaches the needle from above at a steeper angle, closes, and lifts about 2.5 cm. All three inputs retain the simulated gripper's bounded closing load after the grasp checkpoint. Preparation and roll use faster simulation settings, while the final approach and loaded lift use smaller corrections. All replay interfaces request fresh measured feedback after each command and reach each checkpoint before advancing. Position and wrist-angle errors are corrected with bounded jogs through the ordinary surgeon-to-patient control path. Progress extends a move's deadline; five seconds without progress stops it. No replay trajectory runs autonomously on the patient.

Franka follows measured probe position and orientation through the approach and scan, using 80% arm speed for the initial approach and 25% for the scan. Versius first prepares its recorded joint configuration above the task to avoid a wrist limit in the redundant arm’s straight-home configuration. Each preparation step uses the node's advertised bound (up to 5 degrees) and waits for completion at the configured joint speed. It then approaches, grasps, and hands off using measured tool poses. The pickup endpoint includes a submillimetre correction to seat the needle securely between the jaws. Tool checkpoints stop and verify the settled pose before advancing.

Opening uses measured gripper position. Closing can settle at object contact once the jaws stop closing; slight spreading under contact load does not restart that settling interval. This does not itself verify a grasp; the saved recording was checked against the simulated needle's actual lift and retention. A command explicitly rejected by the patient as expired before dispatch is followed by fresh feedback and a newly calculated step. Transport failures and unknown command outcomes stop replay.

Version 1 MIRA keyboard recordings keep their original cadence with feedback gates at key transitions. Other legacy version 1 recordings retain recorded timing. The bundled version 2 tasks advance by measured arrival; their displayed duration is nominal and increases with network delay. Stop, Esc, hiding the dashboard or native controller, stale feedback, or a motion timeout stops playback. Simulation replay can continue while another window such as Holoviz has focus, provided the controller remains visible and responsive. The replay status retains the reason for a stop.

Restore the manifest's starting scene and gripper opening before running a recording. For MIRA, use **Reset scene**. Connect and approve the surgeon services, then release dashboard control. For Versius, use one surgeon service per arm. Replace `NODE_ID` with the ID from `/api/status`:

```bash
.venv-sdk5/bin/python scripts/replay_controller.py \
  examples/controller-replays/versius/keyboard/manifest.json \
  --bind left http://127.0.0.1:8002 NODE_ID:left \
  --bind right http://127.0.0.1:8003 NODE_ID:right
```

The runner accepts simulations only and releases control when finished. Ctrl+C stops it. Select camera views and start screen recording before replay. Contact results can vary with timing and physics settings.

Verification on 2026-10-14 used Isaac physics through real surgeon, TLS patient, and node services on UNI. Every environment completed with all three inputs locally, keyboard and Haply at 80 ms added round-trip delay, and gamepad at 160 ms. These timings exclude connection setup and the final retention check; the displayed duration is based on a local run.

| Environment | Local replay | With 80 ms added RTT | With 160 ms added RTT | Measured outcome |
| --- | --- | --- | --- | --- |
| MIRA | 12–13 s | 29–30 s | 60 s | Needle pickup and roughly 2–2.6 cm lift |
| Franka | 32–36 s | 44–50 s | 61 s | All 18 approach/scan checkpoints; about 14.3 cm between scan endpoints |
| Versius | 80–81 s | 92–95 s | 127 s | Left pickup, right grasp, left release/withdrawal, and right lift; final needle about 5 cm above its starting point |

MIRA checks ran with both cameras enabled; Versius checks used all six cameras and the supplied GLB materials. Franka checks used headless physics. Needle retention was observed for ten seconds after MIRA playback and three seconds after the Versius handoff. Individual manifests contain the measured results and exact elapsed times.

Regression coverage includes all device/environment selections in the browser and native controller, delayed command admission, controller silence/cancellation, fresh feedback after acknowledgements, a second surgeon joining after the first reaches the handoff, two-surgeon handoff barriers, bounded joint preparation, and correction rates that account for feedback delay. Restart the simulation nodes as well as the patient and surgeon services after updating, so simulation speed limits and replay catalogs match.
