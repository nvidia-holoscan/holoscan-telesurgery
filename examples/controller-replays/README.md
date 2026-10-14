# Controller replays

Saved simulation tasks for keypad/keyboard, gamepad and Haply, grouped by environment and device. All nine bundled recordings use version 2 feedback-paced checkpoints. Each manifest describes the starting scene, reference recording and verification result. These are normalized task checkpoints using each selected device’s normal motion bounds, not physical-device captures. The `*-100hz.jsonl.gz` files are archival Haply samples from the earlier tasks; the current manifests do not use them.

| Environment          | Task                                        | Streams         |
| -------------------- | ------------------------------------------- | --------------- |
| MIRA                 | Right-arm needle pickup from above and lift | `mira`          |
| Franka               | Probe approach and torso scan               | `franka`        |
| Versius              | Needle pickup and two-surgeon handoff       | `left`, `right` |

After updating the checkout, restart both patient and surgeon services so their replay catalogs and handoff protocol match. On the surgeon dashboard, acquire control and select an input device. A Replay icon appears beside Home when a verified recording matches that device and simulation arm. Restore the recorded starting scene first. For MIRA, use **Reset scene** to restore both arms and the needle before repeating a replay; Home only moves the robot. For Versius, each surgeon prepares their own arm; playback starts when both are ready. During the task, measured checkpoints synchronize the left pickup, right grasp, left release/withdrawal, and right lift. A fast participant waits for its peer instead of advancing on the recording’s clock. Stop or Esc cancels both streams while each surgeon keeps their own control lease.

All MIRA recordings use the established keyboard task with the right arm. During the initial right-arm preparation, it moves the left gripper about 3 cm outward and leaves it parked clear of the lifted needle. The right arm opens the jaws, approaches the needle from above at a steeper angle, closes, and lifts. Keyboard and gamepad recordings explicitly refresh their close input during the lift; Haply retains the closing load from its grasp checkpoint because its grip buttons clutch tool motion. Both the dashboard and command-line runner request fresh measured feedback after each command and reach each checkpoint before advancing. Position and wrist-angle errors are corrected with bounded jogs through the ordinary surgeon-to-patient control path. Progress extends a move's deadline; five seconds without progress stops it. No replay trajectory runs autonomously on the patient.

Franka follows measured probe position and orientation through the approach and scan. Versius first prepares its recorded joint configuration above the task to avoid a wrist limit in the redundant arm’s straight-home configuration. It then approaches, grasps, and hands off using measured tool poses. The pickup endpoint includes a submillimetre correction to seat the needle securely between the jaws. Tool checkpoints stop and verify the settled pose before advancing.

Opening uses measured gripper position. Closing can settle at object contact, and an explicit held close key or gamepad button refreshes the bounded closing input during lifting. This does not itself verify a grasp; the saved recording was checked against the simulated needle's actual lift and retention. A command explicitly rejected by the patient as expired before dispatch is followed by fresh feedback and a newly calculated step. Transport failures and unknown command outcomes stop replay.

Version 1 MIRA keyboard recordings keep their original cadence with feedback gates at key transitions. Other legacy version 1 recordings retain recorded timing. The bundled version 2 tasks advance by measured arrival; their displayed duration is nominal and increases with network delay. Stop, Esc in the dashboard, hiding the dashboard, stale feedback, or a motion timeout stops playback. Simulation replay can continue while another window such as Holoviz has focus, provided the dashboard remains visible and responsive. The replay status retains the reason for a stop.

Restore the manifest's starting scene and gripper opening before running a recording. For MIRA, use **Reset scene**. Connect and approve the surgeon services, then release dashboard control. For Versius, use one surgeon service per arm. Replace `NODE_ID` with the ID from `/api/status`:

```bash
.venv-sdk5/bin/python scripts/replay_controller.py \
  examples/controller-replays/versius/keyboard/manifest.json \
  --bind left http://127.0.0.1:8002 NODE_ID:left \
  --bind right http://127.0.0.1:8003 NODE_ID:right
```

The runner accepts simulations only and releases control when finished. Ctrl+C stops it. Select camera views and start screen recording before replay. Contact results can vary with timing and physics settings.

Verification on 2026-10-14 used headless Isaac physics through real surgeon, TLS patient, and node services on UNI. Every environment completed with keypad/keyboard at 80 ms added round-trip delay, gamepad at 160 ms, and Haply without added delay. Cameras were disabled for these physics checks. Needle retention was measured for three seconds after replay.

| Environment | Measured outcome |
| --- | --- |
| MIRA | Right-arm pickup and 5.7–6.3 cm needle lift |
| Franka | All 18 approach/scan checkpoints reached; about 14.3 cm between scan endpoints |
| Versius | Left pickup, right grasp, left release/withdrawal, and right lift; final needle height about 5 cm above its starting point |

Franka Haply also completed with the surgeon on Spark and the patient/simulator on UNI, with 80 ms added round-trip delay. Individual manifests contain the measured results and elapsed times. Regression coverage includes all device/environment selections in the browser, delayed command admission, dashboard silence/cancellation, fresh feedback after acknowledgements, and two-surgeon handoff barriers. The full suite passed 1,096 tests with two inapplicable Franka control cases skipped; the final targeted replay checks passed 68 tests.
