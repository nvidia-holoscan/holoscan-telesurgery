# Holoscan Telesurgery

A distributed telesurgery demo built with **NVIDIA Holoscan and Holoscan Sensor Bridge**. Device nodes bring cameras and robots into a patient room. The patient approves nodes and surgeons; surgeons view live feeds and control permitted robots from their own dashboard.

Use physical devices or **MIRA and Franka simulations**, with browser or native Holoviz viewing and per-stream latency metrics.

![Surgeon workspace: live MIRA feeds and controls for both arms and grippers](docs/images/surgeon-walkthrough.gif)

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

In separate terminals, start simulation (`mira` or `franka`):

```bash
./run.sh --docker node --patient 127.0.0.1 --sim mira
```

Or physical cameras and robots:

```bash
./run.sh --docker node --patient 127.0.0.1
```

> For nodes on another machine, replace `127.0.0.1` with the patient IP.

Approve each node under **Nodes**, then start streams or connect robots. In Surgeon, select the feeds and robot to use.

[Camera configuration](docs/architecture.md#camera-configuration) · [Robot controls](docs/robot-controls.md)

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
- Dashboard ports are **8000** and **8002** (`--port`). The patient endpoint is **7447** (`--endpoint-port`).
- Dashboards bind to `127.0.0.1`. Add `--host 0.0.0.0 --ssl` for HTTPS from another machine. There is no login.
- Saved state, simulation assets, caches and logs use `./workspace`; pass `--workspace PATH` to setup and run commands to change it.
- `run.sh` saves terminal output to a separate timestamped file in `workspace/logs/` for each dashboard or node.
- Stop the services and run `mv workspace workspace-backup` to start fresh.

Research demonstration. [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md) · [TODO](docs/TODO.md)
