# Architecture

## Workspace

| Package | Responsibility |
| --- | --- |
| `packages/core` | Wire protocol, access rules, camera and controller adapters, GPU codec |
| `packages/runtime` | Holoscan graphs and the SDK 4/5 implementations |
| `packages/app` | Local HTTP dashboard, patient coordinator, SSH nodes |
| `packages/sim` | Isaac Sim launcher, assets and room presets |

Each is a uv workspace member. The application imports a single runtime interface; only `runtime/sdk4` and `runtime/sdk5` depend on different Holoscan APIs. Native HSB support is built from `native/` for SDK 5; SDK 4 uses Hololink's module adapters.

Remote devices use the same `NodeService` in two deployment modes. SSH deployment installs an outbound node connected to the patient endpoint. A standalone `./run.sh node` listens on TCP 7448; the patient connects using a pairing code containing the node certificate fingerprint and a random credential. The fingerprint is verified before sending the credential. Only one patient connection can own a standalone node at a time. Both sides persist credentials with owner-only permissions, and the patient reconnects automatically. Disconnects stop cameras and release controller leases; reconnecting does not restart streams. The patient UI exposes connection logs for standalone nodes and deployment logs for SSH nodes.

SSH deployment can start physical discovery or a MIRA/Franka room. The node's **Environment** action changes that choice after streams stop and robot control is released; the choice persists across restarts. Standalone nodes take `--sim mira|franka` at startup and reject remote environment changes. Restarting without `--sim` returns to physical discovery. Both modes report simulator progress and logs to the patient dashboard.

## Dashboard

The browser uses small ES modules: `app.js` coordinates state and media; `patient.js` owns node navigation; `workspace.js` arranges mounted video tiles; `robots.js` owns held input and lease renewal. Patient previews are opt-in. Moving or resizing surgeon tiles preserves their WebRTC connections.

`monitor.js` runs diagnostics only while visible, at a configurable interval. `latency.js` samples counters; `metrics.js` renders bounded trends and percentiles. A per-device panel uses existing browser peers without subscribing to video again. `trace.py` correlates software stages; `frame-timing.js` matches browser display callbacks to RTP timestamps. `path-view.js` draws the breakdown and history. Percentile aggregation runs outside the service event loop. Losing window focus releases held robot input and ownership.

## Media

A node supervises one camera process per stream. Its Holoscan graph captures, packs or encodes, and publishes frames through a local bounded IPC channel. The node serves frames directly to authorized surgeon services and native viewers. The patient coordinator handles admission and controls; it receives video only when its operator opens a preview. A surgeon graph delivers each H.264 camera's latest encoded frame to its local WebRTC service. WebRTC packetizes H.264 without decoding or re-encoding it; the browser decodes and displays it.

Native viewing launches a separate Holoscan process connected directly to the camera node’s TLS video endpoint. The dashboard only supervises the window. Encoded packets enter a bounded latest-frame graph, NVDEC (H.264/H.265) or nvJPEG produces RGB device pixels, and Holoviz renders them. Device copies preserve buffer ownership; decoded pixels are never downloaded to the CPU. The native process has its own scoped video connection.

A native viewer receives a single-use, camera-scoped ticket valid for 30 seconds. The patient issues the ticket through its authenticated node control connection; the node accepts it once and rejects control requests on the video connection. Hiding a camera, disconnecting or revoking access closes the associated viewer connections. Patient-local viewers use the same endpoint. Temporary launch credentials are private and removed when the process closes.

USB discovery enumerates capture interfaces and valid format/resolution/FPS combinations through V4L2, preferring uncompressed capture. IMX274 exposes the two RAW10 modes implemented by both adapters (1080p60 and 4K60). Each node probes its available encoders once; per-camera settings persist on that node. Streaming defaults to H.264. Uncompressed BGR8 frames are bounded to 4096×2160×3 bytes and must match the advertised dimensions exactly. H.264/H.265 use independently decodable NVENC frames with QP and preset controls. JPEG uses nvJPEG quality control. Only H.264 goes to WebRTC; other formats require Holoviz, with no transcoding. The native viewer follows each frame’s format. [NVIDIA codec controls](https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-prog-guide/using_pynvvideocodec_apis.html)

