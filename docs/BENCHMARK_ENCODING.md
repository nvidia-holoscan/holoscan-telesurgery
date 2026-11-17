# Encoder defaults: before and after

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}} -->

November 2026 · Holoscan `5.0.0a3 (public EA3)` · H.264 and H.265 only.

This page compares the former encoder defaults with the current ones on the [SDK 5 benchmark](../BENCHMARK.md) matrix. Both sides were measured on 2026-11-17, on the same hosts and camera scenes, with `scripts/benchmark.py` and no encoder arguments.

| | Before (`main` at `dd3dd32`) | After |
| --- | --- | --- |
| Rate control | Constant QP 24 | Bitrate limit by resolution: 10 Mbit/s at FHD, 16 at QHD, 30 at 4K |
| Frames | Every frame an IDR | IPPP, IDR on demand, and one every ten seconds of frames at the configured rate |
| Recovery | None needed | Frames kept in order; an IDR repairs a viewer that fell behind |

nvJPEG and BGR8 are unchanged and are not compared here.

## Summary

<!-- summary:begin -->
| Viewer | Results | Bitrate, median (range) | Total P50, median | Total P99, median | Lower P99 | Sequence gaps after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Holoviz | 23 | -7% (-93% to +124%) | -2.8% | -4.3% | 16 of 23 | 0 |
| Browser | 17 | -7% (-64% to +61%) | -2.9% | -2.5% | 10 of 17 | 0 |
<!-- summary:end -->

Each row of the tables below reads **before → after**. Bitrate is the mean encoded frame size times the received frame rate. P50 and P99 are total latency from buffer availability to Holoviz submission, or to estimated browser display.

- **Bandwidth** falls most where the former defaults cost most: the physical cameras, by 62–64% on the BRIO and 59% on the IMX274 at 4K. For the simulation's procedure camera, H.264 changes by −21% to +3%. The MIRA room camera uses 20–60% more with H.264, and about twice as much with H.265 at 4K, because rate control now spends the limit on detail that QP 24 discarded.
- **Latency** follows frame size. Holoviz P50 is 2–23% lower on the physical cameras and within 4% on the x86 simulation. On the DGX Spark, simulator acquisition time differs by 1–2 ms between sessions and accounts for the changes at FHD and QHD.
- **Frame size** is bounded. The largest frame is now close to the per-frame share of the limit; before, it followed the scene, up to 295 KiB on the BRIO at 4K.
- **No refreshed run had a sequence gap, an undecodable frame or a recovery.** Every IDR in them was a periodic one. The period is 300 frames for a stream configured at 30 FPS, so a simulation that renders 6 FPS sends one about every 47 seconds.
- **DGX Spark simulation at 4K** renders at about 6 FPS and, in some sessions, delivers frames unevenly. The refreshed H.264 runs show it as a P99 near 270 ms in the acquisition stage; a repeat and an nvJPEG run in a later session showed the same pattern. Those P99 values describe the simulator, not the encoder.

## Results

<!-- tables:begin -->
### x86 · MIRA Procedure Camera

| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| FHD | H.264 | Holoviz | 29.2 → 29.0 | 10.2 → **8.3** | 43 → 36 | 10.74 → **10.74** | 17.99 → **18.40** |
| FHD | H.264 | Browser | 27.6 → 27.7 | 10.3 → **8.4** | 43 → 36 | 39.94 → **39.18** | 60.32 → **58.29** |
| QHD | H.264 | Holoviz | 28.0 → 28.2 | 14.0 → **13.0** | 61 → 58 | 17.27 → **17.32** | 25.08 → **25.33** |
| QHD | H.264 | Browser | 27.0 → 26.9 | 13.9 → **12.8** | 61 → 58 | 50.20 → **48.18** | 70.69 → **67.91** |
| 4K | H.264 | Holoviz | 14.3 → 14.7 | 11.6 → **11.9** | 100 → 105 | 45.68 → **44.02** | 57.60 → **55.71** |
| 4K | H.264 | Browser | 14.4 → 15.5 | 11.8 → **12.6** | 100 → 105 | 87.24 → **77.25** | 131.49 → **113.44** |
| 4K | H.265 | Holoviz | 15.2 → 15.3 | 9.6 → **13.0** | 80 → 125 | 41.46 → **40.65** | 53.64 → **51.31** |

