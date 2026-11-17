#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build NVIDIA's pinned source with two additions to its NVENC binding.

An explicit output-delay argument, and priority areas: NVIDIA's policy-map converter
(native/cae) turns a coarse map of policy IDs into the per-block delta-QP map that the
public NVENC API accepts with each frame.

Run with the application's Python; the built wheel is installed into that interpreter.
Requires uv, a C++ compiler, and the CUDA Toolkit. Downloads and build products
stay under build/codec. NVIDIA's source and license notices are preserved there.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

from dependencies import ROOT, run

VERSION = "2.2.3+telesurgery.2"
ARCHIVE = "PyNvVideoCodec_2.2.3.zip"
URL = (
    f"https://api.ngc.nvidia.com/v2/resources/nvidia/pynvvideocodec/versions/v2.2.3/files/{ARCHIVE}"
)
SHA256 = "29f7c0694d683266c563aca9a4f8e979ba0c5dce8f0ccc1efe500073e0948be0"
# NVIDIA's policy-map to delta-QP converter, compiled into the binding.
CONVERTER = ROOT / "native/cae"
CONVERTER_FILES = ("PolicyMapToDeltaQp.h", "PolicyMapToDeltaQp.cu", "PolicyToDeltaQpProfile.cpp")


def replace_once(path, old, new, count=1):
    text = path.read_text()
    if text.count(old) != count:
        raise RuntimeError(f"source patch does not match {path}: {old!r}")
    path.write_text(text.replace(old, new))


def patch(source):
    encoder = source / "src/PyNvVideoCodec/src/PyNvEncoder.cpp"
    replace_once(
        encoder,
        "        NV_ENC_BUFFER_FORMAT eBufferFormat;",
        """        // Default is unchanged for other users of this locally built library.
        int extraOutputDelay = 3;
        if (options.count("extra_output_delay")) {
            extraOutputDelay = std::stoi(options.at("extra_output_delay"));
            if (extraOutputDelay < 0 || extraOutputDelay > 16) {
                throw std::invalid_argument("extra_output_delay must be in [0, 16]");
            }
            options.erase("extra_output_delay");
        }
        NV_ENC_BUFFER_FORMAT eBufferFormat;""",
    )
    replace_once(
        encoder,
        "                3, false, false, useIvfContainer, true);",
        "                extraOutputDelay, false, false, useIvfContainer, true);",
    )
    replace_once(
        encoder,
        "(cudacontext, cudastream, _width, _height, eBufferFormat);",
        "(cudacontext, cudastream, _width, _height, eBufferFormat, extraOutputDelay);",
    )
    replace_once(
        source / "src/PyNvVideoCodec/src/PyNvVideoCodec.cpp",
        "PYBIND11_MODULE(_PyNvVideoCodec, m)\n{",
        'PYBIND11_MODULE(_PyNvVideoCodec, m)\n{\n    m.attr("telesurgery_low_latency_patch") = 1;',
    )
    # Upstream's pybind11 2.10 predates Python 3.12 support.
    cmake = source / "src/PyNvVideoCodec/CMakeLists.txt"
    replace_once(
        cmake,
        "https://github.com/pybind/pybind11/archive/v2.10.0.tar.gz",
        "https://codeload.github.com/pybind/pybind11/tar.gz/refs/tags/v2.13.6",
    )
    replace_once(
        cmake,
        "eacf582fa8f696227988d08cfc46121770823839fe9e301a20fbce67e7cd70ec",
        "e08cb87f4773da97fa7b5f035de8763abc656d87d5773e62f6da0587d1f0ec20",
    )
    for filename in ("setup.py", "pyproject.toml", "src/PyNvVideoCodec/__init__.py"):
        replace_once(source / filename, '"2.2.3"', f'"{VERSION}"')
    patch_policy_map(source)


