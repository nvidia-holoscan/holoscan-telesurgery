# Contributing

This project is released under the Apache License, Version 2.0. See [LICENSE](LICENSE). Contributions are accepted only under that license. By submitting a contribution you agree that it may be redistributed under Apache-2.0.

Report security issues privately, as described in [SECURITY.md](SECURITY.md). Do not open a public issue, pull request, or discussion for a suspected vulnerability.

Third-party software fetched by the build is attributed in [NOTICE](NOTICE). Do not copy third-party source into this tree. A new or upgraded dependency must be pinned, added to `NOTICE` with its license, and reviewed before it is committed or installed into a published image. Copyleft, custom, and unpublished licenses need Open Source Review Board approval before redistribution.

Run native [setup](README.md#native-execution), then install development tools without replacing the built SDK and codec:

```bash
uv pip install --python .venv-sdk5/bin/python --group dev
.venv-sdk5/bin/playwright install chromium
.venv-sdk5/bin/pre-commit run --all-files
xvfb-run -a .venv-sdk5/bin/pytest -q
```

For SDK 4, use `.venv-sdk4`. Use `setup.sh` for runtime dependency changes so the SDK and patched codec stay consistent.

Native setup and the Docker image include Xvfb and xauth. Run tests under `xvfb-run -a` so native viewers and controller windows use a virtual display. The native controller layout tests also create their own virtual display, and skip if Xvfb is unavailable; they never open on the desktop display.

Keep application logic in the shared packages and SDK-specific code in `packages/runtime/src/telesurgery_runtime/backends`. Preserve bounded queues, frame ownership, CUDA ordering, command expiry and orderly shutdown. Verify hardware changes on the actual device. Keep generated artifacts in `workspace/` or `build/`. Do not hard-wrap Markdown paragraphs.

Every source file covered by `scripts/check_license.py` needs this leading header, with the current year:

```text
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
```

## Signing off your work

Every commit must include a Developer Certificate of Origin sign-off (`git commit -s`). Pull requests that contain unsigned commits will not be accepted. Use your real name and a verifiable email address. Pseudonyms and anonymous contributions are not accepted.

```bash
git commit -s -m "feat: describe the change"
```

That appends:

```text
Signed-off-by: Your Name <your@email.com>
```

Full text of the DCO (<https://developercertificate.org/>):

```text
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## Dependencies

`dependencies/sdk4.toml` and `dependencies/sdk5.toml` are used by native and Docker builds:

| Provider    | Configuration                                                                  |
| ----------- | ------------------------------------------------------------------------------ |
| `git`       | `git` URL, pinned `rev`, optional `patches`; SDK builds also specify `version` |
| `packages`  | `pip` and/or `apt` lists; optional CMake `prefix`                              |
| `installed` | Optional `prefix`; reuse installed dependencies                                |

All dependency sources are public and stay under `build/third_party/`. SDK 5 uses unmodified public EA3 source. Physical nodes with HSB configuration or detected board announcements automatically use SDK 4 and the public sensor-bridge library. Native setup prepares that isolated environment alongside SDK 5; Docker selects a separate image before launch. No process loads both SDKs. For backend development, `--sdk 4` and `--sdk 5` remain available on setup and run commands; detected HSB always selects SDK 4 for physical nodes.

## Verification

Tests cover admission, exclusive control, stale commands, disconnection, real SDK graphs, GPU codecs and browser video. `scripts/benchmark.py` collects real camera-to-viewer measurements from dedicated patient and surgeon services; its usage is in [BENCHMARK.md](BENCHMARK.md).

Pull requests run CPU-only unit and browser tests, pre-commit, SPDX copyright/license checks, documentation link checks and security checks. GPU and Holoscan integration tests run locally with the corresponding SDK installed.

CI reports the 20 slowest tests. To profile the same selection locally, run `xvfb-run -a .venv-sdk5/bin/pytest -q -m 'not sdk and not gpu' --durations=20 --durations-min=1`. Cover shared behavior once per distinct code path; test device labels and responsive layouts separately instead of multiplying them into every motion scenario. Keep screenshots only when they are asserted or retained as review artifacts.

For Blossom CI, `SachidanandAlle`, `jjomier` and `wendell-hom` can comment `/build` on a pull request. The repository needs the `blossom` runner and `BLOSSOM_KEY` / `CI_SERVER` secrets; `workflow_dispatch` is reserved for CI result callbacks. Comment triggers become available once the workflow is on `main`.

CI audits locked Python dependencies, scans Python code and checks workflow security on changes and weekly. Dependency updates come through Dependabot. Private keys are checked before commit; keep certificates, credentials and runtime state out of Git. Dependency scans do not cover the CUDA/Isaac Sim images or vendor binaries.
