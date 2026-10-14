# Controller replays

Saved keyboard, gamepad and Haply inputs, grouped by environment and device. Each manifest describes the starting scene and observed result. Inputs were generated using the normal controller mappings; physical-device testing is still required.

| Environment | Task                                  | Streams         |
| ----------- | ------------------------------------- | --------------- |
| MIRA        | Left-arm needle pickup and lift       | `mira`          |
| Franka      | Probe approach and torso scan         | `franka`        |
| Versius     | Needle pickup and two-surgeon handoff | `left`, `right` |

On the surgeon dashboard, acquire control and select an input device. A Replay icon appears beside Home when a verified recording matches that device and simulation arm. Restore the recorded starting scene first. For Versius, each surgeon prepares their own arm; playback starts when both are ready. Stop or Esc cancels both streams while each surgeon keeps their own control lease.

Start a fresh matching simulation at the recorded Home pose and gripper opening. Connect and approve the surgeon services, then release dashboard control. For Versius, use one surgeon service per arm. Replace `NODE_ID` with the ID from `/api/status`:

```bash
.venv-sdk5/bin/python scripts/replay_controller.py \
  examples/controller-replays/versius/keyboard/manifest.json \
  --bind left http://127.0.0.1:8002 NODE_ID:left \
  --bind right http://127.0.0.1:8003 NODE_ID:right
```

The runner accepts simulations only and releases control when finished. Ctrl+C stops it. Select camera views and start screen recording before replay. Contact results can vary with timing and physics settings.
