# Priority area: what it changes

A priority area is a region a surgeon draws on a camera view. The patient-side encoder then keeps picture quality inside it and spends less on the rest of the picture. Pixels are not altered and the stream decodes like any other. This page records what the encoder does with an area, measured through the product's own encoder (`telesurgery_core.video.codecs.GpuCodec`) with its default settings.

## Summary

Default strength (`strong`) at FHD, on two clips with both codecs:

| Rate control | Area | Inside the area | Rest of the picture | Bitrate |
| --- | --- | --- | --- | --- |
| Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% of the picture | +1.7 to +2.4 dB | −3.1 to −6.4 dB | −69% to −72% |
| Bitrate limit, automatic (10 Mbit/s) | Box, 16% | +0.7 to +1.2 dB | −4.9 to −8.1 dB | −59% to −63% |
| Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | +0.3 to +0.9 dB | −5.7 to −8.5 dB | −50% to −54% |
| Bitrate limit, 2 Mbit/s | Freehand, 5% of the picture | +2.6 to +5.8 dB | −1.2 to −1.8 dB | −12% to +2% |
| Bitrate limit, 2 Mbit/s | Quarter of the picture | +1.0 to +3.0 dB | −5.5 to −6.4 dB | −10% to −23% |
| Fixed quality (QP 24) | Freehand, 5% of the picture | +1.2 to +1.5 dB | −4.0 to −4.7 dB | −56% to −77% |
| Fixed quality (QP 24) | Quarter of the picture | +1.5 to +1.8 dB | −3.8 to −4.6 dB | −15% to +6% |

