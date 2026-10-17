# Holoscan Telesurgery

A distributed telesurgery demo built with **NVIDIA Holoscan and Holoscan Sensor Bridge**. Device nodes bring cameras and robots into a patient room. The patient approves nodes and surgeons; surgeons view live feeds and control permitted robots from their own dashboard.

Use physical devices or **MIRA, Franka and Versius simulations**, with browser or native Holoviz viewing and per-stream latency metrics.

![Project walkthrough: CMR Versius and MIRA simulation, Franka color and depth side by side, physical Franka, patient approvals, HSB 4K stream settings, browser and native controls, and live metrics](docs/images/surgeon-walkthrough.gif)

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
| Robot input      | Keyboard, Xbox/PlayStation/Nintendo Switch gamepad, or Haply Inverse3 (MIRA, Franka and Versius simulations).                                                                                             |

## Setup

Run commands from the repository root on each machine. Camera support is selected automatically from the node’s saved configuration and connected hardware. Connect HSB boards to the configured camera network before setup and node startup.

### Docker execution

Prepare the host once:

```bash
./setup.sh --docker
```

`run.sh --docker` builds and selects the appropriate image automatically.

### Native execution

With the CUDA 13 development toolkit installed, run:

```bash
./setup.sh
```

Unchanged setups are reused automatically. Use `./setup.sh --force` to rerun installation and validation.

Follow the quickstart below, omitting `--docker` from run commands. Simulation nodes still require Docker for Isaac Sim.

## Quickstart

Start each service in a separate terminal. The commands below use Docker.

### 1. Patient

```bash
./run.sh --docker patient
```

Open **[localhost:8000](http://localhost:8000)**. Your room starts empty.

### 2. Nodes

Choose a **simulation** node or a **physical** node. Physical nodes can provide cameras (including HSB), robots, or both.

#### Simulation nodes

Select a simulation with `--sim`: `mira`, `franka` or [CMR Versius](#cmr-versius-simulation) (`versius`).

```bash
./run.sh --docker node --patient 127.0.0.1 --sim mira
```

#### Physical nodes

For cameras, including HSB, start a node without a robot profile:

```bash
./run.sh --docker node --patient 127.0.0.1
```

Cameras are discovered automatically. Connect HSB boards to the configured camera network before starting the node. If the node previously used a robot profile, add `--profile none` to clear its saved profile selection.

Add a robot profile to include a physical robot alongside any cameras.

Start a physical Franka node after enabling FCI in Desk:

```bash
./run.sh --docker node --patient 127.0.0.1 --profile franka
```

Start a physical MIRA node after copying the vendor API executable to `workspace/mira-api` (or supply its path with `--mira-api PATH`):

```bash
./run.sh --docker node --patient 127.0.0.1 --profile mira
```

Run each node on the host running its simulation or connected to its physical devices. If Patient runs on another machine, replace `127.0.0.1` with its IP. See [physical devices](#physical-devices) for Franka address overrides, native setup and HSB cameras.

Approve each node under **Nodes** in Patient. The node automatically starts configured controllers, connects its robots and starts discovered streams using saved settings, or the device defaults on first use.

### 3. Surgeon

On the surgeon's machine:

```bash
./run.sh --docker surgeon
```

Open **[localhost:8002](http://localhost:8002)**. Enter the patient hostname, your name and requested access. The default endpoint works when both services run on the same machine.

Approve the request in Patient, then select feeds and a robot in Surgeon. See [robot controls](docs/robot-controls.md) for keyboard, gamepad and Haply mappings.

## Node configuration

Replace `PATIENT_IP` below with the patient hostname or IP.

### CMR Versius simulation

Extract `CMR_Versius_All_Assets.zip` on the simulation host, preserving its folders:

```bash
mkdir -p workspace/assets/versius
unzip CMR_Versius_All_Assets.zip -d workspace/assets/versius
```

Start the simulation node:

```bash
./run.sh --docker node --patient PATIENT_IP --sim versius
```

See [Versius controls](docs/robot-controls.md#versius-simulation) for the two-surgeon handoff demo.

### Physical devices

- **MIRA:** Copy the vendor API executable to `workspace/mira-api` (or provide `--mira-api PATH`) and run `./run.sh --docker node --patient PATIENT_IP --profile mira`.
- **Franka:** Enable FCI in Desk and run `./run.sh --docker node --patient PATIENT_IP --profile franka` (native: run `./setup.sh --profile franka` first and omit `--docker`); the default address is `172.16.0.3`, overridden with `--franka-address ROBOT_IP`.
- **HSB camera:** Connect the board to the node's camera network and run `./run.sh --docker node --patient PATIENT_IP`; boards are discovered automatically with IMX274 sensor 0 as the default ([other sensors](docs/architecture.md#camera-configuration)).

## Miscellaneous

### Streams

- See [camera configuration](docs/architecture.md#camera-configuration) for source and format settings.

> For 720p or 1080p streams, try **Surgical Neural Tokenizer (trial)** in **Stream settings**.

### Network

- Dashboard ports are **8000** and **8002** (`--port`). The TLS patient endpoint is **7447** (`--endpoint-port`), bound to all IPv4 interfaces unless `--endpoint-host` is set.
- Dashboards bind to `127.0.0.1`. For network access, use `--host 0.0.0.0 --ssl` and the access code from `dashboard-access.yaml` (path printed at startup). Network HTTP requires explicit `--insecure`. See [Security](SECURITY.md).
- Custom HTTPS certificates must cover a local hostname or IP address for native controls.

### Workspace

- Data is stored in `./workspace`, with logs under `logs/`. Override with `--workspace PATH`.

### Stopping services

Works for native and Docker services on the local host:

```bash
./run.sh status
./run.sh stop patient
./run.sh stop surgeon
./run.sh stop node --name uni-mira
./run.sh stop --all
```

A role alone stops its only running instance. If several match, specify `--name` / `--port`, or add `--all`. Use `--workspace PATH` for another workspace. Shutdown allows 30 seconds for cleanup. Change this with `--timeout SECONDS`; add `--force` to kill after the timeout.

----
Research demonstration. [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [TODO](docs/TODO.md)
