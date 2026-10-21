# Third-Party Python Dependency Inventory

This inventory records the external Python distributions selected from `uv.lock` for the release. Versions and dependency roles come from the lockfile and the repository's `uv` installation commands; licenses, upstream sources, and legal-file locations come from the selected-version package metadata and upstream projects.

The 77 external distributions in `uv.lock` are the union of three distinct selections; 77 is not an observed runtime-package count:

- **Release runtime (39):** selected by `uv sync --locked --all-packages --no-dev --extra codecs-cu13 --extra tokenizer-cu13`. Platform markers determine which artifacts are installed on a particular target.
- **Optional Franka-only additions (17):** selected only by `telesurgery-robots[franka]` and not already in the release runtime selection. Ten additional Franka dependencies are shared with the runtime selection and appear in the runtime table.
- **Development-only (21):** selected by the `dev` dependency group and absent from release and Franka selections. Three development dependencies are shared with the runtime selection and appear in the runtime table.

“Distribution” below means the exact wheel or source distribution identified by `uv.lock`. Upstream links are supplied where package metadata does not declare a legal-file path. Non-Python system packages, native source builds, container bases, models, and proprietary components are documented in `NOTICE`.

## Release runtime

| Component | Version | License / terms | Upstream source | Legal-file location | Distribution role |
| --- | ---: | --- | --- | --- | --- |
| `aiohappyeyeballs` | 2.7.1 | PSF-2.0 | [upstream](https://github.com/aio-libs/aiohappyeyeballs) | distribution: `LICENSE` | runtime transitive |
| `aiohttp` | 3.14.4 | Apache-2.0 AND MIT | [upstream](https://github.com/aio-libs/aiohttp) | distribution: `LICENSE.txt`, `vendor/llhttp/LICENSE` | runtime direct |
| `aioice` | 0.10.2 | BSD-3-Clause | [upstream](https://github.com/aiortc/aioice) | distribution: `LICENSE` | runtime transitive |
| `aiortc` | 1.15.0 | BSD-3-Clause | [upstream](https://github.com/aiortc/aiortc) | distribution: `LICENSE` | runtime direct |
| `aiosignal` | 1.4.0 | Apache-2.0 | [upstream](https://github.com/aio-libs/aiosignal) | distribution: `LICENSE` | runtime transitive |
| `attrs` | 26.1.0 | MIT | [upstream](https://github.com/python-attrs/attrs) | distribution: `LICENSE` | runtime transitive |
| `av` | 17.1.0 | BSD-3-Clause | [upstream](https://github.com/PyAV-Org/PyAV) | distribution: `LICENSE.txt`, `AUTHORS.py`, `AUTHORS.rst` | runtime transitive |
| `cffi` | 2.1.1 | MIT-0 | [upstream](https://github.com/python-cffi/cffi) | distribution: `LICENSE` | runtime transitive; shared with Franka |
| `cryptography` | 50.0.2 | Apache-2.0 OR BSD-3-Clause | [upstream](https://github.com/pyca/cryptography) | distribution: `LICENSE`, `LICENSE.APACHE`, `LICENSE.BSD` | runtime direct; shared with Franka |
| `cuda-pathfinder` | 1.8.2 | Apache-2.0 | [upstream](https://github.com/NVIDIA/cuda-python) | distribution: `LICENSE` | runtime transitive |
| `cuda-toolkit` | 13.4.2 | NVIDIA proprietary terms | [upstream](https://developer.nvidia.com/cuda-toolkit) | [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) | runtime transitive |
| `cupy-cuda13x` | 14.2.0 | MIT | [upstream](https://github.com/cupy/cupy) | distribution: `LICENSE`, `docs/source/license.rst` | runtime direct |
| `dnspython` | 2.8.0 | ISC | [upstream](https://github.com/rthalley/dnspython) | distribution: `LICENSE` | runtime transitive |
| `frozenlist` | 1.8.0 | Apache-2.0 | [upstream](https://github.com/aio-libs/frozenlist) | distribution: `LICENSE` | runtime transitive |
| `google-crc32c` | 1.9.0 | Apache-2.0 | [upstream](https://github.com/googleapis/python-crc32c) | distribution: `LICENSE` | runtime transitive |
| `idna` | 3.20 | BSD-3-Clause | [upstream](https://github.com/kjd/idna) | distribution: `LICENSE.md` | runtime transitive |
| `ifaddr` | 0.2.0 | MIT | [upstream](https://github.com/pydron/ifaddr) | [upstream `LICENSE.txt`](https://github.com/pydron/ifaddr/blob/master/LICENSE.txt) | runtime direct |
| `multidict` | 6.9.1 | Apache-2.0 | [upstream](https://github.com/aio-libs/multidict) | distribution: `LICENSE` | runtime transitive |
| `numpy` | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [upstream](https://github.com/numpy/numpy) | distribution: `LICENSE.txt` and component license files | runtime direct; shared with Franka |
| `nvidia-cuda-runtime` | 13.4.92 | NVIDIA proprietary terms | [upstream](https://developer.nvidia.com/cuda-toolkit) | distribution: `License.txt` | runtime transitive |
| `nvidia-nvimgcodec-cu13` | 0.9.0.20 | Apache-2.0 | [upstream](https://github.com/NVIDIA/nvImageCodec) | distribution: `LICENSE.txt` | runtime direct |
| `opencv-python-headless` | 5.0.0.93 | Apache-2.0 and bundled third-party licenses | [upstream](https://github.com/opencv/opencv-python) | [`LICENSE-3RD-PARTY.txt`](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt), [`LICENSE.txt`](https://github.com/opencv/opencv-python/blob/4.x/LICENSE.txt) | runtime direct; shared with Franka |
| `propcache` | 0.5.4 | Apache-2.0 | [upstream](https://github.com/aio-libs/propcache) | distribution: `LICENSE`, `NOTICE` | runtime transitive |
| `pycparser` | 3.0 | BSD-3-Clause | [upstream](https://github.com/eliben/pycparser) | distribution: `LICENSE` | runtime transitive; shared with Franka |
| `pyee` | 13.0.1 | MIT | [upstream](https://github.com/jfhbrook/pyee) | distribution: `LICENSE` | runtime transitive; shared with development |
| `pylibsrtp` | 1.0.0 | BSD-3-Clause | [upstream](https://github.com/aiortc/pylibsrtp) | distribution: `LICENSE` | runtime transitive |
| `pynvvideocodec` | 2.2.3 | MIT | [upstream](https://catalog.ngc.nvidia.com/orgs/nvidia/resources/pynvvideocodec) | distribution: `LICENSE.txt`, `NOTICES.txt` | runtime direct |
| `pyopenssl` | 26.4.0 | Apache-2.0 | [upstream](https://github.com/pyca/pyopenssl) | distribution: `LICENSE` | runtime transitive |
| `pyrealsense2` | 2.58.4.10922 | Apache-2.0 | [upstream](https://github.com/realsenseai/librealsense) | distribution: `LICENSE` | runtime direct; shared with Franka |
| `pyyaml` | 6.0.3 | MIT | [upstream](https://github.com/yaml/pyyaml) | distribution: `LICENSE` | runtime direct; shared with Franka and development |
| `pyzmq` | 27.2.0 | BSD-3-Clause | [upstream](https://github.com/zeromq/pyzmq) | [upstream `LICENSE.md`](https://github.com/zeromq/pyzmq/blob/main/LICENSE.md) | runtime direct; shared with Franka |
| `ruckig` | 0.19.4 | MIT | [upstream](https://github.com/pantor/ruckig) | [upstream `LICENSE`](https://github.com/pantor/ruckig/blob/main/LICENSE) | runtime direct; shared with Franka |
| `tensorrt-cu13-bindings` | 10.13.3.9.post1 | NVIDIA proprietary terms | [upstream](https://github.com/nvidia/tensorrt) | [TensorRT SLA](https://docs.nvidia.com/deeplearning/tensorrt/sla/index.html) | runtime direct |
| `tensorrt-cu13-libs` | 10.13.3.9.post1 | NVIDIA proprietary terms | [upstream](https://github.com/nvidia/tensorrt) | [TensorRT SLA](https://docs.nvidia.com/deeplearning/tensorrt/sla/index.html) | runtime direct |
| `trimesh` | 5.1.1 | MIT | [upstream](https://github.com/mikedh/trimesh) | distribution: `LICENSE.md` | runtime direct |
| `typing-extensions` | 4.16.0 | PSF-2.0 | [upstream](https://github.com/python/typing_extensions) | distribution: `LICENSE` | runtime transitive; shared with development |
| `websocket-client` | 1.9.2 | Apache-2.0 | [upstream](https://github.com/websocket-client/websocket-client) | distribution: `LICENSE` | runtime direct; shared with Franka |
| `websockets` | 17.2 | BSD-3-Clause | [upstream](https://github.com/python-websockets/websockets) | distribution: `LICENSE` | runtime direct |
| `yarl` | 1.25.1 | Apache-2.0 | [upstream](https://github.com/aio-libs/yarl) | distribution: `LICENSE`, `NOTICE` | runtime transitive |

## Optional Franka-only additions

These packages are selected only when the physical Franka profile is built. Build tools may be removed from the final container layer after producing the adapter.

| Component | Version | License / terms | Upstream source | Legal-file location | Distribution role |
| --- | ---: | --- | --- | --- | --- |
| `cmake` | 4.4.4 | Apache-2.0 AND BSD-3-Clause | [upstream](https://github.com/scikit-build/cmake-python-distributions) | [wrapper `LICENSE_Apache_20`](https://github.com/scikit-build/cmake-python-distributions/blob/main/LICENSE_Apache_20), [CMake `LICENSE.rst`](https://github.com/Kitware/CMake/blob/v4.4.4/LICENSE.rst) | optional Franka direct/build |
| `cmeel` | 0.61.0 | BSD-2-Clause | [upstream](https://github.com/cmake-wheel/cmeel) | distribution: `LICENSE` | optional Franka transitive |
| `cmeel-assimp` | 6.0.5 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/cmeel-assimp) | [Assimp `LICENSE`](https://github.com/assimp/assimp/blob/master/LICENSE) | optional Franka transitive |
| `cmeel-boost` | 1.90.0 | BSL-1.0 | [upstream](https://github.com/cmake-wheel/cmeel-boost) | [Boost Software License](https://www.boost.org/LICENSE_1_0.txt) | optional Franka transitive |
| `cmeel-console-bridge` | 1.0.2.3 | Zlib AND BSD-3-Clause | [upstream](https://github.com/cmake-wheel/cmeel-console-bridge) | [build recipe](https://github.com/cmake-wheel/cmeel-console-bridge/blob/main/pyproject.toml), [console_bridge `LICENSE`](https://github.com/ros/console_bridge/blob/master/LICENSE) | optional Franka transitive |
| `cmeel-octomap` | 1.10.0 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/cmeel-octomap) | [OctoMap `octomap/LICENSE.txt`](https://github.com/OctoMap/octomap/blob/devel/octomap/LICENSE.txt) | optional Franka transitive |
| `cmeel-qhull` | 8.0.2.1 | Qhull license | [upstream](https://github.com/cmake-wheel/cmeel-qhull) | distribution: `cmeel.prefix/share/doc/qhull/COPYING.txt` | optional Franka transitive |
| `cmeel-tinyxml2` | 11.0.0 | Zlib | [upstream](https://github.com/cmake-wheel/cmeel-tinyxml2) | [TinyXML-2 `LICENSE.txt`](https://github.com/leethomason/tinyxml2/blob/master/LICENSE.txt) | optional Franka direct/build |
| `cmeel-urdfdom` | 6.0.0 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/cmeel-urdfdom) | [urdfdom `LICENSE`](https://github.com/ros/urdfdom/blob/master/LICENSE) | optional Franka direct/build |
| `cmeel-zlib` | 1.3.2 | Zlib | [upstream](https://github.com/cmake-wheel/cmeel-zlib) | distribution: `cmeel.prefix/share/doc/zlib/zlib/LICENSE` | optional Franka transitive |
| `coal` | 3.0.3 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/coal) | distribution: `LICENSE` | optional Franka transitive |
| `eigenpy` | 3.13.0 | BSD-2-Clause | [upstream](https://github.com/cmake-wheel/eigenpy) | distribution: `LICENSE` | optional Franka transitive |
| `libcoal` | 3.0.3 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/libcoal) | distribution: `LICENSE` | optional Franka transitive |
| `libpinocchio` | 4.1.0 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/libpinocchio) | distribution: `LICENSE` | optional Franka transitive |
| `nanobind` | 3.1.0 | BSD-3-Clause | [upstream](https://github.com/wjakob/nanobind) | [upstream `LICENSE`](https://github.com/wjakob/nanobind/blob/master/LICENSE) | optional Franka direct/build |
| `ninja` | 1.13.2 | Apache-2.0 | [upstream](https://github.com/scikit-build/ninja-python-distributions) | distribution: `LICENSE_Apache_20` | optional Franka direct/build |
| `pin` | 4.1.0 | BSD-3-Clause | [upstream](https://github.com/cmake-wheel/pinocchio) | distribution: `LICENSE` | optional Franka direct/build |

## Development-only

These packages are not selected by release installation commands.

| Component | Version | License / terms | Upstream source | Legal-file location | Distribution role |
| --- | ---: | --- | --- | --- | --- |
| `cfgv` | 3.5.0 | MIT | [upstream](https://github.com/asottile/cfgv) | [upstream `LICENSE`](https://github.com/asottile/cfgv/blob/main/LICENSE) | development transitive |
| `colorama` | 0.4.6 | BSD-3-Clause | [upstream](https://github.com/tartley/colorama) | [upstream `LICENSE.txt`](https://github.com/tartley/colorama/blob/master/LICENSE.txt) | development transitive |
| `distlib` | 0.4.3 | PSF-2.0 | [upstream](https://github.com/pypa/distlib) | distribution: `LICENSE.txt` | development transitive |
| `execnet` | 2.1.2 | MIT | [upstream](https://github.com/pytest-dev/execnet) | distribution: `LICENSE` | development transitive |
| `filelock` | 4.0.7 | MIT | [upstream](https://github.com/tox-dev/py-filelock) | distribution: `LICENSE` | development transitive |
| `greenlet` | 3.5.6 | MIT AND PSF-2.0 | [upstream](https://github.com/python-greenlet/greenlet) | distribution: `LICENSE`, `LICENSE.PSF` | development transitive |
| `identify` | 2.6.20 | MIT | [upstream](https://github.com/pre-commit/identify) | distribution: `LICENSE` | development transitive |
| `iniconfig` | 2.3.0 | MIT | [upstream](https://github.com/pytest-dev/iniconfig) | distribution: `LICENSE` | development transitive |
| `nodeenv` | 1.11.0 | BSD-3-Clause | [upstream](https://github.com/ekalinin/nodeenv) | distribution: `LICENSE`, `AUTHORS` | development transitive |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | [upstream](https://github.com/pypa/packaging) | distribution: `LICENSE`, `LICENSE.APACHE`, `LICENSE.BSD` | development transitive |
| `platformdirs` | 4.12.2 | MIT | [upstream](https://github.com/tox-dev/platformdirs) | distribution: `LICENSE` | development transitive |
| `playwright` | 1.63.0 | Apache-2.0 | [upstream](https://github.com/microsoft/playwright-python) | [upstream `LICENSE`](https://github.com/microsoft/playwright-python/blob/main/LICENSE) | development direct |
| `pluggy` | 1.6.0 | MIT | [upstream](https://github.com/pytest-dev/pluggy) | distribution: `LICENSE` | development transitive |
| `pre-commit` | 4.6.2 | MIT | [upstream](https://github.com/pre-commit/pre-commit) | [upstream `LICENSE`](https://github.com/pre-commit/pre-commit/blob/main/LICENSE) | development direct |
| `pygments` | 2.21.0 | BSD-2-Clause | [upstream](https://github.com/pygments/pygments) | distribution: `AUTHORS`, `LICENSE` | development transitive |
| `pytest` | 9.1.1 | MIT | [upstream](https://github.com/pytest-dev/pytest) | distribution: `LICENSE` | development direct |
| `pytest-asyncio` | 1.4.0 | Apache-2.0 | [upstream](https://github.com/pytest-dev/pytest-asyncio) | distribution: `LICENSE` | development direct |
| `pytest-xdist` | 3.8.0 | MIT | [upstream](https://github.com/pytest-dev/pytest-xdist) | distribution: `LICENSE` | development direct |
| `python-discovery` | 1.6.1 | MIT | [upstream](https://github.com/tox-dev/python-discovery) | distribution: `LICENSE` | development transitive |
| `ruff` | 0.17.0 | MIT | [upstream](https://github.com/astral-sh/ruff) | distribution: `LICENSE` | development direct |
| `virtualenv` | 21.14.1 | MIT | [upstream](https://github.com/pypa/virtualenv) | distribution: `LICENSE`, `THIRD-PARTY-NOTICES.md` | development transitive |
