# Contributing

Run native [setup](README.md#native-execution), then install development tools without replacing the built SDK and codec:

```bash
uv pip install --python .venv-sdk5/bin/python --group dev
.venv-sdk5/bin/playwright install chromium
.venv-sdk5/bin/ruff check .
.venv-sdk5/bin/ruff format --check .
.venv-sdk5/bin/pytest -q
```

For SDK 4, use `.venv-sdk4`. Use `setup.sh` for runtime dependency changes so the SDK and patched codec stay consistent.

Keep application logic in the shared packages and SDK-specific code in `packages/runtime/src/telesurgery_runtime/backends`. Preserve bounded queues, frame ownership, CUDA ordering, command expiry and orderly shutdown. Verify hardware changes on the actual device. Keep generated artifacts in `workspace/` or `build/`. Do not hard-wrap Markdown paragraphs.

## Dependencies

`dependencies/sdk4.toml` and `dependencies/sdk5.toml` are used by native and Docker builds:

| Provider    | Configuration                                                                  |
| ----------- | ------------------------------------------------------------------------------ |
| `git`       | `git` URL, pinned `rev`, optional `patches`; SDK builds also specify `version` |
| `packages`  | `pip` and/or `apt` lists; optional CMake `prefix`                              |
| `installed` | Optional `prefix`; reuse installed dependencies                                |

Git uses ordinary SSH/HTTPS authentication. Sources stay under `build/third_party/`. Compatible public releases can replace these providers without changing application code. Camera bindings also require matching C++ headers and CMake exports. SDK 5 uses unmodified public EA3 source. Its compatible Hololink port still requires NVIDIA GitLab and camera-specific patches; remove those when upstream supplies the fixes.

## Verification

Tests cover admission, exclusive control, stale commands, disconnection, real SDK graphs, GPU codecs and browser video. `scripts/benchmark.py` collects real camera-to-viewer measurements from dedicated patient and surgeon services; its usage is in [BENCHMARK.md](BENCHMARK.md).

Pull requests run CPU-only unit and browser tests, pre-commit, SPDX copyright/license checks, documentation link checks and security checks. GPU and Holoscan integration tests run locally with the corresponding SDK installed.

For Blossom CI, `SachidanandAlle`, `jjomier` and `wendell-hom` can comment `/build` on a pull request. The repository needs the `blossom` runner and `BLOSSOM_KEY` / `CI_SERVER` secrets; `workflow_dispatch` is reserved for CI result callbacks. Comment triggers become available once the workflow is on `main`.

CI audits locked Python dependencies, scans Python code and checks workflow security on changes and weekly. Dependency updates come through Dependabot. Private keys are checked before commit; keep certificates, credentials and runtime state out of Git. Dependency scans do not cover the CUDA/Isaac Sim images or vendor binaries.