### x86 · MIRA Room Camera

| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| FHD | H.264 | Holoviz | 29.2 → 29.0 | 6.7 → **8.3** | 28 → 36 | 10.15 → **10.18** | 18.21 → **18.00** |
| FHD | H.264 | Browser | 27.5 → 27.8 | 6.7 → **8.4** | 28 → 36 | 37.19 → **38.42** | 58.60 → **58.61** |
| QHD | H.264 | Holoviz | 28.0 → 28.5 | 9.2 → **13.1** | 40 → 58 | 17.13 → **16.92** | 24.04 → **23.01** |
| QHD | H.264 | Browser | 26.8 → 26.6 | 9.1 → **12.9** | 40 → 58 | 48.00 → **46.63** | 67.39 → **68.56** |
| 4K | H.264 | Holoviz | 14.3 → 14.8 | 7.8 → **12.3** | 67 → 105 | 33.86 → **32.92** | 41.73 → **39.88** |
| 4K | H.264 | Browser | 14.6 → 15.5 | 8.0 → **12.9** | 67 → 105 | 72.27 → **72.52** | 111.31 → **111.16** |
| 4K | H.265 | Holoviz | 15.3 → 15.3 | 6.2 → **14.0** | 52 → 123 | 31.69 → **29.84** | 40.08 → **38.08** |

### x86 · Logitech BRIO Camera

| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| FHD | H.264 | Holoviz | 29.9 → 29.9 | 23.0 → **8.7** | 95 → 37 | 9.07 → **8.50** | 12.87 → **12.62** |
| FHD | H.264 | Browser | 29.6 → 30.0 | 21.5 → **8.7** | 88 → 37 | 57.27 → **45.10** | 76.23 → **76.68** |
| QHD | H.264 | Holoviz | 29.8 → 29.8 | 38.5 → **14.0** | 158 → 60 | 6.78 → **5.90** | 9.37 → **8.27** |
| QHD | H.264 | Browser | 30.0 → 30.0 | 38.5 → **14.0** | 159 → 60 | 38.03 → **39.17** | 55.53 → **60.02** |
| 4K | H.264 | Holoviz | 30.0 → 30.0 | 71.1 → **25.7** | 291 → 113 | 11.06 → **10.59** | 13.79 → **14.22** |
| 4K | H.264 | Browser | 30.0 → 29.8 | 71.8 → **25.7** | 295 → 113 | 73.55 → **44.18** | 91.71 → **47.29** |
| 4K | H.265 | Holoviz | 30.0 → 29.7 | 63.7 → **31.8** | 261 → 140 | 10.51 → **8.12** | 13.66 → **10.70** |

### Thor · IMX274 Camera

| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| FHD | H.264 | Holoviz | 59.8 → 59.7 | 9.9 → **9.1** | 20 → 21 | 16.31 → **15.99** | 18.63 → **18.15** |
| FHD | H.264 | Browser | 59.2 → 59.3 | 9.9 → **9.0** | 20 → 21 | 51.57 → **48.64** | 69.79 → **65.89** |
| 4K | H.264 | Holoviz | 59.9 → 60.0 | 69.5 → **28.4** | 142 → 71 | 17.26 → **16.20** | 20.18 → **18.45** |
| 4K | H.264 | Browser | 55.5 → 55.4 | 69.5 → **28.3** | 142 → 69 | 63.29 → **55.89** | 80.11 → **76.31** |
| 4K | H.265 | Holoviz | 60.0 → 60.0 | 64.3 → **4.4** | 131 → 12 | 17.68 → **15.20** | 20.99 → **19.29** |