POLICY_MAP_STATE = """    // telesurgery: policy maps. Null without the "qp_policy_map" option.
    struct PolicyMapState {
        nvcodec::cae::PolicyMapToDeltaQpConverter converter;
        CUcontext context = nullptr;
        CUstream stream = nullptr;
        CUevent policyReady = nullptr, deltaReady = nullptr;
        CUdeviceptr policy = 0, delta = 0;
        size_t policyBytes = 0;
        nvcodec::cae::Extent2D frame{}, blocks{}, block{};
        std::vector<int8_t> packed;  // what NV_ENC_PIC_PARAMS::qpDeltaMap points at
        ~PolicyMapState();
    };
    std::shared_ptr<PolicyMapState> m_policyMap;
    void InitPolicyMap();
"""

POLICY_MAP_METHODS = r"""namespace nvcodec { namespace cae {
// Defined in PolicyToDeltaQpProfile.cpp.
[[nodiscard]] Status ResolvePolicyToDeltaQpProfileForNvencGuid(
    GUID encodeGuid, PolicyToDeltaQpProfile* out) noexcept;
} }

PyNvEncoder::PolicyMapState::~PolicyMapState()
{
    if (!context || cuCtxPushCurrent(context) != CUDA_SUCCESS) {
        return;
    }
    if (stream) cuStreamSynchronize(stream);
    if (policy) cuMemFree(policy);
    if (delta) cuMemFree(delta);
    if (policyReady) cuEventDestroy(policyReady);
    if (deltaReady) cuEventDestroy(deltaReady);
    if (stream) cuStreamDestroy(stream);
    cuCtxPopCurrent(NULL);
}

void PyNvEncoder::InitPolicyMap()
{
    using namespace nvcodec::cae;
    auto state = std::make_shared<PolicyMapState>();
    PolicyToDeltaQpProfile profile{};
    Status status = ResolvePolicyToDeltaQpProfileForNvencGuid(m_encodeGUID, &profile);
    if (!status.IsOk()) {
        PYNVVC_THROW_ERROR_UNSUPPORTED(status.message, NV_ENC_ERR_UNSUPPORTED_PARAM);
    }
    CUDA_DRVAPI_CALL(cuCtxPushCurrent(m_CUcontext));
    try {
        state->context = m_CUcontext;
        CUDA_DRVAPI_CALL(cuStreamCreate(&state->stream, CU_STREAM_NON_BLOCKING));
        status = PolicyMapToDeltaQpConverter::Create(state->stream, profile, &state->converter);
        if (!status.IsOk()) {
            PYNVVC_THROW_ERROR(status.message, NV_ENC_ERR_GENERIC);
        }
        state->block = profile.DeltaQpBlockSizePixels();
        state->frame = {static_cast<uint32_t>(m_width), static_cast<uint32_t>(m_height)};
        state->blocks = {(state->frame.width + state->block.width - 1) / state->block.width,
                         (state->frame.height + state->block.height - 1) / state->block.height};
        // All zeros is the neutral map: it encodes exactly as no map.
        state->packed.assign(size_t(state->blocks.width) * state->blocks.height, 0);
        CUDA_DRVAPI_CALL(cuMemAlloc(&state->delta, state->packed.size()));
        CUDA_DRVAPI_CALL(cuMemsetD8(state->delta, 0, state->packed.size()));
        CUDA_DRVAPI_CALL(cuEventCreate(&state->policyReady, CU_EVENT_DISABLE_TIMING));
        CUDA_DRVAPI_CALL(cuEventCreate(&state->deltaReady, CU_EVENT_DISABLE_TIMING));
    } catch (...) {
        cuCtxPopCurrent(NULL);
        throw;
    }
    CUDA_DRVAPI_CALL(cuCtxPopCurrent(NULL));
    m_policyMap = state;
}

void PyNvEncoder::SetPolicyMap(py::object policy)
{
    using namespace nvcodec::cae;
    if (!m_policyMap) {
        PYNVVC_THROW_ERROR_UNSUPPORTED(
            "the encoder was created without qp_policy_map", NV_ENC_ERR_INVALID_CALL);
    }
    PolicyMapState& state = *m_policyMap;
    if (policy.is_none()) {
        std::fill(state.packed.begin(), state.packed.end(), 0);
        return;
    }
    auto map = py::array_t<uint8_t, py::array::c_style | py::array::forcecast>::ensure(policy);
    if (!map || map.ndim() != 2 || map.shape(0) < 1 || map.shape(1) < 1) {
        PYNVVC_THROW_ERROR("the policy map must be a 2-D uint8 array", NV_ENC_ERR_INVALID_PARAM);
    }
    const uint32_t height = static_cast<uint32_t>(map.shape(0));
    const uint32_t width = static_cast<uint32_t>(map.shape(1));
    const size_t bytes = size_t(width) * height;
    CUDA_DRVAPI_CALL(cuCtxPushCurrent(state.context));
    try {
        if (bytes > state.policyBytes) {
            if (state.policy) {
                CUDA_DRVAPI_CALL(cuMemFree(state.policy));
                state.policy = 0;
                state.policyBytes = 0;
            }
            CUDA_DRVAPI_CALL(cuMemAlloc(&state.policy, bytes));
            state.policyBytes = bytes;
        }
        // Everything is ordered on one stream and finished before this call returns, so the
        // encoder never reads a half-written map.
        CUDA_DRVAPI_CALL(cuMemcpyHtoDAsync(state.policy, map.data(), bytes, state.stream));
        CUDA_DRVAPI_CALL(cuEventRecord(state.policyReady, state.stream));
        PolicyMapView source{};
        source.devicePtr = state.policy;
        source.rowPitchBytes = width;
        source.capacityBytes = bytes;
        source.mapSizeCells = {width, height};
        source.spatialMapping = ScaleToFrameMapping{};
        DeltaQpMapView target{};
        target.devicePtr = state.delta;
        target.rowPitchBytes = state.blocks.width;  // tight pitch: NVENC's packed layout
        target.capacityBytes = state.packed.size();
        target.frameSizePixels = state.frame;
        target.mapSizeBlocks = state.blocks;
        target.blockSizePixels = state.block;
        const Status status =
            state.converter.ConvertAsync(source, target, state.policyReady, state.deltaReady);
        if (!status.IsOk()) {
            cuStreamSynchronize(state.stream);
            PYNVVC_THROW_ERROR(status.message, NV_ENC_ERR_GENERIC);
        }
        // Convert into a scratch copy so a failed download leaves the active map intact.
        std::vector<int8_t> packed(state.packed.size());
        CUDA_DRVAPI_CALL(
            cuMemcpyDtoHAsync(packed.data(), state.delta, packed.size(), state.stream));
        CUDA_DRVAPI_CALL(cuStreamSynchronize(state.stream));
        state.packed.swap(packed);
    } catch (...) {
        cuCtxPopCurrent(NULL);
        throw;
    }
    CUDA_DRVAPI_CALL(cuCtxPopCurrent(NULL));
}

"""