- **The default is meant to be seen.** `strong` encodes the area 16 quantizer steps finer than the rest of the picture and lowers the stream's bitrate to what the coarser rest no longer needs: the area's share of the picture plus a fifth of the remainder, which is a third of the limit for an area covering 16%. The area keeps or gains quality, the rest loses 3 to 8.5 dB, and bandwidth falls by a half to three quarters.
- **A stream short of bandwidth is not cut further.** The bitrate never goes below a quarter of the automatic limit for the picture size (2.5 Mbit/s at FHD). A stream at or under that keeps its bitrate and the same step moves quality into the area: at 2 Mbit/s the area gains 1.0 to 5.8 dB and the rest loses 1.2 to 6.4 dB.
- **With fixed quality there is no bitrate to lower.** `strong` encodes the area 4 steps finer and the rest 8 coarser, which saves bandwidth for an area smaller than about a quarter of the picture.
- **`area_strength=subtle` does not lower the bitrate** and moves a smaller amount of quality: with a bitrate limit a 5% area gains 1.8 to 3.5 dB for 0.2 to 0.6 dB outside ([Subtle](#subtle)).
- **The bitrate falls from the next frame; on a still scene the softening follows later.** Blocks that do not change are skipped and keep the detail they had, until they change or the next periodic keyframe (10 seconds) codes them again ([Timing](#timing)).
- **No keyframe** is produced when an area is set, moved or cleared.
- **Frames are no larger than without an area.** At the automatic limit the largest predicted frame was 0.30–0.83 times its share of the limit with a `strong` area and 0.89–1.10 without; the keyframe was 0.46–0.88 times against 0.85–0.91.
- **Encode time is unchanged:** 2.4–3.1 ms per FHD frame without an area and 2.4–3.2 ms with one (median difference under 0.01 ms). Applying a new area took 0.5–2.0 ms (median 0.9 ms, 24 changes) when the bitrate changes with it and 0.4–2.0 ms (median 0.7 ms, 48 changes) when it does not. It happens once per change, not per frame.
- **Without an area the stream is byte-identical** to one from an encoder that cannot take areas.
- **Live latency was measured with `subtle` only.** Camera-to-viewer P50 and P99 in nine live results from four cameras match `main` without an area and are no higher with a `subtle` one. The `strong` default has not been through that benchmark ([live streams](#live-streams)).

## Strength

`area_strength` is an advanced stream setting. `strong` is the default.

| Strength | Rate control | Area | Rest of the picture | Bitrate |
| --- | --- | --- | --- | --- |
| `strong` | Bitrate limit | 8 steps finer | 8 steps coarser | Lowered to the area's share of the picture plus a fifth of the remainder; never below a quarter of the automatic limit |
| `strong` | Fixed quality | 4 steps finer | 8 steps coarser | Follows from the two steps |
| `subtle` | Bitrate limit | 4 steps finer | 4 steps coarser | Unchanged: rate control holds the limit, so quality moves |
| `subtle` | Fixed quality | 4 steps finer | The chosen QP | Rises with the size of the area |

The steps are relative: with a bitrate limit, rate control still chooses each frame's base quantizer to meet the limit, so the table gives the distance between the area and the rest, not their absolute quality.

Lowering the bitrate uses NVENC's reconfigure call and needs no keyframe. The rate buffer keeps its size, so a frame may still be as large as the limit already allowed. Scaling the buffer with the bitrate was tried and rejected: on the office clip with a 16% area, the keyframe measured 37.6 dB inside the area with a scaled buffer, 42.4 dB with the buffer kept, and 38.2 dB with no area, and the picture took about ten frames to recover.

## Results

FHD, 30 FPS, default strength. Each cell is without an area → with an area; quality is luma PSNR against the source, scored over the same pixels in both runs.

| Clip | Rate control | Area | CC | Mbit/s | Inside (dB) | Rest of the picture (dB) |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.264 | 8.1 → 2.5 | 42.3 → **44.5** (+2.2) | 42.8 → 36.4 (−6.4) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.265 | 8.1 → 2.5 | 42.6 → **45.0** (+2.4) | 43.3 → 37.5 (−5.8) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.264 | 8.1 → 3.3 | 40.9 → **41.7** (+0.9) | 43.3 → 35.2 (−8.1) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.265 | 8.1 → 3.3 | 41.2 → **42.5** (+1.2) | 43.8 → 36.2 (−7.7) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.264 | 8.1 → 4.0 | 41.0 → **41.7** (+0.7) | 43.6 → 35.1 (−8.5) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.265 | 8.1 → 4.0 | 41.4 → **42.3** (+0.9) | 44.2 → 36.1 (−8.0) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.264 | 2.6 → 2.3 | 38.0 → **43.7** (+5.8) | 37.8 → 36.2 (−1.6) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.265 | 2.6 → 2.3 | 38.8 → **44.3** (+5.5) | 38.6 → 37.3 (−1.3) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Box, 16% | H.264 | 2.6 → 2.3 | 36.1 → **40.0** (+3.9) | 38.3 → 33.6 (−4.6) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Box, 16% | H.265 | 2.6 → 2.2 | 36.8 → **40.6** (+3.8) | 39.0 → 34.6 (−4.5) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.264 | 2.6 → 2.4 | 36.2 → **39.2** (+3.0) | 38.5 → 32.6 (−6.0) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.265 | 2.6 → 2.3 | 36.9 → **39.9** (+2.9) | 39.3 → 33.8 (−5.5) |
| Endoscopy | Fixed quality, QP 24 | Freehand, 5% | H.264 | 7.5 → 3.3 | 43.5 → **44.8** (+1.3) | 43.4 → 38.7 (−4.7) |
| Endoscopy | Fixed quality, QP 24 | Freehand, 5% | H.265 | 6.9 → 2.9 | 43.8 → **44.9** (+1.2) | 43.6 → 39.1 (−4.5) |
| Endoscopy | Fixed quality, QP 24 | Box, 16% | H.264 | 7.5 → 5.2 | 41.8 → **43.5** (+1.8) | 43.8 → 39.2 (−4.6) |
| Endoscopy | Fixed quality, QP 24 | Box, 16% | H.265 | 6.9 → 4.7 | 42.0 → **43.8** (+1.8) | 44.0 → 39.6 (−4.5) |
| Endoscopy | Fixed quality, QP 24 | Quarter of the picture | H.264 | 7.5 → 6.5 | 41.9 → **43.7** (+1.8) | 44.1 → 39.5 (−4.6) |
| Endoscopy | Fixed quality, QP 24 | Quarter of the picture | H.265 | 6.9 → 5.9 | 42.1 → **43.9** (+1.7) | 44.3 → 39.9 (−4.4) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.264 | 8.6 → 2.5 | 45.8 → **47.6** (+1.9) | 45.5 → 42.2 (−3.3) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.265 | 8.7 → 2.5 | 45.7 → **47.4** (+1.7) | 45.3 → 42.2 (−3.1) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.264 | 8.6 → 3.2 | 45.7 → **46.6** (+0.9) | 45.4 → 39.7 (−5.7) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.265 | 8.7 → 3.2 | 45.7 → **46.4** (+0.7) | 45.2 → 40.3 (−4.9) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.264 | 8.6 → 3.9 | 45.5 → **45.9** (+0.5) | 45.5 → 38.8 (−6.7) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.265 | 8.7 → 4.0 | 45.4 → **45.7** (+0.3) | 45.3 → 39.5 (−5.7) |
| Office camera | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.264 | 2.6 → 2.4 | 43.8 → **46.4** (+2.6) | 43.7 → 41.9 (−1.8) |
| Office camera | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.265 | 2.4 → 2.5 | 43.6 → **47.0** (+3.4) | 43.4 → 42.1 (−1.2) |
| Office camera | Bitrate limit, 2 Mbit/s | Box, 16% | H.264 | 2.6 → 1.9 | 43.6 → **45.3** (+1.7) | 43.7 → 38.6 (−5.1) |
| Office camera | Bitrate limit, 2 Mbit/s | Box, 16% | H.265 | 2.4 → 2.0 | 43.4 → **45.4** (+1.9) | 43.4 → 38.8 (−4.6) |
| Office camera | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.264 | 2.6 → 2.0 | 43.4 → **44.4** (+1.1) | 43.8 → 37.3 (−6.4) |
| Office camera | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.265 | 2.4 → 2.0 | 43.2 → **44.2** (+1.0) | 43.5 → 37.6 (−5.9) |
| Office camera | Fixed quality, QP 24 | Freehand, 5% | H.264 | 2.0 → 0.5 | 43.2 → **44.7** (+1.5) | 43.6 → 39.1 (−4.5) |
| Office camera | Fixed quality, QP 24 | Freehand, 5% | H.265 | 2.7 → 0.6 | 43.3 → **44.6** (+1.3) | 43.6 → 39.6 (−4.0) |
| Office camera | Fixed quality, QP 24 | Box, 16% | H.264 | 2.0 → 1.4 | 43.3 → **44.8** (+1.5) | 43.6 → 39.2 (−4.4) |
| Office camera | Fixed quality, QP 24 | Box, 16% | H.265 | 2.7 → 1.6 | 43.3 → **44.8** (+1.5) | 43.6 → 39.7 (−3.9) |
| Office camera | Fixed quality, QP 24 | Quarter of the picture | H.264 | 2.0 → 2.2 | 43.1 → **44.7** (+1.6) | 43.7 → 39.4 (−4.3) |
| Office camera | Fixed quality, QP 24 | Quarter of the picture | H.265 | 2.7 → 2.3 | 43.1 → **44.6** (+1.5) | 43.8 → 40.0 (−3.8) |

At 2 Mbit/s both clips need more than the limit without an area (2.4–2.6 Mbit/s) and come closer to it with one (1.9–2.5 Mbit/s). The largest predicted frame there was 1.23–2.73 times its share of the limit with an area and 1.48–2.63 without; the keyframe was 1.39–2.33 times against 1.86–2.20.

## Timing

An area was set on a stream one second after it started, with no keyframe for the next four seconds (16% box, H.264, automatic limit).

| Clip | First frame with the area | Rest of the picture before the next keyframe | Rest of the picture after it |
| --- | --- | --- | --- |
| Office camera (still scene) | 23% of the size of the same frame without an area | −2.4 to −2.5 dB | −5.7 dB |
| Endoscopy (moving scene) | 36% | −7.5 to −7.7 dB | −8.1 dB |

- **The bitrate changes at once** in both clips.
- **A moving scene softens within the first second.** Every block is coded again as the picture changes.
- **A still scene keeps its earlier detail until the next keyframe.** The early loss on the office clip is sensor noise that the coarser quantizer no longer codes. Edges and texture stay: fine detail outside the area (Laplacian energy against the source) was 99–100% before the keyframe and 87% after it, against 102% without an area.

## Subtle

`area_strength=subtle` leaves the bitrate limit alone, so rate control moves quality into the area at the bandwidth the stream already has. FHD, 30 FPS, same clips and method:

| Rate control | Area | Inside the area | Rest of the picture | Bitrate |
| --- | --- | --- | --- | --- |
| Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% of the picture | +1.8 to +2.7 dB | −0.2 to −0.4 dB | 0% to −2% |
| Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | +0.9 to +1.8 dB | −0.9 to −1.7 dB | −1% to −4% |
| Bitrate limit, 2 Mbit/s | Freehand, 5% of the picture | +2.1 to +3.5 dB | −0.3 to −0.6 dB | −4% to +1% |
| Bitrate limit, 2 Mbit/s | Quarter of the picture | +1.0 to +2.0 dB | −1.5 to −2.5 dB | −5% to −9% |
| Fixed quality (QP 24) | Freehand, 5% of the picture | +1.5 to +1.7 dB | unchanged | +3% to +13% |
| Fixed quality (QP 24) | Quarter of the picture | +1.7 to +1.9 dB | unchanged | +24% to +72% |

| Clip | Rate control | Area | CC | Mbit/s | Inside (dB) | Rest of the picture (dB) |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.264 | 8.1 → 8.0 | 42.3 → **45.0** (+2.7) | 42.8 → 42.4 (−0.4) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.265 | 8.1 → 8.0 | 42.6 → **45.3** (+2.7) | 43.3 → 43.0 (−0.3) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.264 | 8.1 → 7.9 | 40.9 → **43.0** (+2.1) | 43.3 → 42.1 (−1.2) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.265 | 8.1 → 7.9 | 41.2 → **43.6** (+2.4) | 43.8 → 42.7 (−1.1) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.264 | 8.1 → 7.8 | 41.0 → **42.7** (+1.7) | 43.6 → 41.9 (−1.7) |
| Endoscopy | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.265 | 8.1 → 7.8 | 41.4 → **43.2** (+1.8) | 44.2 → 42.6 (−1.6) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.264 | 2.6 → 2.5 | 38.0 → **41.5** (+3.5) | 37.8 → 37.3 (−0.6) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.265 | 2.6 → 2.5 | 38.8 → **42.0** (+3.3) | 38.6 → 38.2 (−0.4) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Box, 16% | H.264 | 2.6 → 2.5 | 36.1 → **38.7** (+2.6) | 38.3 → 36.6 (−1.7) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Box, 16% | H.265 | 2.6 → 2.4 | 36.8 → **39.3** (+2.5) | 39.0 → 37.4 (−1.6) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.264 | 2.6 → 2.5 | 36.2 → **38.2** (+2.0) | 38.5 → 36.1 (−2.5) |
| Endoscopy | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.265 | 2.6 → 2.4 | 36.9 → **38.9** (+1.9) | 39.3 → 37.0 (−2.3) |
| Endoscopy | Fixed quality, QP 24 | Freehand, 5% | H.264 | 7.5 → 7.7 | 43.5 → **45.0** (+1.5) | 43.4 → 43.4 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Freehand, 5% | H.265 | 6.9 → 7.2 | 43.8 → **45.3** (+1.5) | 43.6 → 43.6 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Box, 16% | H.264 | 7.5 → 8.7 | 41.8 → **43.7** (+1.9) | 43.8 → 43.8 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Box, 16% | H.265 | 6.9 → 8.1 | 42.0 → **44.0** (+2.0) | 44.0 → 44.0 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Quarter of the picture | H.264 | 7.5 → 9.3 | 41.9 → **43.8** (+1.9) | 44.1 → 44.1 (0.0) |
| Endoscopy | Fixed quality, QP 24 | Quarter of the picture | H.265 | 6.9 → 8.6 | 42.1 → **44.0** (+1.9) | 44.3 → 44.3 (0.0) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.264 | 8.6 → 8.5 | 45.8 → **47.6** (+1.8) | 45.5 → 45.3 (−0.2) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Freehand, 5% | H.265 | 8.7 → 8.6 | 45.7 → **47.5** (+1.8) | 45.3 → 45.1 (−0.2) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.264 | 8.6 → 8.5 | 45.7 → **47.1** (+1.5) | 45.4 → 44.8 (−0.7) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Box, 16% | H.265 | 8.7 → 8.6 | 45.7 → **47.0** (+1.3) | 45.2 → 44.6 (−0.6) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.264 | 8.6 → 8.5 | 45.5 → **46.6** (+1.1) | 45.5 → 44.6 (−0.9) |
| Office camera | Bitrate limit, automatic (10 Mbit/s) | Quarter of the picture | H.265 | 8.7 → 8.4 | 45.4 → **46.3** (+0.9) | 45.3 → 44.3 (−0.9) |
| Office camera | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.264 | 2.6 → 2.6 | 43.8 → **45.9** (+2.1) | 43.7 → 43.3 (−0.4) |
| Office camera | Bitrate limit, 2 Mbit/s | Freehand, 5% | H.265 | 2.4 → 2.4 | 43.6 → **45.8** (+2.3) | 43.4 → 43.0 (−0.3) |
| Office camera | Bitrate limit, 2 Mbit/s | Box, 16% | H.264 | 2.6 → 2.5 | 43.6 → **45.1** (+1.5) | 43.7 → 42.5 (−1.2) |
| Office camera | Bitrate limit, 2 Mbit/s | Box, 16% | H.265 | 2.4 → 2.4 | 43.4 → **44.9** (+1.5) | 43.4 → 42.4 (−0.9) |
| Office camera | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.264 | 2.6 → 2.3 | 43.4 → **44.4** (+1.0) | 43.8 → 42.0 (−1.8) |
| Office camera | Bitrate limit, 2 Mbit/s | Quarter of the picture | H.265 | 2.4 → 2.3 | 43.2 → **44.2** (+1.0) | 43.5 → 42.0 (−1.5) |
| Office camera | Fixed quality, QP 24 | Freehand, 5% | H.264 | 2.0 → 2.3 | 43.2 → **44.9** (+1.7) | 43.6 → 43.6 (0.0) |
| Office camera | Fixed quality, QP 24 | Freehand, 5% | H.265 | 2.7 → 3.0 | 43.3 → **44.9** (+1.6) | 43.6 → 43.6 (0.0) |
| Office camera | Fixed quality, QP 24 | Box, 16% | H.264 | 2.0 → 3.0 | 43.3 → **44.9** (+1.7) | 43.6 → 43.6 (0.0) |
| Office camera | Fixed quality, QP 24 | Box, 16% | H.265 | 2.7 → 3.6 | 43.3 → **45.0** (+1.7) | 43.6 → 43.6 (0.0) |
| Office camera | Fixed quality, QP 24 | Quarter of the picture | H.264 | 2.0 → 3.5 | 43.1 → **44.8** (+1.7) | 43.7 → 43.7 (0.0) |
| Office camera | Fixed quality, QP 24 | Quarter of the picture | H.265 | 2.7 → 4.0 | 43.1 → **44.8** (+1.7) | 43.8 → 43.8 (0.0) |

With `subtle` the largest predicted frame at the automatic limit was 0.88–1.08 times its share of the limit.

The simulation clip was measured with this strength only, by an earlier method (area set before the first frame, frames 30–299 scored):

| Clip | Rate control | Area | CC | Mbit/s | Inside (dB) | Rest of the picture (dB) |
| --- | --- | --- | --- | ---: | ---: | ---: |
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

## Live streams

Camera-to-viewer runs with `scripts/benchmark.py` (60 seconds after a 30-second warmup) on the same day and scenes. Each cell is `main` → this change without an area → this change with a `subtle` area. These runs were made with the strength that is now `subtle`, before `strong` became the default. The area is a centred box covering 16% of the picture (`--area 0.3,0.3,0.7,0.7`).

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
- **With a `subtle` area, latency is no higher:** P50 changes by −6% to +1% against the same change without one. Frame rates are unchanged, and no run had a sequence gap.
- **With `subtle`, bitrate falls where the scene uses less than its limit.** These scenes do, so lowering detail outside the area lowers the total: 13–16% on the simulation, 1% on the BRIO, 4% on the IMX274 at FHD.
- **The IMX274 at 4K H.265 varies between runs of the same code.** Three runs on `main` gave 9.2, 21.6 and 4.4 Mbit/s; three runs of this change without an area gave 4.4 each (the first of each is in the latency columns). Identical frames encode to identical bytes on Thor with and without this change at 4K and FHD in both codecs, so the difference is in the camera's picture between starts, not in the encoder. With a `subtle` area that stream used 1.7 Mbit/s in one run.
- **The `strong` default was not run through this benchmark.** On the workstation's live stack with the default strength, the Logitech BRIO at FHD30 H.264 in a browser used 8.5 Mbit/s without an area, 2.6 Mbit/s with a box covering 7% of the picture and 8.6 Mbit/s after it was cleared. The MIRA room camera at FHD30 H.265 in Holoviz went from 8.0 to 1.4 Mbit/s with a 12% box. Frames with a `strong` area are smaller than without one, so there is no reason to expect added latency, but camera-to-viewer latency with `strong` was not measured.

## Hosts

The default `strong` strength was run on the DGX Spark and Jetson AGX Thor through the same encoder path: one FHD30 stream of moving texture with fresh noise in every frame, 60 frames without an area, 60 with a box covering 16% of the picture and 60 after clearing it.

| Host | CC | Mbit/s: no area → area → cleared | Inside (dB) | Rest of the picture (dB) |
| --- | --- | --- | --- | --- |
| DGX Spark | H.264 | 8.9 → 3.3 → 8.8 | 31.0 → 31.0 → 31.0 | 31.0 → 28.7 → 31.0 |
| DGX Spark | H.265 | 9.5 → 3.3 → 9.4 | 31.1 → 31.1 → 31.1 | 31.1 → 29.7 → 31.1 |
| Jetson AGX Thor | H.264 | 8.9 → 3.3 → 8.8 | 31.0 → 31.0 → 31.0 | 31.0 → 28.2 → 31.0 |
| Jetson AGX Thor | H.265 | 9.0 → 3.3 → 9.1 | 30.9 → 30.9 → 30.9 | 30.9 → 29.6 → 30.9 |

- **The bitrate lands on the planned third of the limit** (3.28 Mbit/s for this area) on both hosts and returns to the full rate when the area is cleared.
- **The only keyframe in each run is the first frame.**
- **The area keeps its quality while the rest of the picture gives up 1.3 to 2.8 dB** on this content, against 5 to 8 dB on the clips above. This texture is noise the encoder cannot predict, so it says how the encoder behaves on each host, not how a camera picture looks.

Earlier runs on each host used what is now the `subtle` strength, with synthetic moving texture at 640×480, FHD and 4K in both codecs. On all three an area raised quality inside it, lowered it outside, produced no keyframe and left encode time unchanged. Without an area, an encoder that can take one produced byte-identical streams to one that cannot, at FHD and 4K in both codecs on each host.

| Host | GPU | Driver |
| --- | --- | --- |
| x86 workstation | RTX PRO 6000 Blackwell | 580.126.20 |
| DGX Spark | GB10 | 580.126.09 |
| Jetson AGX Thor | Thor | 580.00 |

## Method and limits

- **Clips:** `Endoscopy` is the public Holoscan endoscopy sample video, 854×480 upscaled to FHD, so it is soft. `Office camera` is ten seconds recorded uncompressed from a Logitech BRIO at FHD: a still office scene with sensor noise. `Simulation` is a recording of the MIRA simulation at FHD, used for the earlier `subtle` rows only.
- **Areas:** `Freehand, 5%` is an eight-point outline covering 4.9% of the encoder's area grid. `Box, 16%` is a centred box covering 16.0%. `Quarter of the picture` is a centred box covering 25.1%.
- **Scoring:** each run encodes 300 frames on the x86 workstation. The area is set before frame 30 and a keyframe is requested at frame 150. PSNR is on luma over frames 180–299, when every block has been coded with the area, inside and outside the area's cells scaled to the picture. Bitrate is the mean over frames 60–299.
- **PSNR is not a viewing test.** Without an area both clips are above 40 dB at the automatic limit. With a `strong` area the rest of the picture is at 35–42 dB there: in side-by-side crops of the office scene, carpet texture and small print outside the area are visibly softer and the area looks the same. No observer study was done, and none on surgical content.
- **Each configuration ran once.** Bitrate differences of a few percent between two runs of an under-limit scene are within run-to-run variation.
- **Encode and apply times were taken while four live camera streams were encoding on the same GPU.**
- **Not available with** NVENC's adaptive quantization (`aq`, `temporalaq`), nvJPEG, BGR8 or the tokenizer. With `multipass`, `qmax`, `vbv_frames` and `gop_seconds` an area was applied and decoded; their combined effect on quality was not measured.
