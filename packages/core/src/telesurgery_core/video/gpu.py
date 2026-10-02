# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small fused CUDA conversions; no host staging or intermediate full-size planes."""

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _nv12_kernel():
    import cupy as cp

    return cp.RawKernel(
        r"""
extern "C" __global__ void bgr_nv12(
    const unsigned char* src, unsigned char* dst, int w, int h,
    long long row, long long col, long long chan, int hd) {
  int i = blockDim.x * blockIdx.x + threadIdx.x;
  if (i >= w * h / 4) return;
  int x = (i % (w / 2)) * 2, y = (i / (w / 2)) * 2;
  float us = 0.f, vs = 0.f;
  for (int dy = 0; dy < 2; ++dy) {
    for (int dx = 0; dx < 2; ++dx) {
      const unsigned char* p = src + (y + dy) * row + (x + dx) * col;
      float b = p[0], g = p[chan], r = p[chan * 2];
      float l = hd ? 16.f + .183f*r + .614f*g + .062f*b
                   : 16.f + .257f*r + .504f*g + .098f*b;
      us += hd ? 128.f - .101f*r - .339f*g + .439f*b
               : 128.f - .148f*r - .291f*g + .439f*b;
      vs += hd ? 128.f + .439f*r - .399f*g - .040f*b
               : 128.f + .439f*r - .368f*g - .071f*b;
      dst[(y + dy)*w + x + dx] = __float2int_rn(fminf(235.f, fmaxf(16.f, l)));
    }
  }
  dst[w*h + (y/2)*w + x] = __float2int_rn(fminf(240.f, fmaxf(16.f, us*.25f)));
  dst[w*h + (y/2)*w + x + 1] = __float2int_rn(fminf(240.f, fmaxf(16.f, vs*.25f)));
}
""",
        "bgr_nv12",
        options=("--fmad=false",),
    )


def nv12(cp, bgr):
    """One CUDA launch converts four BGR pixels and their averaged chroma per thread."""
    height, width = bgr.shape[:2]
    if width % 2 or height % 2:
        raise ValueError("NV12 requires even image dimensions")
    out = cp.empty((height * 3 // 2, width), dtype=cp.uint8)
    count = width * height // 4
    _nv12_kernel()(
        ((count + 255) // 256,),
        (256,),
        (
            bgr,
            out,
            np.int32(width),
            np.int32(height),
            *(np.int64(s) for s in bgr.strides),
            np.int32(width > 720 or height > 576),
        ),
    )
    return out


@lru_cache(maxsize=1)
def _bayer_kernel():
    import cupy as cp

    return cp.RawKernel(
        r"""
__device__ int color(int x, int y, int pattern) {
  // Color indices are BGR; patterns follow NPP/HSB's public enum.
  const int table[16] = {0,1,1,2, 2,1,1,0, 1,0,2,1, 1,2,0,1};
  return table[pattern*4 + (y&1)*2 + (x&1)];
}
extern "C" __global__ void bayer_bgr(const unsigned short* src,
    unsigned char* dst, int w, int h, int pattern) {
  int i = blockDim.x*blockIdx.x + threadIdx.x;
  if (i >= w*h) return;
  int x = i%w, y = i/w;
  for (int c = 0; c < 3; ++c) {
    unsigned int sum = 0, count = 0;
    if (color(x,y,pattern) == c) { sum = src[i]; count = 1; }
    else for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
      int nx = x+dx, ny = y+dy;
      if (nx>=0 && nx<w && ny>=0 && ny<h && color(nx,ny,pattern)==c) {
        sum += src[ny*w+nx]; ++count;
      }
    }
    float linear = float(sum) / (float(count) * 65535.f);
    float display = linear <= .0031308f ? 12.92f * linear
                                      : 1.055f * powf(linear, 1.f/2.4f) - .055f;
    dst[i*3+c] = __float2int_rn(255.f * fminf(1.f, fmaxf(0.f, display)));
  }
}
""",
        "bayer_bgr",
    )


def demosaic(cp, bayer, pattern):
    """Linear Bayer16 to display BGR8: bilinear demosaic and sRGB transfer in one launch."""
    if pattern not in range(4) or bayer.dtype != cp.uint16 or not bayer.flags.c_contiguous:
        raise ValueError("demosaic expects contiguous Bayer16 and an NPP pattern in 0..3")
    height, width = bayer.shape[:2]
    if width < 2 or height < 2 or bayer.size != width * height:
        raise ValueError("demosaic expects one Bayer plane at least 2x2")
    out = cp.empty((height, width, 3), dtype=cp.uint8)
    _bayer_kernel()(
        ((width * height + 255) // 256,),
        (256,),
        (bayer, out, np.int32(width), np.int32(height), np.int32(pattern)),
    )
    return out
