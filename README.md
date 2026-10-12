# Holoscan Telesurgery

A distributed telesurgery demo built with **NVIDIA Holoscan and Holoscan Sensor Bridge**. Device nodes bring cameras and robots into a patient room. The patient approves nodes and surgeons; surgeons view live feeds and control permitted robots from their own dashboard.

Use physical devices or **MIRA, Franka and Versius simulations**, with browser or native Holoviz viewing and per-stream latency metrics.

![Surgeon walkthrough: live MIRA and Franka streams, keyboard and gamepad tool controls, depth views and metrics](docs/images/surgeon-walkthrough.gif)

[Patient dashboard](docs/images/patient-walkthrough.gif) · [Architecture](docs/architecture.md) · [Benchmarks](BENCHMARK.md)

## System requirements

| Component        | Requirement                                                                                                                                                                                               |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Operating system | Ubuntu 24.04 on x86 or ARM64. Use Docker on Ubuntu 22.04.                                                                                                                                                 |
| GPU              | NVIDIA GPU with hardware video encoding/decoding and a CUDA 13-compatible driver.                                                                                                                         |
| Docker           | Docker with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), usable without `sudo`. Required for `--docker` and simulation nodes. |
| Native builds    | CUDA 13 development toolkit and GCC 13+. `setup.sh` installs the remaining build dependencies.                                                                                                            |
| Simulation nodes | x86 with an RTX GPU, or DGX Spark, meeting [Isaac Sim requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/requirements.html).                                                     |
| Viewing          | A browser for dashboards; a local desktop display for Holoviz or the Isaac Sim window.                                                                                                                    |
| Build access     | SSH access to NVIDIA GitLab for the current SDK 5 Hololink dependency.                                                                                                                                    |

## Quickstart

### 1. Patient

```bash
./run.sh --docker patient
```

Open **[localhost:8000](http://localhost:8000)**. Your room starts empty.

### 2. Surgeon

In a separate terminal or on the surgeon's machine:

```bash
./run.sh --docker surgeon
```

Open **[localhost:8002](http://localhost:8002)**. Enter the patient hostname, your name and requested access. The default endpoint works when both services run on the same machine.

> Approve the request in Patient.

### 3. Nodes

In separate terminals, start simulation (`mira`, `franka` or `versius`):

```bash
./run.sh --docker node --patient 127.0.0.1 --sim mira
```

For Versius, extract the supplied CMR URDF archive so that `workspace/assets/versius/BSU.urdf`, `needle_holder_platform.urdf`, `fenestrated_grasper_platform.urdf` and `meshes/` exist, then use `--sim versius`. The shared scene has three instrument arms and an endoscope arm, with independent controllers, a 1080p endoscope view and an additional 1080p room observer view. Two surgeons can each control an instrument arm to pick up a needle, hand it over and place it in the blue target on the suture pad. The procedure view follows the endoscope arm; the room view shows the full setup. The vendor assets stay in the local workspace.

Or physical cameras and robots:

```bash
./run.sh --docker node --patient 127.0.0.1
```

> For nodes on another machine, replace `127.0.0.1` with the patient IP.

Approve each node under **Nodes**, then start streams or connect robots. In Surgeon, select the feeds and robot to use.

[Camera configuration](docs/architecture.md#camera-configuration) · [Robot controls](docs/robot-controls.md)

For a neural encoding trial, use a **1280 × 720** or **1920 × 1080** stream and choose **Surgical Neural Tokenizer (trial)** in **Stream settings**. You can apply the encoding while streaming and switch back to H.264. Normal setup includes TensorRT; the pinned [Hugging Face model](https://huggingface.co/nvidia/Cosmos-Tokenizer-Surg) downloads automatically on first use, and GPU engines are built and cached under `workspace/cache`. Holoviz displays the decoded GPU image directly; browser viewing converts it to H.264 on the viewing machine. Use the existing stream metrics to compare performance.

## Physical devices

- **MIRA:** Copy the vendor API executable to `workspace/mira-api` (or provide `--mira-api PATH`) and run `./run.sh --docker node --patient PATIENT_IP --profile mira`.
- **Franka:** Enable FCI in Desk and run `./run.sh --docker node --patient PATIENT_IP --profile franka` (native: run `./setup.sh --profile franka` first and omit `--docker`); the default address is `172.16.0.3`, overridden with `--franka-address ROBOT_IP`.
- **HSB camera:** Connect the board to the node's camera network and run `./run.sh --docker node --patient PATIENT_IP`; boards are discovered automatically with IMX274 sensor 0 as the default ([other sensors](docs/architecture.md#camera-configuration)).

## Native execution

With the CUDA 13 development toolkit installed, run setup once on each machine:

```bash
./setup.sh
./run.sh patient

# Another terminal:
./run.sh surgeon

# Another terminal:
./run.sh node --patient 127.0.0.1 --sim mira
```

## Miscellaneous

- [Holoscan SDK 5 EA3](https://github.com/nvidia-holoscan/holoscan-sdk/tree/v5.0.0-ea3) is the default. Add `--sdk 4` to `./setup.sh` and `./run.sh` for SDK 4.
- Docker images use `holoscan-telesurgery:0.1.0` for SDK 5 and `holoscan-telesurgery:0.1.0-sdk4` for SDK 4.
- Dashboard ports are **8000** and **8002** (`--port`). The patient endpoint is **7447** (`--endpoint-port`).
- Dashboards bind to `127.0.0.1`. Add `--host 0.0.0.0 --ssl` for HTTPS from another machine. There is no login.
- Saved state, simulation assets, caches and logs use `./workspace`; pass `--workspace PATH` to setup and run commands to change it.
- `run.sh` saves terminal output to a separate timestamped file in `workspace/logs/` for each dashboard or node.
- Stop the services and run `mv workspace workspace-backup` to start fresh.

Research demonstration. [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [TODO](docs/TODO.md)