### DGX Spark · MIRA Procedure Camera

| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| FHD | H.264 | Holoviz | 16.1 → 16.3 | 5.8 → **4.6** | 44 → 36 | 15.72 → **16.13** | 18.39 → **18.60** |
| FHD | H.264 | Browser | 16.2 → 16.3 | 5.8 → **4.6** | 44 → 36 | 52.30 → **53.58** | 81.39 → **78.88** |
| QHD | H.264 | Holoviz | 11.2 → 11.4 | 5.7 → **5.2** | 62 → 58 | 24.14 → **26.33** | 43.59 → **29.69** |
| QHD | H.264 | Browser | 11.3 → 11.4 | 5.7 → **5.2** | 62 → 59 | 74.27 → **70.11** | 111.67 → **108.85** |
| 4K | H.264 | Holoviz | 6.4 → 6.4 | 5.2 → **4.2** | 100 → 105 | 74.25 → **47.76** | 85.19 → **272.92** |
| 4K | H.264 | Browser | 6.4 → 6.3 | 5.3 → **4.9** | 102 → 105 | 118.55 → **90.35** | 151.49 → **325.00** |
| 4K | H.265 | Holoviz | 6.4 → 6.4 | 4.1 → **5.4** | 81 → 107 | 75.85 → **48.49** | 84.40 → **58.55** |

### DGX Spark · MIRA Room Camera

| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| FHD | H.264 | Holoviz | 16.1 → 16.3 | 3.7 → **4.6** | 28 → 36 | 13.06 → **14.09** | 16.19 → **17.62** |
| FHD | H.264 | Browser | 16.2 → 16.3 | 3.7 → **4.6** | 28 → 36 | 49.31 → **52.00** | 77.55 → **78.26** |
| QHD | H.264 | Holoviz | 11.2 → 11.4 | 3.7 → **5.2** | 40 → 58 | 23.34 → **25.30** | 29.35 → **29.59** |
| QHD | H.264 | Browser | 11.3 → 11.4 | 3.7 → **5.2** | 40 → 58 | 69.45 → **72.28** | 107.20 → **112.43** |
| 4K | H.264 | Holoviz | 6.4 → 6.4 | 3.5 → **4.2** | 67 → 104 | 46.71 → **40.96** | 60.17 → **54.36** |
| 4K | H.264 | Browser | 6.4 → 6.5 | 3.5 → **5.1** | 67 → 104 | 80.54 → **82.22** | 107.87 → **104.27** |
| 4K | H.265 | Holoviz | 6.4 → 6.4 | 2.6 → **5.5** | 51 → 106 | 48.62 → **48.68** | 60.99 → **54.99** |
<!-- tables:end -->

## Quality at these bitrates

The same recorded clips were encoded and decoded on Thor with both sets of defaults. PSNR is against the source frames; for camera clips the value in parentheses is against a noise-free reference, the average of 240–300 frames of the static scene.

| Clip | Before: QP 24 | After: automatic limit |
| --- | --- | --- |
| Simulation, FHD 30 FPS | 10.1 Mbit/s, 45.1 dB | 4.7 Mbit/s, 48.4 dB |
| IMX274 static, FHD 60 FPS | 10.0 Mbit/s, 38.5 dB (44.4 dB) | 9.1 Mbit/s, 38.5 dB (43.9 dB) |
| IMX274 panning, FHD 60 FPS | 19.4 Mbit/s, 36.0 dB (42.0 dB) | 9.2 Mbit/s, 35.6 dB (42.9 dB) |
| IMX274 static, 4K 60 FPS | 69.5 Mbit/s, 36.2 dB | 28.4 Mbit/s, 35.8 dB |