HSB acquisition, Bayer conversion and encoding use GPU buffers. USB starts with CPU pixels uploaded for encoding. Isaac Sim renders on the GPU, but its current gateway reads RGB into CPU memory and sends it over local IPC before GPU encoding. This path is not zero-copy. Codec calls run on a Python-owned worker thread to avoid native-callback GIL problems. nvJPEG permits NVIDIA’s hardware and CUDA hybrid backends, excluding CPU-only codec fallbacks. [nvJPEG backend definitions](https://docs.nvidia.com/cuda/nvimagecodec/codec_options.html)

Uncompressed streaming skips the codecs: CPU BGR8 buffers are packed directly, while GPU sources require a download for the current transport. Holoviz uploads the received pixels and converts BGR to RGB. Metrics report these costs as **Pack** and **Upload**, instead of encoding/decoding. Same-host streams still use the bounded IPC/TLS path, not shared memory. A webcam configured for MJPEG still decodes during capture; select an uncompressed capture mode for that baseline.

Camera and network frame queues discard old frames. Reliable control messages have separate bounded queues. SDK 4 uses an EventBasedScheduler and mailbox tokens; SDK 5 uses Graph partitions and latest-message queues. Frame buffers remain owned until their CUDA work completes. Logs and benchmark counters expose process failures and dropped frames.

## Clock synchronization and latency

Host clock setup is part of `setup.sh`, automatically invoked for the first Docker launch and SSH-node deployment. An active chrony/PTP configuration is preserved. Otherwise setup installs and enables the OS `chrony.service` using public UTC servers, replacing systemd-timesyncd with gradual corrections only; it never invokes `makestep`. Systemd starts the daemon after reboot, independently of the application; the project helper is only an installer. No privileged operation runs inside the dashboard or container. SSH enrollment without installation privileges can still stream; clock setup is deferred to an interactive setup on that host.

Containers read the host clock and query chrony's local monitoring port. Allow UDP 123 between clients and their time server; monitoring UDP 323 stays on localhost. A room server needs a valid upstream UTC source; an isolated `local` clock is not treated as verified UTC. The internal setup helper also supports provisioning a room server; this is optional site infrastructure, not an extra application startup step.

Use a shared room server on the patient LAN. Across the public internet, each site should use its own trusted UTC sources or reachable time server. Hardware-timestamped PTP needs compatible NICs and a suitable network; it is not required or assumed across the internet. If a site already has PTP, integrate its reference with chrony instead of running two independent system-clock controllers. The setup script refuses to replace an active PTP service.

The app reads `chronyc tracking` every 5 seconds outside the video loop. Its estimated UTC error is `abs(system offset) + root dispersion + root delay / 2`, with allowance for intervening clock adjustments and reported skew. Fresh UTC reports can resolve a hop when their combined uncertainty is at most 1 ms. Otherwise, connected services exchange four monotonic timestamps to estimate their relative clock offset. The recent probe with the smallest RTT/2 plus drift allowance is used (1000 ppm relative drift, 15-second expiry). The displayed uncertainty includes possible path asymmetry; internet estimates can be coarse. Negative delays and expired mappings remain unavailable. This does not adjust either system clock. Same-host services compare monotonic timestamps in the same boot/time namespace and need no NTP. Patient request RTT is a separate measurement, never divided by two to manufacture one-way latency.

| Stage | Measurement boundary |
| --- | --- |
| Frame preparation | Starts when a buffer is delivered to application code: USB `read()` return, processed HSB Bayer tensor receive, or simulator `get_data()` return. Includes subsequent application copies, conversion and local handoff. Device acquisition, simulator update/rendering and producer work before this boundary are excluded |
| Processing queue / Encode | Source-ready to codec worker; then input upload/conversion, selected GPU encoding and completion. No extra GPU synchronization |
| Pack / Upload (uncompressed) | Packing and any GPU-to-host copy before transport; then host-to-GPU upload and RGB conversion at the native viewer. Replaces Encode / Decode |
| Source relay | Encoded output through local IPC to the source node service |
| Source queue / Send queue | Source dispatch and per-viewer scheduling, ending at transport handoff. **Source latency** on patient/node dashboards stops here; unsent overwritten frames are excluded |
| Stream transport | Transport handoff through serialization, TLS, network, message assembly and receiver dispatch |
| Receive queue | Surgeon graph dispatch through browser relay or native decode entry |
| WebRTC queue | Relay through RTP handoff |
| Decode | Browser-reported per-frame decoding/output preparation, or native GPU decoding and owned output preparation |
| WebRTC + display | RTP handoff to estimated browser display, minus Decode. Includes local transmission, jitter buffering and display scheduling. Combining these avoids treating sub-millisecond browser transit as resolved when it is below clock-mapping uncertainty |
| Holoviz handoff | Native decoder output through SDK handoff. Holoviz rendering and physical scanout are not measured |
| Robot acknowledgement | Per-robot command through controller acknowledgement; does not measure completed physical motion |

Every traced frame has adjacent boundaries. The P50/P95/P99/P99.9 stacked bars rank **total** latency, then use the same ranked frames and interpolation weights for all stage contributions. Each column sums to its total, including display rounding. These contributions are not independent stage percentiles; the top-row cards and their trends show total latency P99 and each processing stage's own P99. Missing timestamps leave totals unavailable; relative-clock estimates include their uncertainty. Frame spacing is cadence, not a latency budget.

Browser timing uses `requestVideoFrameCallback` RTP timestamps and estimated display time. An unreliable, bounded data channel carries small timing records while metrics is visible; lost records skip a sample without blocking video. Four-timestamp clock exchanges between the local service and browser bound their clock mapping, rejecting bounds over 1 ms. The one private aiortc packet observer is isolated in `stream_timing.py` and exercised by a real RTP/browser check. No video pixels are copied for diagnostics. This is software buffer-to-estimated-display timing, not a photon-to-glass measurement. [Browser timestamp definitions](https://wicg.github.io/video-rvfc/)

Detailed samples retain the latest 10,000 frames after a 2-second warmup. History retains at most one hour of 5-second buckets; the view offers 1 min, 5 min, 30 min and 1 hr. Browser history records while its metrics panel is open, survives closing/reopening that panel, and shows gaps while collection is paused. Server/native history records while frames flow. Reset clears only the selected device; restarting a service or reloading a browser clears its in-memory history. Percentiles are calculated outside the frame callbacks (server aggregation runs in a worker).

Durations use local monotonic clocks; host-to-host hops use verified UTC or a relative clock estimate. Buffer handoff uses the local monotonic clock; hardware receive timestamps remain metadata and do not define the start. [Chrony error bounds](https://chrony-project.org/doc/latest/chronyc.html) · [Linux PTP](https://www.linuxptp.org/documentation/)

## Control and admission

A serialized patient control path validates each request inside a Holoscan graph. A separate graph on the device node invokes its controller adapter. Surgeon payloads and returned state also pass through its graph. Controller URIs remain on patient nodes.

Approvals persist against a hash of the surgeon service's private credential; display names alone confer no access. A returning service inherits its approved permissions. New identities and requests for additional robot permission need patient approval. Offline approvals remain visible and revocable. Connections, video tickets and robot ownership are temporary. Robot ownership uses a random token, increasing command sequence and a two-second renewable lease. Commands older than 300 ms are rejected; application graphs also expire queued work. Node timestamps use an estimated coordinator clock offset. Release, disconnect, revocation and expiry request a hold before another owner is allowed. The simulator acknowledgment confirms assigned drive targets, not completion of motion.

The current controller adapters support only MIRA and Franka simulation. Physical controllers need their own stop/state semantics and verification.

## Connections and deployment

HTTP binds to loopback and rejects other Host headers and cross-origin writes. The application endpoint uses TLS 1.3. Surgeons pin the first observed patient certificate; SSH enrollment delivers a pinned certificate fingerprint and random node credential. Certificate changes fail the connection. Pending surgeons receive no inventory or video. Display names are labels, not authenticated identities.

Each SSH node is installed under `~/.local/share/holoscan-telesurgery/NODE_ID`. It reconnects after coordinator loss, stopping streams and holding controllers while disconnected. Re-entering an offline target retries deployment. Node logs stay in that installation; deployment logs are in the patient's state directory. Nodes need a driver, CUDA 13 development tools, source access and permissions to install missing system libraries.

State defaults to `runs/ROLE-PORT`; `--state-dir` selects another directory. A file lock prevents two services from sharing it. YAML files hold enrolled nodes, certificate pins, camera settings, SSH node environments and surgeon approvals. Writes replace files atomically with owner-only permissions. Existing JSON configuration migrates on first read. Simulator manifests, process messages and benchmark reports retain their existing formats. SIGTERM closes connections, holds controllers, stops cameras and joins the SDK graphs.

Nodes expose direct video on TCP **7449** (standalone custom service port + 1). Surgeons must be able to reach that endpoint; the coordinator never silently relays an unreachable node.

## Camera configuration

Automatic HSB discovery identifies boards, not attached sensor models. The default camera is IMX274 sensor 0 at 1080p60. To override it or add sensor 1, place a `devices.yaml` in the node's device directory (`runs/patient-8000/host` locally; the installation directory itself on an enrolled node). For example:

```yaml
cameras:
  - id: hsb-192.168.0.2-0
    name: Endoscope
    kind: HSB
    source: imx274
    hololink: 192.168.0.2
    expander: 0
    width: 3840
    height: 2160
    fps: 60
```

Use a distinct ID and `expander: 1` for another sensor. The HSB network link and camera must already be configured. Names changed in the dashboard persist separately.

Simulation cameras offer 640×480, 1280×720, 1920×1080, 2560×1440 and 3840×2160. Changing resolution recreates that camera’s Isaac render product; frames are not upscaled. Each camera selects its own available codec. The initial selection is 1080p/H.264.

IMX274 processing applies optical-black correction, white balance, demosaic and a GPU sRGB display transfer before encoding. The [sRGB transfer](https://www.w3.org/Graphics/Color/srgb) is not an exposure control.

## Extending the application

Add camera/controller adapters behind the existing interfaces, or a simulation preset in `presets.py` with its scene construction in `scene.py`. Permission checks belong in the application, not the UI. Keep SDK-specific code inside its backend and dependency changes in `dependencies/sdk4.toml` or `sdk5.toml`.

Planned robot input and controller work is tracked in [TODO](TODO.md).
