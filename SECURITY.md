# Security Policy: Holoscan Telesurgery

## Reporting a Vulnerability

If you discover a potential security vulnerability, **do not open a public issue, pull request, or discussion**.

- **Web (preferred):** Report it through the [NVIDIA Vulnerability Disclosure Program](https://www.nvidia.com/en-us/security/).
- **Email:** Send details to [psirt@nvidia.com](mailto:psirt@nvidia.com). For encrypted communication, use the [NVIDIA public PGP key](https://www.nvidia.com/en-us/security/pgp-key).
- **GitHub:** Use this repository's **Security** tab to submit a private report on `nvidia-holoscan/holoscan-telesurgery`.

Include the project name and affected version or branch, vulnerability type, reproduction steps, proof-of-concept code when available, and an impact assessment. Detailed reports help NVIDIA evaluate and address issues faster.

NVIDIA's Product Security Incident Response Team (PSIRT) will acknowledge the report, validate and assess the issue, develop and test fixes, and publish a security bulletin when appropriate.

## Supported Versions

Security fixes are applied to the current `main` branch. The default runtime is Holoscan SDK 5.0.0 EA3, commit `163dac10195d6b603f9e6158a1d5dfb390732203`. `./setup.sh --sdk 4` and `./run.sh --sdk 4` select Holoscan SDK 4.6.0.

## Security Architecture and Context

Holoscan Telesurgery is a research demonstration. Patient and surgeon dashboards admit cameras and robots, forward live video, and send robot commands. Device nodes run on the patient side. Simulation nodes can start Isaac Sim. Native Holoviz and browser WebRTC are the viewers.

This project operates at the application level. Its primary security responsibility is to keep dashboard control, robot commands, and live video inside the patient-approved set of nodes and surgeons. It does not provide user accounts.

The principal security boundaries are:

- `./run.sh` starts `python -m telesurgery`. Dashboards bind to `127.0.0.1` unless `--host` is set. Ports are 8000 (patient), 8002 (surgeon), and 7447 (patient endpoint).
- `packages/app/src/telesurgery/server/security.py` rejects non-local dashboard hosts when bound to loopback, blocks cross-origin requests, requires JSON for POST, and sets a Content Security Policy. `--ssl` serves the dashboard with TLS 1.3.
- `packages/core/src/telesurgery_core/transport/tls.py` creates a local ECDSA certificate for the patient endpoint, stores the unencrypted key at mode `0600`, and pins the peer certificate fingerprint in `peers.yaml`. The client context uses TLS 1.3 with `CERT_NONE` and hostname checking disabled; identity is the pin, not a public CA.
- `packages/core/src/telesurgery_core/control/access.py` keeps surgeon requests pending until the patient approves them. A remembered identity is the SHA-256 of a 43-character credential. Robot control is a separate flag from viewing.
- `packages/core/src/telesurgery_core/video/codecs.py` encodes and decodes H.264, H.265, and NVJPEG on the GPU through a locally patched `PyNvVideoCodec` and `nvidia-nvimgcodec`. `packages/app/src/telesurgery/server/media.py` forwards already-encoded H.264 to browsers with `aiortc` and does not transcode it.
- `packages/sim/src/telesurgery_sim/runtime/launch.py` starts `nvcr.io/nvidia/isaac-sim:6.0.1` with `ACCEPT_EULA=Y`. `scripts/docker.sh` runs the application container with `--network host` and, for a node, mounts `/var/run/docker.sock`.
- `scripts/build_franka.sh` can write `/etc/security/limits.d/90-telesurgery-franka-*.conf` so the operator can use real-time priority 99.
- GitHub Actions in `.github/workflows/` check out with `persist-credentials: false` and `contents: read`. Blossom CI uses the `BLOSSOM_KEY` and `CI_SERVER` secrets and accepts `/build` only from the accounts named in `blossom-ci.yml`.

### Threat Model

1. **Network exposure without accounts:** The README states that there is no login. `--host 0.0.0.0` serves the patient dashboard, surgeon dashboard, and approval controls on the network. Anyone who can reach those ports can request access or, on the patient dashboard, approve nodes and surgeons.
2. **Robot motion after approval:** `Access.approve` and a remembered robot credential authorize `packages/runtime` robot commands. An approved surgeon session, a copied credential, or a compromised dashboard can jog a connected Franka or MIRA arm. Command expiry limits stale commands; it does not authenticate the person at the keyboard.
3. **First-use endpoint identity:** `pin_peer` stores the first TLS certificate fingerprint it sees for an address and later rejects a change. The first connection to a new patient address accepts whatever certificate is presented. A network attacker on that first connection can pin their own endpoint.
4. **Untrusted video bitstreams:** Camera nodes and WebRTC peers supply H.264, H.265, NVJPEG, and raw frames. `video/formats.py` parses those payloads, and `video/codecs.py` feeds them to NVDEC, NVENC, and nvImageCodec. A malicious node can submit crafted encoded video to those parsers and to the browser decoder.
5. **Docker socket on the node container:** `scripts/docker.sh` bind-mounts `/var/run/docker.sock` into a node container so it can start Isaac Sim and managed MIRA controllers. A process in that container can start other containers on the host, including privileged ones.
6. **Host real-time priority for Franka:** `scripts/build_franka.sh` installs an `rtprio` 99 limit for the invoking user. That user can then run real-time threads outside this application.
7. **Build fetches and patched codecs:** SDK 5 clones internal Hololink over SSH and applies `native/patches/`. `scripts/builders/codecs.py` downloads `PyNvVideoCodec` 2.2.3 from NGC, patches NVENC, and installs the result. `packages/sim` downloads USD assets from the Isaac content host. A substituted URL, patch, or archive changes the binary that the image runs. CI dependency audits do not cover the CUDA image, Isaac Sim, or those vendor archives.

### Critical Security Assumptions

- The operator controls the host, Docker, GPU devices, and whether dashboards bind beyond localhost. This repository does not add an account system.
- Patient approval is the authorization decision. The software assumes the person using the patient dashboard is entitled to admit nodes and surgeons.
- Remembered surgeon credentials in the workspace directory stay on a trusted disk. The workspace is created by the operator and is not committed.
- Endpoint TLS pins are established on a network path the operator trusts for the first connection. Later connections assume that stored fingerprint is the patient endpoint.
- Holoscan SDK, CUDA, the NVIDIA driver, NVENC, NVDEC, and the CUDA container enforce their own device and memory contracts.
- Robot adapters assume the connected Franka or MIRA controller honors protocol limits. This application adds command expiry and exclusive control; it does not replace the robot's own safety system.
- Isaac Sim and its EULA are accepted by the operator. The simulator container is not a security boundary for the host Docker daemon.
- Secrets used to clone internal Hololink and to run Blossom CI are supplied by the build environment. They are not committed. Pre-commit rejects private keys.
- Third-party packages are installed at build or setup time from the pins in `uv.lock`, `dependencies/*.toml`, and the Dockerfile. They are not vendored in this source tree. Their licenses are listed in `NOTICE`.

## Dependency and Distribution Security

This repository redistributes NVIDIA Apache-2.0 application source. Container and native setup download third-party software, including GPL and LGPL packages in the runtime image (`chrony`, `libglib2.0`, `libusb`) and FFmpeg through the PyAV wheel installed for `aiortc`. The Franka extra also installs Pinocchio, which redistributes Qhull under its custom license, and builds against Eigen (MPL-2.0).

New or upgraded third-party dependencies must have their license and redistribution terms reviewed before they are pinned or installed into a published image. Components distributed with a Holoscan product must follow the applicable NVIDIA Open Source Review Board process. Corresponding source for copyleft components in a published image must be offered with that image. Attributions for the direct dependencies are in `NOTICE`.
