# Priority area: what it changes

A priority area is a region a surgeon draws on a camera view. The patient-side encoder then spends more of the picture's quality inside it. Pixels are not altered and the stream decodes like any other. This page records what the encoder does with an area, measured through the product's own encoder (`telesurgery_core.video.codecs.GpuCodec`) with its default settings.

## Summary

| Rate control | Inside the area | Outside the area | Bitrate |
| --- | --- | --- | --- |
| Bitrate limit (default), freehand area of 5% of the picture | +2.2 to +2.7 dB | −0.1 to −0.4 dB | −7% to −1% |
| Bitrate limit (default), area of a quarter of the picture | +0.8 to +1.6 dB | −0.6 to −1.6 dB | −4% to +13%, under the limit |
| Fixed quality (QP 24), freehand area of 5% | +1.3 to +1.7 dB | unchanged | +2% to +3% |
| Fixed quality (QP 24), area of a quarter | +1.5 to +1.9 dB | unchanged | +23% to +48% |

- **With a bitrate limit, quality moves; bandwidth does not grow.** Rate control aims at the same limit with and without an area, so what the area gains the rest of the picture gives up. A small area gains most and costs the rest least. The limit is a target, not a hard cap: at 2 Mbit/s the endoscopy clip needs 2.6–2.7 Mbit/s without an area and 2.5 with one.
- **With fixed quality, the rest of the picture keeps the chosen QP** and the area is encoded more finely, which costs bandwidth in proportion to its size.
- **No keyframe** is produced when an area is set, moved or cleared, and frame sizes are as predictable as before: the largest predicted frame was 0.88–1.18 times its share of the limit with an area and 0.96–1.18 times without.
- **Encode time is unchanged:** 2.1–2.6 ms per FHD frame with and without an area (median difference 0.02 ms). Applying a new area took about 0.5 ms (2.5 ms at most in 108 changes at FHD and 4K) and happens once per change, not per frame.
- **Without an area the stream is byte-identical** to one from an encoder that cannot take areas.
- **Live latency is unchanged:** camera-to-viewer P50 and P99 in nine live results from four cameras match `main` without an area and are no higher with one ([live streams](#live-streams)).

## Results

FHD, 30 FPS, 300 frames per run, standard strength. Each cell is without an area → with an area; quality is luma PSNR against the source, scored over the same pixels in both runs.

| Clip | Rate control | Area | CC | Mbit/s | Inside (dB) | Outside (dB) |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.264 | 8.1 → 8.0 | 42.4 → **45.1** (+2.7) | 43.6 → 43.3 (−0.4) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.265 | 8.2 → 8.1 | 43.2 → **45.7** (+2.6) | 44.3 → 43.9 (−0.4) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.264 | 8.1 → 7.9 | 41.5 → **43.1** (+1.6) | 44.5 → 43.0 (−1.6) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.265 | 8.2 → 7.9 | 42.1 → **43.7** (+1.6) | 45.2 → 43.7 (−1.5) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.264 | 2.7 → 2.5 | 38.3 → **41.5** (+3.2) | 38.8 → 38.1 (−0.7) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.265 | 2.6 → 2.5 | 39.0 → **42.1** (+3.1) | 39.6 → 39.0 (−0.6) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.264 | 2.7 → 2.5 | 36.9 → **38.6** (+1.8) | 39.7 → 37.2 (−2.5) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.265 | 2.6 → 2.5 | 37.6 → **39.3** (+1.8) | 40.5 → 38.2 (−2.4) |
| Endoscopy | Fixed quality, QP 24 | Freehand, 5% | H.264 | 7.1 → 7.4 | 43.4 → **45.0** (+1.6) | 43.9 → 43.9 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Freehand, 5% | H.265 | 6.6 → 6.8 | 43.7 → **45.2** (+1.6) | 44.1 → 44.1 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Quarter of the picture | H.264 | 7.1 → 8.8 | 42.1 → **44.0** (+1.9) | 44.7 → 44.7 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Quarter of the picture | H.265 | 6.6 → 8.1 | 42.4 → **44.3** (+1.9) | 44.9 → 44.9 (0.0) |
| Simulation | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.264 | 5.8 → 5.4 | 49.0 → **51.5** (+2.5) | 49.3 → 49.2 (−0.1) |
| Simulation | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.265 | 6.2 → 5.8 | 48.8 → **51.0** (+2.2) | 49.1 → 49.0 (−0.1) |
| Simulation | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.264 | 5.8 → 6.6 | 48.6 → **49.6** (+1.1) | 49.6 → 49.0 (−0.6) |
| Simulation | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.265 | 6.2 → 6.2 | 48.4 → **49.2** (+0.8) | 49.4 → 48.6 (−0.7) |
| Simulation | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.264 | 1.7 → 1.7 | 45.7 → **48.4** (+2.7) | 47.1 → 46.8 (−0.2) |
| Simulation | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.265 | 1.7 → 1.7 | 46.0 → **48.1** (+2.1) | 47.1 → 46.9 (−0.2) |
| Simulation | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.264 | 1.7 → 1.9 | 45.1 → **46.2** (+1.0) | 47.8 → 46.7 (−1.1) |
| Simulation | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.265 | 1.7 → 1.7 | 45.3 → **46.0** (+0.7) | 47.8 → 46.7 (−1.1) |
| Simulation | Fixed quality, QP 24 | Freehand, 5% | H.264 | 0.7 → 0.7 | 43.2 → **44.9** (+1.7) | 45.0 → 45.0 (0.0) |
| Simulation | Fixed quality, QP 24 | Freehand, 5% | H.265 | 0.7 → 0.8 | 43.9 → **45.2** (+1.3) | 45.6 → 45.6 (0.0) |
| Simulation | Fixed quality, QP 24 | Quarter of the picture | H.264 | 0.7 → 1.0 | 43.0 → **44.8** (+1.7) | 45.8 → 45.8 (0.0) |
| Simulation | Fixed quality, QP 24 | Quarter of the picture | H.265 | 0.7 → 1.1 | 43.5 → **45.0** (+1.5) | 46.4 → 46.4 (0.0) |

## Strength

The default is `standard`. The advanced stream setting `area_strength=strong` asks the encoder for a larger step inside the area.

| Rate control | Area | Inside, standard → strong | Outside, standard → strong | Bitrate, strong |
| --- | --- | --- | --- | --- |
| Bitrate limit, automatic | Freehand, 5% | +2.2 to +2.7 → +2.6 to +3.6 dB | −0.1 to −0.4 → −0.1 to −0.7 dB | −6% to −2% |
| Bitrate limit, automatic | Quarter | +0.8 to +1.6 → +1.0 to +2.1 dB | −0.6 to −1.6 → −1.3 to −2.8 dB | −6% to +7% |
| Bitrate limit, 2 Mbit/s | Quarter | +0.7 to +1.8 → +0.9 to +2.4 dB | −1.1 to −2.5 → −2.2 to −4.2 dB | −8% to −4% |
| Fixed quality, QP 24 | Freehand, 5% | +1.3 to +1.7 → +2.5 to +3.4 dB | unchanged | +7% to +10% |
| Fixed quality, QP 24 | Quarter | +1.5 to +1.9 → +2.9 to +3.8 dB | unchanged | +63% to +140% |

`standard` is the default because a large area on a starved link costs the rest of the picture up to 2.5 dB already; `strong` takes up to 4.2 dB there.

## Live streams

Camera-to-viewer runs with `scripts/benchmark.py` (60 seconds after a 30-second warmup) on the same day and scenes. Each cell is `main` → this change without an area → this change with an area. The area is a centred box covering 16% of the picture (`--area 0.3,0.3,0.7,0.7`).

| Camera | RES | CC | Viewer | FPS | Mbit/s | P50 (ms) | P99 (ms) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| x86 · MIRA Procedure | FHD30 | H.264 | Holoviz | 28.5 → 28.7 → 28.8 | 8.1 → 8.2 → 7.0 | 10.87 → 10.69 → 10.30 | 19.78 → 19.50 → 18.53 |
| x86 · MIRA Room | FHD30 | H.264 | Holoviz | 28.5 → 28.7 → 28.8 | 8.1 → 8.2 → 7.0 | 10.37 → 10.23 → 9.78 | 19.71 → 19.99 → 18.63 |
| x86 · MIRA Procedure | FHD30 | H.264 | Browser | 27.2 → 27.1 → 27.3 | 8.3 → 8.3 → 7.1 | 36.59 → 37.64 → 36.90 | 60.83 → 59.33 → 57.00 |
| x86 · MIRA Room | FHD30 | H.264 | Browser | 27.2 → 27.4 → 27.2 | 8.3 → 8.3 → 7.1 | 36.32 → 38.38 → 36.22 | 59.06 → 58.57 → 56.57 |
| x86 · MIRA Procedure | FHD30 | H.265 | Holoviz | 28.4 → 28.7 → 28.8 | 8.2 → 8.2 → 6.9 | 10.76 → 10.83 → 10.41 | 19.29 → 20.06 → 19.07 |
| x86 · MIRA Room | FHD30 | H.265 | Holoviz | 28.4 → 28.5 → 28.8 | 8.0 → 8.0 → 6.9 | 10.16 → 10.28 → 9.67 | 20.38 → 20.98 → 19.66 |
| x86 · Logitech BRIO | FHD30 | H.264 | Holoviz | 29.8 → 29.8 → 29.8 | 8.7 → 8.7 → 8.6 | 6.64 → 6.37 → 6.43 | 11.98 → 11.85 → 11.72 |
| Thor · IMX274 | FHD60 | H.264 | Holoviz | 59.6 → 59.6 → 59.6 | 9.4 → 9.2 → 8.8 | 16.24 → 16.46 → 16.33 | 19.91 → 20.28 → 19.91 |
| Thor · IMX274 | 4K60 | H.265 | Holoviz | 59.8 → 59.8 → 59.8 | 4.4–21.6 → 4.4 → 1.7 | 16.07 → 15.99 → 15.67 | 19.85 → 19.93 → 19.99 |

- **Without an area, latency matches `main`** within run-to-run variation: P50 differs by −4% to +6% across the nine results (median +0.7%) and P99 by −3% to +4% (median +0.4%).
- **With an area, latency is no higher:** P50 changes by −6% to +1% against the same change without one. Frame rates are unchanged, and no run had a sequence gap.
- **Bitrate falls where the scene uses less than its limit.** These scenes do, so lowering detail outside the area lowers the total: 13–16% on the simulation, 1% on the BRIO, 4% on the IMX274 at FHD.
- **The IMX274 at 4K H.265 varies between runs of the same code.** Three runs on `main` gave 9.2, 21.6 and 4.4 Mbit/s; three runs of this change without an area gave 4.4 each (the first of each is in the latency columns). Identical frames encode to identical bytes on Thor with and without this change at 4K and FHD in both codecs, so the difference is in the camera's picture between starts, not in the encoder. With an area that stream used 1.7 Mbit/s in one run.

## Hosts

The same encoder path was run on each host with synthetic moving texture at 640×480, FHD and 4K, H.264 and H.265. On all three an area raised quality inside it, lowered it outside, produced no keyframe and left encode time unchanged.

| Host | GPU | Driver |
| --- | --- | --- |
| x86 workstation | RTX PRO 6000 Blackwell | 580.126.20 |
| DGX Spark | GB10 | 580.126.09 |
| Jetson AGX Thor | Thor | 580.00 |

## Method and limits

- **Clips:** `Endoscopy` is the public Holoscan endoscopy sample video, 854×480 upscaled to FHD, so it is soft; `Simulation` is a recording of the MIRA simulation at FHD.
- **Areas:** `Quarter of the picture` is a centred box covering 25.1% of the encoder's area grid. `Freehand, 5%` is an eight-point outline covering 4.9%.
- **Scoring:** frames were encoded and decoded on the x86 workstation. PSNR is on luma, averaged over frames 30–299, inside and outside the area's cells scaled to the picture.
- **PSNR is not a viewing test.** At the automatic limit both clips are already above 41 dB, where differences are hard to see; the gain matters most when the link is starved. No observer study was done.
- **Each configuration ran once.** Bitrate differences of a few percent between two runs of an under-limit scene are within run-to-run variation.
- **Not available with** NVENC's adaptive quantization (`aq`, `temporalaq`), nvJPEG, BGR8 or the tokenizer. With `multipass`, `qmax`, `vbv_frames` and `gop_seconds` an area was applied and decoded; their combined effect on quality was not measured.
