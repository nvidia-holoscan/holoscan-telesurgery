# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""nvJPEG CUDA processing through nvImageCodec, with no software codec fallback."""

import os
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory


def _load_library():
    extensions = distribution("nvidia-nvimgcodec-cu13").locate_file("nvidia/nvimgcodec/extensions")
    extension = next(Path(extensions).glob("libnvjpeg_ext.so*"), None)
    if extension is None:
        raise ImportError("nvImageCodec's nvJPEG extension is missing")
    # The Python binding discovers plugins once, during import. Load only nvJPEG;
    # unrelated TIFF/JPEG 2000 plugins require libraries our streams do not use.
    with TemporaryDirectory(prefix="telesurgery-nvjpeg-") as directory:
        Path(directory, extension.name).symlink_to(extension.resolve())
        previous = os.environ.get("NVIMGCODEC_EXTENSIONS_PATH")
        os.environ["NVIMGCODEC_EXTENSIONS_PATH"] = directory
        try:
            from nvidia import nvimgcodec

            return nvimgcodec
        finally:
            if previous is None:
                os.environ.pop("NVIMGCODEC_EXTENSIONS_PATH", None)
            else:
                os.environ["NVIMGCODEC_EXTENSIONS_PATH"] = previous


# This module is imported lazily for JPEG; Python's import lock serializes setup.
_library = _load_library()


class JpegCodec:
    def __init__(self, config, *, encode, stream):
        nic = _library

        self.library, self.stream, self.quality = nic, stream, config.jpeg_quality
        # Use dedicated hardware where available (e.g. Thor), otherwise NVIDIA's
        # CUDA hybrid backend. CPU_ONLY would permit an OpenCV/libjpeg fallback.
        factory = nic.Encoder if encode else nic.Decoder
        self.backend = factory(
            device_id=config.codec_gpu,
            max_num_cpu_threads=1,
            backends=[
                nic.Backend(nic.BackendKind.HW_GPU_ONLY),
                nic.Backend(nic.BackendKind.HYBRID_CPU_GPU),
            ],
        )

    def encode(self, pixels):
        nic = self.library
        result = self.backend.encode(
            nic.as_image(pixels, cuda_stream=self.stream, sample_format=nic.SampleFormat.I_BGR),
            "jpeg",
            cuda_stream=self.stream,
            params=nic.EncodeParams(
                quality_type=nic.QualityType.QUALITY, quality_value=self.quality
            ),
        )
        if result is None:
            raise RuntimeError("nvJPEG encoding failed; software fallback is disabled")
        return bytes(result)

    def decode(self, data):
        nic = self.library
        result = self.backend.decode(
            nic.CodeStream(data),
            cuda_stream=self.stream,
            params=nic.DecodeParams(
                apply_exif_orientation=False, sample_format=nic.SampleFormat.I_RGB
            ),
        )
        if result is None:
            raise ValueError("nvJPEG could not decode this frame on the GPU")
        return result

    def close(self):
        self.backend.__exit__(None, None, None)