def patch_policy_map(source):
    """Priority areas: a "qp_policy_map" option, SetPolicyMap() and SupportsPolicyMap().

    The encoder stays the binding's own NvEncoderCuda. The option arms NVENC's delta-QP
    map mode for the session (a zero map encodes exactly as no map). SetPolicyMap()
    converts a uint8 map of policy IDs once per change with NVIDIA's converter, and every
    Encode() attaches the result through the public NV_ENC_PIC_PARAMS::qpDeltaMap field.
    """
    utils = source / "src/VideoCodecSDKUtils"
    converter = utils / "helper_classes/Cae"
    converter.mkdir()
    for name in CONVERTER_FILES:
        shutil.copyfile(CONVERTER / name, converter / name)
    # PolicyToDeltaQpProfile.cpp includes <nvEncodeAPI.h> for the codec GUIDs only; the
    # binding ships that header once per supported API version.
    (converter / "nvEncodeAPI.h").write_text(
        '#pragma once\n#include "configNvEncVer.h"\n#ifdef NVENC_VER_13_0\n'
        '#include "nvEncodeAPI_130.h"\n#else\n#include "nvEncodeAPI_121.h"\n#endif\n'
    )
    cmake = utils / "CMakeLists.txt"
    replace_once(
        cmake,
        " helper_classes/NvCodec/NvEncoder/NvEncoder_121.cpp\n)",
        " helper_classes/NvCodec/NvEncoder/NvEncoder_121.cpp\n"
        " helper_classes/Cae/PolicyToDeltaQpProfile.cpp\n)",
    )
    replace_once(
        cmake,
        "set(CODEC_CUDA_UTILS\n helper_classes/Utils/ColorSpace.cu\n)",
        "set(CODEC_CUDA_UTILS\n helper_classes/Utils/ColorSpace.cu\n"
        " helper_classes/Cae/PolicyMapToDeltaQp.cu\n)\n"
        "set(CMAKE_CUDA_STANDARD 17)\nset(CMAKE_CUDA_STANDARD_REQUIRED ON)",
    )
    # Both the versioned targets and the unsuffixed one need the include directory.
    for indent in ("        ", "            "):
        replace_once(
            cmake,
            f"\n{indent}helper_classes/NvCodec\n{indent}helper_classes/Utils\n",
            f"\n{indent}helper_classes/NvCodec\n{indent}helper_classes/Utils\n"
            f"{indent}helper_classes/Cae\n",
        )

    header = source / "src/PyNvVideoCodec/inc/PyNvEncoder.hpp"
    replace_once(
        header,
        '#include "NvEncoderCuda.h"',
        '#include "NvEncoderCuda.h"\n#include "PolicyMapToDeltaQp.h"',
    )
    replace_once(
        header,
        "protected:\n    std::unique_ptr<NvEncoderCuda> m_encoder;\n",
        POLICY_MAP_STATE + "protected:\n    std::unique_ptr<NvEncoderCuda> m_encoder;\n",
    )
    replace_once(
        header,
        "    bool Reconfigure(structEncodeReconfigureParams reconfigureParams);",
        "    bool Reconfigure(structEncodeReconfigureParams reconfigureParams);\n"
        "    void SetPolicyMap(py::object policy);\n"
        "    bool SupportsPolicyMap() const { return static_cast<bool>(m_policyMap); }",
    )

    encoder = source / "src/PyNvVideoCodec/src/PyNvEncoder.cpp"
    replace_once(
        encoder,
        "        int extraOutputDelay = 3;",
        """        bool policyMaps = false;
        if (options.count("qp_policy_map")) {
            policyMaps = options.at("qp_policy_map") != "0";
            options.erase("qp_policy_map");
        }
        int extraOutputDelay = 3;""",
    )
    replace_once(
        encoder,
        "        m_encoder->CreateEncoder(&params);\n",
        """        if (policyMaps) {
            const auto& rc = params.encodeConfig->rcParams;
            if (rc.enableAQ || rc.enableTemporalAQ || rc.enableLookahead ||
                params.encodeConfig->frameIntervalP != 1) {
                PYNVVC_THROW_ERROR_UNSUPPORTED(
                    "qp_policy_map cannot be combined with AQ, temporal AQ, lookahead or B-frames",
                    NV_ENC_ERR_INVALID_PARAM);
            }
            // A zero map encodes exactly as no map, so the mode is armed for the whole session.
            params.encodeConfig->rcParams.qpMapMode = NV_ENC_QP_MAP_DELTA;
        }
        m_encoder->CreateEncoder(&params);
""",
    )
    replace_once(
        encoder,
        "        m_bUseCPUInutBuffer = bUseCPUInutBuffer;\n        m_mapPtr.clear();\n    }\n"
        "    catch (const PyNvVCException<PyNvVCGenericError>& e) {",
        "        m_bUseCPUInutBuffer = bUseCPUInutBuffer;\n        m_mapPtr.clear();\n"
        "        if (policyMaps) {\n            InitPolicyMap();\n        }\n    }\n"
        "    catch (const PyNvVCException<PyNvVCGenericError>& e) {",
    )
    attach = (
        "    if (m_policyMap) {{\n        {pic}.qpDeltaMap = m_policyMap->packed.data();\n"
        "        {pic}.qpDeltaMapSize = static_cast<uint32_t>(m_policyMap->packed.size());\n"
        "    }}\n    m_encoder->EncodeFrame(vvByte, &{pic});"
    )
    for pic, count in (("picParam", 3), ("picParams", 1)):
        replace_once(
            encoder,
            f"    m_encoder->EncodeFrame(vvByte, &{pic});",
            attach.format(pic=pic),
            count=count,
        )
    replace_once(
        encoder,
        "PyNvEncoder::~PyNvEncoder()\n{",
        POLICY_MAP_METHODS + "PyNvEncoder::~PyNvEncoder()\n{",
    )
    replace_once(
        encoder,
        """        .def(
             "Encode",
             [](std::shared_ptr<PyNvEncoder>& self, const py::object& frame)
             {
                return self->Encode(frame);
             }, R"pbdoc(""",
        """        .def("SetPolicyMap", &PyNvEncoder::SetPolicyMap,
             "Set a 2-D uint8 map of policy IDs spanning the frame, or None to clear it.")
        .def("SupportsPolicyMap", &PyNvEncoder::SupportsPolicyMap)
        .def(
             "Encode",
             [](std::shared_ptr<PyNvEncoder>& self, const py::object& frame)
             {
                return self->Encode(frame);
             }, R"pbdoc(""",
    )
    replace_once(
        source / "src/PyNvVideoCodec/src/PyNvVideoCodec.cpp",
        'm.attr("telesurgery_low_latency_patch") = 1;',
        'm.attr("telesurgery_low_latency_patch") = 1;\n'
        '    m.attr("telesurgery_policy_map_patch") = 1;',
    )


