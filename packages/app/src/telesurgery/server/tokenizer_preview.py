# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One GPU tokenizer-to-H.264 preview converter per subscribed camera."""

from dataclasses import asdict, replace

from telesurgery_core.diagnostics.trace import mark
from telesurgery_core.video.codecs import create_codec
from telesurgery_core.video.config import Config
from telesurgery_core.video.depth import split
from telesurgery_core.video.model import Frame


class TokenizerPreview:
    def __init__(self):
        self.decoder = self.encoder = None
        self.key = None

    def convert(self, header, data, trace):
        key = header.codec_profile, header.width, header.height
        if key != self.key:
            self.close()
            config = Config(width=header.width, height=header.height, codec=header.codec)
            self.decoder = create_codec(config, encode=False)
            self.encoder = create_codec(replace(config, codec="h264"), encode=True)
            self.key = key
        color, depth = split(header, data)
        frame = self.decoder.decode(header, color, on_device=True)
        trace = mark(trace, "decode_ms")
        # GPU decoding returns RGB; encoders accept BGR. Keep measured depth bytes
        # and the original capture timestamp through preview conversion.
        preview_header = replace(header, codec="h264", codec_profile="", depth_bytes=0)
        _, encoded = self.encoder.encode(Frame(preview_header, frame.image[..., ::-1]))
        trace = mark(trace, "preview_encode_ms")
        return asdict(replace(preview_header, depth_bytes=len(depth))), encoded + depth, trace

    def close(self):
        for codec in (self.decoder, self.encoder):
            if codec is not None:
                codec.close()
        self.decoder = self.encoder = None
        self.key = None
