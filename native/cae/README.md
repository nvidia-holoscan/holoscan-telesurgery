# Policy-map converter for priority areas

These three files are NVIDIA's content-adaptive encoding (CAE) converter from the Video Codec SDK
CAE sample, provided by NVIDIA under Apache-2.0:

- `PolicyMapToDeltaQp.h`
- `PolicyMapToDeltaQp.cu`
- `PolicyToDeltaQpProfile.cpp`

The converter turns a coarse map of policy IDs (neutral, protect, deprioritize) into the per-block
delta-QP map that the public NVENC API accepts with each frame (`NV_ENC_QP_MAP_DELTA`,
`NV_ENC_PIC_PARAMS::qpDeltaMap`). It needs only the CUDA Toolkit and the public NVENC header.

`scripts/builders/codecs.py` compiles them into the locally built `PyNvVideoCodec` binding, which
then offers `SetPolicyMap()`. `telesurgery_core.video.codecs.GpuCodec.set_region()` is the only
caller. The files are not built or imported anywhere else.

Changes from NVIDIA's sample: the licence header and Unix line endings. The code is otherwise
unmodified and is excluded from `clang-format` so that it stays comparable with its source. Comments
in the files mention `NvEncoderCudaDeltaQpMap`, the sample's encoder wrapper; it is not used here,
because the binding's own encoder passes the converted map to NVENC.