def build_wheel(args):
    build = ROOT / "build/codec"
    build.mkdir(parents=True, exist_ok=True)
    stamp = build / "build-options.txt"
    # The converter sources are part of the build: editing one rebuilds the wheel.
    converter = hashlib.sha256(
        b"".join((CONVERTER / name).read_bytes() for name in CONVERTER_FILES)
    ).hexdigest()[:16]
    options = (
        f"{VERSION}:{sys.version_info[:2]}:{os.uname().machine}:{args.cuda_architectures}"
        f":{converter}"
    )
    candidates = list(
        (build / "wheels").glob(
            f"pynvvideocodec-{VERSION}-cp{sys.version_info.major}{sys.version_info.minor}-*.whl"
        )
    )
    if candidates and stamp.exists() and stamp.read_text() == options:
        wheel = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        return wheel
    archive = build / ARCHIVE
    if not archive.exists():
        print(f"Downloading {URL}", flush=True)
        temporary = archive.with_suffix(".download")
        # Fixed HTTPS URL, SHA256 verified below.
        urllib.request.urlretrieve(URL, temporary)  # nosec B310
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError(f"SHA256 mismatch: remove {archive} and retry")
    # Re-extract a verified source so patches never stack across runs.
    source = build / "source"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(source)
    source = source / "PyNvVideoCodec_2.2.3"
    patch(source)
    wheels = build / "wheels"
    env = os.environ.copy()
    env["CMAKE_ARGS"] = (
        env.get("CMAKE_ARGS", "") + f" -DCMAKE_CUDA_ARCHITECTURES={args.cuda_architectures}"
    )
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    run("uv", "build", "--python", sys.executable, source, "--wheel", "--out-dir", wheels, env=env)
    candidates = list(
        wheels.glob(
            f"pynvvideocodec-{VERSION}-cp{sys.version_info.major}{sys.version_info.minor}-*.whl"
        )
    )
    if not candidates:
        raise RuntimeError(f"Codec build did not produce a wheel for {sys.executable}")
    wheel = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    stamp.write_text(options)
    print(f"Built {wheel}\nSHA256: {hashlib.sha256(wheel.read_bytes()).hexdigest()}", flush=True)
    return wheel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuda-architectures", default=os.environ.get("CUDAARCHS", "native"))
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    # The version does not change when only the converter sources do: always replace it.
    run(
        "uv",
        "pip",
        "install",
        "--reinstall-package",
        "pynvvideocodec",
        "--python",
        sys.executable,
        build_wheel(args),
    )


if __name__ == "__main__":
    main()
