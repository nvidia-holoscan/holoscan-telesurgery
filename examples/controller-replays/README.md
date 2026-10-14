# Controller replays

Saved keyboard, gamepad and Haply inputs, grouped by environment and device. Each manifest describes the starting scene and observed result. Inputs were generated using the normal controller mappings; physical-device testing is still required.

| Environment          | Task                                        | Streams         |
| -------------------- | ------------------------------------------- | --------------- |
| MIRA keyboard        | Right-arm needle pickup from above and lift | `mira`          |
| MIRA gamepad / Haply | Left-arm needle pickup and lift             | `mira`          |
| Franka               | Probe approach and torso scan               | `franka`        |
| Versius              | Needle pickup and two-surgeon handoff       | `left`, `right` |

On the surgeon dashboard, acquire control and select an input device. A Replay icon appears beside Home when a verified recording matches that device and simulation arm. Restore the recorded starting scene first. For MIRA, use **Reset scene** to restore both arms and the needle before repeating a replay; Home only moves the robot. For Versius, each surgeon prepares their own arm; playback starts when both are ready. Stop or Esc cancels both streams while each surgeon keeps their own control lease.

The MIRA keyboard recording uses the right arm. During the initial right-arm preparation, it moves the left gripper about 3 cm outward and leaves it parked clear of the lifted needle. The right arm opens the jaws, approaches the needle from above at a steeper angle, closes, and lifts while holding the close key. Version 2 recordings store measured pose checkpoints alongside the keyboard actions. Both the dashboard and command-line runner use current Cartesian and joint feedback to reach each checkpoint before advancing. Position and wrist-angle errors are corrected with bounded jogs through the ordinary surgeon-to-patient control path. Progress extends a move's deadline; five seconds without progress stops it. No replay trajectory runs autonomously on the patient.

Opening uses measured gripper position. Closing can settle at object contact, and an explicit held close key refreshes the bounded closing input during lifting. This does not itself verify a grasp; the saved recording was checked against the simulated needle's actual lift and retention. A command explicitly rejected by the patient as expired before dispatch is followed by fresh feedback and a newly calculated step. Transport failures and unknown command outcomes stop replay.

Version 1 MIRA keyboard recordings keep their original cadence with feedback gates at key transitions. Other version 1 device recordings and the command-line runner retain recorded timing. Stop, Esc in the dashboard, hiding the dashboard, stale feedback, or a motion timeout stops playback. Simulation replay can continue while another window such as Holoviz has focus, provided the dashboard remains visible and responsive. The replay status retains the reason for a stop.

Restore the manifest's starting scene and gripper opening before running a recording. For MIRA, use **Reset scene**. Connect and approve the surgeon services, then release dashboard control. For Versius, use one surgeon service per arm. Replace `NODE_ID` with the ID from `/api/status`:

```bash
.venv-sdk5/bin/python scripts/replay_controller.py \
  examples/controller-replays/versius/keyboard/manifest.json \
  --bind left http://127.0.0.1:8002 NODE_ID:left \
  --bind right http://127.0.0.1:8003 NODE_ID:right
```

The runner accepts simulations only and releases control when finished. Ctrl+C stops it. Select camera views and start screen recording before replay. Contact results can vary with timing and physics settings.
