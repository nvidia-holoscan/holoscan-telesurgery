# Controller replays

Saved simulation tasks for keypad/keyboard, gamepad and Haply, grouped by environment and device. All nine bundled recordings use version 2 feedback-paced checkpoints. Each manifest describes the starting scene, reference recording and verification result. These are normalized task checkpoints using each selected device’s normal motion bounds, not physical-device captures. The `*-100hz.jsonl.gz` files are archival Haply samples from the earlier tasks; the current manifests do not use them.

| Environment          | Task                                        | Streams         |
| -------------------- | ------------------------------------------- | --------------- |
| MIRA                 | Right-arm needle pickup from above and lift | `mira`          |
| Franka               | Probe approach and torso scan               | `franka`        |
| Versius              | Needle pickup and two-surgeon handoff       | `left`, `right` |

After updating the checkout, restart patient, surgeon and node services. On the surgeon dashboard or native controller, acquire control and select an input device. A Replay icon appears beside Home and Reset scene when a verified recording matches that device and simulation arm. Restore the recorded starting scene first. Use **Reset scene** to restore the robot and task objects before repeating a replay; Home only moves the robot. For Versius, reset before the second surgeon acquires an arm; every other arm must be released and stopped for the shared scene to reset.

Versius replays are independent actions. The left replay picks up the needle, lifts it about 3 cm, and completes while holding it. Keep the left arm's control lease; its replay does not need to remain running. Start the right replay whenever ready. It approaches and closes at the pickup position, then lifts about 2 cm. If the left replay has presented the needle and the right jaws settle around it, the right replay automatically opens the left gripper fully, settles its own grasp, and then lifts. The left arm stays in place. The right chooses its action when Replay starts. If no completed left pickup is available then, it performs an empty pickup 3 cm to the side of the handoff position, clear of the left tool at Home, and completes without waiting. This shadow action stays independent if the left finishes later. Each side can independently select keyboard, gamepad or Haply. Manual gripper control never triggers automatic release. Moving the left arm manually, releasing its control, resetting the scene, or starting another left replay cancels its previous automatic-release permission. Stop or Esc cancels the selected replay without cancelling the other action; cancelling during automatic release also stops the opening gripper.

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

For Versius, the runner performs left then right when both are bound, and keeps both control leases until the actions finish. A single left or right binding runs that action alone. The runner accepts simulations only and releases control when finished. Ctrl+C stops it. Select camera views and start screen recording before replay. Contact results can vary with timing and physics settings.

Verification on 2026-10-14 used Isaac physics through real surgeon, TLS patient, and node services on UNI. MIRA and Franka completed with all three inputs locally, keyboard and Haply at 80 ms added round-trip delay, and gamepad at 160 ms. These timings exclude connection setup and the final retention check.

| Environment | Local replay | With 80 ms added RTT | With 160 ms added RTT | Measured outcome |
| --- | --- | --- | --- | --- |
| MIRA | 12–13 s | 29–30 s | 60 s | Needle pickup and roughly 2–2.6 cm lift |
| Franka | 32–36 s | 44–50 s | 61 s | All 18 approach/scan checkpoints; about 14.3 cm between scan endpoints |

Versius checks ran independent actions with different devices on each side. The left replay completed and held the needle for ten seconds before the right replay started. Each transfer retained the needle for ten seconds after the right replay completed; the final height was about 4.5–4.7 cm above the needle rest.

| CMR action | Added round-trip delay | Left elapsed | Right elapsed |
| --- | --- | --- | --- |
| Native Gamepad → native Keyboard transfer | 0 ms | 35.0 s | 41.5 s |
| Native Keyboard → native Haply transfer | 80 ms | 40.3 s | 48.1 s |
| Native Haply → browser Gamepad transfer | 160 ms | 54.2 s | 86.6 s |
| Browser Keyboard, right-only shadow pickup | 0 ms | — | 36.7 s |

MIRA checks ran with both cameras enabled; Versius checks used all six cameras and the supplied GLB materials. Franka checks used headless physics. The right-only shadow pickup left the needle on its rest and the left arm at Home. A simultaneous native Gamepad/Haply start also completed both actions: the left retained the needle while the right performed the empty pickup. Individual manifests contain the measured verification results.

Regression coverage includes all device/environment selections in the browser and native controller, delayed command admission, controller silence/cancellation, fresh feedback after acknowledgements, a second surgeon joining after the first reaches the handoff, independent completion, replay-only automatic release, empty pickup, bounded joint preparation, and correction rates that account for feedback delay. Restart the simulation nodes as well as the patient and surgeon services after updating, so simulation speed limits and replay catalogs match.