Simulation gains 3 dB at less than half the bitrate. Camera footage is noise-limited: its PSNR against the source moves by less than 0.5 dB between 3 and 30 Mbit/s, and a higher bitrate mostly preserves sensor noise. Predicted frames stayed within 1.13 times their share of the limit in these clips, and IDRs within it. At limits below half the automatic value the encoder overshoots: a 5 Mbit/s limit on the panning clip produced 6.2 Mbit/s.

## Links slower or lossier than the stream

A recorded IMX274 clip (FHD, 60 FPS, panning) was replayed as a camera on the DGX Spark and viewed in Holoviz on the x86 workstation. `tc netem` shaped the Spark's video traffic. One run per row.

| Link | Before | After |
| --- | --- | --- |
| Unimpaired (two runs) | 60 FPS, 8.1–8.5 ms P50, 19.5 Mbit/s | 60 FPS, 7.6 ms P50, 9.1 Mbit/s |
| Limited to 15 Mbit/s | 47 FPS, 1.2 s P50 | 60 FPS, 16.9 ms P50 |
| 1% loss and 20 ms delay | 30 FPS, 0.76 s P50 | 54 FPS, 0.67 s P50 |
| Limited to 6 Mbit/s | 20 FPS, 3.0 s P50 | 36 FPS, 2.9 s P50 |

A stream that fits the link is unaffected by the limit. When the link is slower than the stream, both versions queue seconds of video in the TCP send buffer. The bitrate setting now lets an operator choose a stream that fits; nothing adapts it automatically.

## Browser viewing under packet loss

The same clip was sent from a surgeon dashboard on the DGX Spark to Chromium on the x86 workstation, with packet loss added on the Spark. 45-second runs.

| Loss | Before | After |
| --- | --- | --- |
| None (three runs) | 60 FPS, no freezes, 43–48 ms P50 | 60 FPS, no freezes, 40–53 ms P50 |
| 2% | 59.0 FPS, no freezes | 57.2 FPS, no freezes, 154 IDRs |
| 5% and 20 ms delay | 55.3 FPS, no freezes | 50.1 FPS, 6 freezes totalling 1.2 s, 323 IDRs |

Independent frames lose one frame per unrecovered packet. Predicted frames lose every frame until the next IDR, so the dashboard forces an IDR when the browser requests a packet twice, and for every loss while retransmissions keep failing. Heavy loss is still somewhat worse than before in the browser.

## Recovery

- IMX274 at 4K and 60 FPS from Thor to Holoviz for ten minutes: 36,000 frames, no sequence gap, no undecodable frame, no recovery, and 60 IDRs, all periodic.
- Changing rate control and advanced settings three times in a running stream: the stream stayed live with one IDR per change and no undecodable frame.
- A forced IDR every 0.5 seconds costs 0.7–1.6 dB on the simulation clip and nothing measurable on camera footage, at an unchanged bitrate; one every 2 seconds costs 0.1–0.4 dB. An IDR reaches every viewer of a camera, so a viewer that keeps falling behind lowers the others' quality by this much, not their frame rate.

## Method and limits

- Each configuration ran once per side: 60 seconds after a 30-second warmup. Differences of a few percent are within run-to-run variation; three repeats of the Thor configurations differed by 0.3 ms at P50.
- The "after" runs used commit `7c59a57`. Later commits in the same change keep predicted frames in order on the surgeon dashboard's browser path, limit keyframe requests in flight and adjust tests and text.
- The automatic limits were chosen from this footage: a dim, low-detail laboratory scene for the IMX274, a webcam scene, and simulation. Surgical content may need different limits; see [TODO](TODO.md).
- NVENC's CBR mode is not used. It produces the same pictures as the bitrate limit, then pads H.264 frames with filler data: 43–45% of the simulation stream and 0–13% of camera streams.
- Physical scenes were not controlled between the October report and this one, which is why the former defaults were measured again here instead of reusing October's results.
- Baseline records are summarised in [`encoding_baseline.csv`](../benchmarks/results/encoding_baseline.csv). `python benchmarks/encoding.py` regenerates the summary and result tables.
