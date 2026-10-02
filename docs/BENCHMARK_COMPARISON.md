# SDK 4 vs SDK 5 benchmark comparison

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}, "MD033": {"allowed_elements": ["details", "summary", "table", "thead", "tbody", "tr", "th", "td", "strong"]}} -->

October 2026 · Holoscan **4.6.0** vs **5.0.0.dev20260928**.

[SDK 5 benchmark](../BENCHMARK.md) · [SDK 4 benchmark](BENCHMARK_SDK4.md) · [Measurements](../benchmarks/results/summary.csv)

**The surgeon always runs on the x86 workstation.** Matching results use the same patient host, camera, resolution, codec and receiver. This report pairs **57 Holoviz camera results** and **17 WebRTC camera results** per SDK; both MIRA cameras stream simultaneously.

## P99 overview

SDK 5 has lower P99 total latency in **36 of 57** matched Holoviz results. The median per-result change is **-1.5%**. Results vary by camera, resolution and codec; this is not an across-the-board speedup.

![P99 total latency change from SDK 4 to SDK 5 for every matched source, resolution and codec](../benchmarks/figures/sdk-comparison.svg)

**Change = (SDK 5 / SDK 4 − 1) × 100.** Negative latency changes favor SDK 5. Gray cells were not tested. FHD = 1920×1080; QHD = 2560×1440; 4K = 3840×2160. H.265 was tested only at 4K.

## Total latency change

Each cell is the median percentage change across that camera’s matched resolution/codec configurations. These are summaries of per-configuration changes, not percentiles of pooled frames. Each configuration has equal weight.

| Patient · Camera | P50 | P95 | P99 | P99.9 |
| --- | --- | --- | --- | --- |
| x86 · MIRA Procedure Camera | +1.3% | +0.1% | 0.0% | +0.8% |
| x86 · MIRA Room Camera | +0.5% | -0.5% | -0.1% | +0.2% |
| x86 · Logitech BRIO Camera | -3.0% | -3.8% | -3.8% | -1.9% |
| Thor · IMX274 Camera | +7.4% | +11.5% | +9.1% | +5.7% |
| DGX Spark · MIRA Procedure Camera | +2.2% | -0.2% | -1.9% | -0.4% |
| DGX Spark · MIRA Room Camera | -4.4% | -7.2% | -8.7% | -10.9% |

## Stage and FPS changes

The same paired median calculation, using **P99** for each latency stage and observed viewer FPS. Positive FPS changes favor SDK 5. BGR8 uses pack/upload for Encode/Decode. Independent stage percentiles do not sum to Total.

| Patient · Camera | Encode | Transport | Decode | FPS |
| --- | --- | --- | --- | --- |
| x86 · MIRA Procedure Camera | -6.5% | -2.1% | -0.6% | +0.4% |
| x86 · MIRA Room Camera | -1.1% | +1.6% | +0.7% | 0.0% |
| x86 · Logitech BRIO Camera | 0.0% | -3.0% | +5.0% | +38.1% |
| Thor · IMX274 Camera | +2.5% | +9.5% | -4.4% | 0.0% |
| DGX Spark · MIRA Procedure Camera | -12.3% | +1.6% | +5.5% | +1.3% |
| DGX Spark · MIRA Room Camera | -8.5% | -4.9% | -1.3% | +1.2% |

## Measurements

Each chart has **FHD, QHD and 4K columns** and **P50, P95, P99 and P99.9 rows**. Within each codec, **SDK 5 is on the left and SDK 4 on the right**. Colors split latency into Encode, Transport, Decode and Other; Other includes preparation, queues and display handoff. Labels above each pair read **SDK 5 / SDK 4**, in milliseconds. Each stack uses matched contributions at that SDK’s total percentile, so its parts sum to its total.

Table cells read **SDK 4 → SDK 5**. **P50–P99.9 show measured total latency in milliseconds**; FPS is the observed Holoviz viewer rate. CC = codec. H.264/H.265 rows are highlighted. The SDK reports include frame sizes and individual stage measurements.

<details open>
<summary>

### x86 (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5 and SDK 4 paired latency breakdowns: x86 patient, x86 surgeon, MIRA Procedure Camera](../benchmarks/figures/sdk-comparison-mira-host-procedure.svg)

<table>
  <thead>
    <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">P50</th><th align="right">P95</th><th align="right">P99</th><th align="right">P99.9</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.88 → 26.86</td><td align="right">18.54 → 20.08</td><td align="right">24.24 → 25.57</td><td align="right">27.02 → 29.00</td><td align="right">29.66 → 31.70</td></tr>
    <tr><td>nvJPEG</td><td align="right">26.88 → 27.18</td><td align="right">14.60 → 14.82</td><td align="right">16.40 → 16.56</td><td align="right">18.01 → 18.11</td><td align="right">20.66 → 20.78</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>27.43 → 27.45</strong></td><td align="right"><strong>12.72 → 13.09</strong></td><td align="right"><strong>15.16 → 15.33</strong></td><td align="right"><strong>15.80 → 16.15</strong></td><td align="right"><strong>21.47 → 23.40</strong></td></tr>
    <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.81 → 24.03</td><td align="right">32.06 → 32.12</td><td align="right">42.28 → 41.23</td><td align="right">48.22 → 45.73</td><td align="right">58.23 → 53.13</td></tr>
    <tr><td>nvJPEG</td><td align="right">24.78 → 24.71</td><td align="right">18.87 → 18.84</td><td align="right">23.14 → 22.14</td><td align="right">24.66 → 24.21</td><td align="right">29.65 → 24.96</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>25.00 → 25.00</strong></td><td align="right"><strong>18.14 → 18.33</strong></td><td align="right"><strong>20.74 → 20.90</strong></td><td align="right"><strong>22.44 → 22.48</strong></td><td align="right"><strong>24.93 → 24.04</strong></td></tr>
    <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.61 → 14.58</td><td align="right">73.72 → 77.59</td><td align="right">90.50 → 98.70</td><td align="right">103.59 → 109.25</td><td align="right">137.49 → 122.56</td></tr>
    <tr><td>nvJPEG</td><td align="right">15.55 → 15.66</td><td align="right">37.51 → 38.39</td><td align="right">43.57 → 43.34</td><td align="right">47.47 → 47.34</td><td align="right">52.93 → 55.00</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>14.93 → 15.47</strong></td><td align="right"><strong>42.06 → 40.15</strong></td><td align="right"><strong>49.63 → 46.28</strong></td><td align="right"><strong>53.18 → 49.49</strong></td><td align="right"><strong>60.18 → 66.54</strong></td></tr>
    <tr><td><strong>H.265</strong></td><td align="right"><strong>15.10 → 15.71</strong></td><td align="right"><strong>41.18 → 39.00</strong></td><td align="right"><strong>47.81 → 45.18</strong></td><td align="right"><strong>51.14 → 48.56</strong></td><td align="right"><strong>53.20 → 53.78</strong></td></tr>
  </tbody>
</table>

</details>

<details>
<summary>

### x86 (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5 and SDK 4 paired latency breakdowns: x86 patient, x86 surgeon, MIRA Room Camera](../benchmarks/figures/sdk-comparison-mira-host-room.svg)

<table>
  <thead>
    <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">P50</th><th align="right">P95</th><th align="right">P99</th><th align="right">P99.9</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.65 → 26.63</td><td align="right">20.13 → 20.83</td><td align="right">26.13 → 27.21</td><td align="right">27.89 → 28.31</td><td align="right">30.63 → 29.19</td></tr>
    <tr><td>nvJPEG</td><td align="right">26.88 → 26.98</td><td align="right">13.52 → 13.66</td><td align="right">17.51 → 17.40</td><td align="right">18.18 → 18.34</td><td align="right">18.70 → 19.68</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>27.20 → 27.20</strong></td><td align="right"><strong>11.54 → 11.78</strong></td><td align="right"><strong>12.91 → 13.49</strong></td><td align="right"><strong>14.92 → 15.51</strong></td><td align="right"><strong>18.82 → 22.27</strong></td></tr>
    <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.81 → 23.83</td><td align="right">33.14 → 32.37</td><td align="right">46.66 → 46.42</td><td align="right">52.80 → 49.97</td><td align="right">56.80 → 66.36</td></tr>
    <tr><td>nvJPEG</td><td align="right">24.56 → 24.53</td><td align="right">18.73 → 18.83</td><td align="right">20.63 → 20.77</td><td align="right">21.87 → 21.85</td><td align="right">29.98 → 23.40</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>24.78 → 24.77</strong></td><td align="right"><strong>16.88 → 16.97</strong></td><td align="right"><strong>20.11 → 20.03</strong></td><td align="right"><strong>21.17 → 21.14</strong></td><td align="right"><strong>35.88 → 21.82</strong></td></tr>
    <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.60 → 14.58</td><td align="right">80.45 → 71.15</td><td align="right">99.17 → 92.03</td><td align="right">112.11 → 100.70</td><td align="right">132.93 → 112.53</td></tr>
    <tr><td>nvJPEG</td><td align="right">15.55 → 15.53</td><td align="right">32.27 → 33.83</td><td align="right">35.82 → 37.31</td><td align="right">38.59 → 39.58</td><td align="right">41.66 → 45.60</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>14.81 → 15.46</strong></td><td align="right"><strong>34.02 → 32.10</strong></td><td align="right"><strong>39.14 → 37.46</strong></td><td align="right"><strong>40.71 → 39.96</strong></td><td align="right"><strong>48.60 → 46.26</strong></td></tr>
    <tr><td><strong>H.265</strong></td><td align="right"><strong>14.97 → 15.72</strong></td><td align="right"><strong>32.87 → 31.51</strong></td><td align="right"><strong>37.76 → 36.54</strong></td><td align="right"><strong>40.63 → 38.79</strong></td><td align="right"><strong>44.69 → 62.60</strong></td></tr>
  </tbody>
</table>

</details>

<details>
<summary>

### x86 (Patient) → x86 (Surgeon): Logitech BRIO Camera

</summary>

![SDK 5 and SDK 4 paired latency breakdowns: x86 patient, x86 surgeon, Logitech BRIO Camera](../benchmarks/figures/sdk-comparison-brio-host-usb-1e29b43c150f.svg)

<table>
  <thead>
    <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">P50</th><th align="right">P95</th><th align="right">P99</th><th align="right">P99.9</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">16.87 → 29.83</td><td align="right">10.69 → 9.73</td><td align="right">15.25 → 14.72</td><td align="right">15.63 → 15.40</td><td align="right">16.27 → 16.91</td></tr>
    <tr><td>nvJPEG</td><td align="right">16.95 → 29.85</td><td align="right">4.15 → 4.05</td><td align="right">5.00 → 4.65</td><td align="right">5.36 → 5.14</td><td align="right">5.88 → 5.38</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>16.88 → 29.85</strong></td><td align="right"><strong>4.98 → 4.75</strong></td><td align="right"><strong>5.63 → 5.54</strong></td><td align="right"><strong>5.97 → 5.86</strong></td><td align="right"><strong>6.30 → 6.40</strong></td></tr>
    <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">29.83 → 29.83</td><td align="right">15.22 → 15.06</td><td align="right">21.66 → 22.33</td><td align="right">24.88 → 24.56</td><td align="right">35.96 → 39.42</td></tr>
    <tr><td>nvJPEG</td><td align="right">29.85 → 29.85</td><td align="right">5.84 → 5.28</td><td align="right">6.74 → 5.92</td><td align="right">7.56 → 6.31</td><td align="right">7.97 → 7.23</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85 → 29.85</strong></td><td align="right"><strong>6.40 → 6.50</strong></td><td align="right"><strong>7.13 → 7.03</strong></td><td align="right"><strong>7.63 → 7.36</strong></td><td align="right"><strong>8.38 → 7.74</strong></td></tr>
    <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.70 → 29.85</td><td align="right">29.95 → 40.95</td><td align="right">44.37 → 52.11</td><td align="right">52.43 → 59.53</td><td align="right">66.10 → 68.91</td></tr>
    <tr><td>nvJPEG</td><td align="right">16.70 → 29.71</td><td align="right">9.15 → 8.45</td><td align="right">9.94 → 9.52</td><td align="right">11.59 → 10.84</td><td align="right">12.12 → 12.35</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>29.95 → 29.97</strong></td><td align="right"><strong>11.26 → 10.99</strong></td><td align="right"><strong>12.25 → 11.65</strong></td><td align="right"><strong>13.88 → 13.27</strong></td><td align="right"><strong>18.12 → 17.11</strong></td></tr>
    <tr><td><strong>H.265</strong></td><td align="right"><strong>29.94 → 29.97</strong></td><td align="right"><strong>10.70 → 10.31</strong></td><td align="right"><strong>11.58 → 11.07</strong></td><td align="right"><strong>13.25 → 12.62</strong></td><td align="right"><strong>18.90 → 15.91</strong></td></tr>
  </tbody>
</table>

</details>

<details open>
<summary>

### Thor (Patient) → x86 (Surgeon): IMX274 Camera

</summary>

![SDK 5 and SDK 4 paired latency breakdowns: Thor patient, x86 surgeon, IMX274 Camera](../benchmarks/figures/sdk-comparison-imx274-thor-hsb-192.168.0.2-0.svg)

<table>
  <thead>
    <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">P50</th><th align="right">P95</th><th align="right">P99</th><th align="right">P99.9</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">59.64 → 45.96</td><td align="right">30.53 → 51.12</td><td align="right">36.45 → 62.93</td><td align="right">39.20 → 78.94</td><td align="right">42.61 → 83.69</td></tr>
    <tr><td>nvJPEG</td><td align="right">59.68 → 59.66</td><td align="right">14.65 → 15.77</td><td align="right">16.03 → 18.16</td><td align="right">16.59 → 19.17</td><td align="right">18.11 → 20.13</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>59.66 → 59.64</strong></td><td align="right"><strong>14.77 → 15.94</strong></td><td align="right"><strong>16.90 → 18.85</strong></td><td align="right"><strong>17.72 → 19.91</strong></td><td align="right"><strong>18.81 → 22.62</strong></td></tr>
    <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.23 → 15.16</td><td align="right">133.29 → 141.53</td><td align="right">154.25 → 162.18</td><td align="right">161.21 → 171.34</td><td align="right">165.47 → 174.61</td></tr>
    <tr><td>nvJPEG</td><td align="right">59.84 → 59.90</td><td align="right">24.99 → 26.83</td><td align="right">31.07 → 35.00</td><td align="right">33.55 → 36.60</td><td align="right">35.95 → 38.00</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>60.12 → 60.11</strong></td><td align="right"><strong>18.79 → 18.24</strong></td><td align="right"><strong>20.09 → 19.68</strong></td><td align="right"><strong>20.72 → 20.62</strong></td><td align="right"><strong>25.07 → 25.41</strong></td></tr>
    <tr><td><strong>H.265</strong></td><td align="right"><strong>60.11 → 60.12</strong></td><td align="right"><strong>18.34 → 18.35</strong></td><td align="right"><strong>20.24 → 20.18</strong></td><td align="right"><strong>21.24 → 21.26</strong></td><td align="right"><strong>23.48 → 24.18</strong></td></tr>
  </tbody>
</table>

</details>

<details>
<summary>

### DGX Spark (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5 and SDK 4 paired latency breakdowns: DGX Spark patient, x86 surgeon, MIRA Procedure Camera](../benchmarks/figures/sdk-comparison-mira-spark-procedure.svg)

<table>
  <thead>
    <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">P50</th><th align="right">P95</th><th align="right">P99</th><th align="right">P99.9</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.65 → 15.78</td><td align="right">25.60 → 24.10</td><td align="right">33.53 → 31.74</td><td align="right">35.48 → 34.51</td><td align="right">37.58 → 36.04</td></tr>
    <tr><td>nvJPEG</td><td align="right">15.38 → 15.58</td><td align="right">15.39 → 13.56</td><td align="right">20.66 → 17.43</td><td align="right">21.74 → 18.44</td><td align="right">22.63 → 19.43</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>15.57 → 15.67</strong></td><td align="right"><strong>13.44 → 11.80</strong></td><td align="right"><strong>18.69 → 15.31</strong></td><td align="right"><strong>19.34 → 15.87</strong></td><td align="right"><strong>20.24 → 16.45</strong></td></tr>
    <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.38 → 13.55</td><td align="right">41.35 → 42.84</td><td align="right">55.51 → 56.78</td><td align="right">57.81 → 60.20</td><td align="right">60.89 → 64.39</td></tr>
    <tr><td>nvJPEG</td><td align="right">13.15 → 13.33</td><td align="right">19.36 → 19.09</td><td align="right">25.08 → 24.04</td><td align="right">26.22 → 25.19</td><td align="right">34.50 → 26.41</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>13.37 → 13.57</strong></td><td align="right"><strong>16.11 → 16.87</strong></td><td align="right"><strong>22.86 → 22.74</strong></td><td align="right"><strong>24.32 → 23.74</strong></td><td align="right"><strong>24.85 → 24.65</strong></td></tr>
    <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.10 → 8.25</td><td align="right">112.86 → 113.68</td><td align="right">170.68 → 170.73</td><td align="right">179.13 → 176.54</td><td align="right">182.50 → 182.43</td></tr>
    <tr><td>nvJPEG</td><td align="right">8.12 → 8.20</td><td align="right">49.06 → 51.16</td><td align="right">87.48 → 87.96</td><td align="right">92.81 → 92.87</td><td align="right">95.82 → 96.78</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>8.22 → 9.12</strong></td><td align="right"><strong>52.42 → 87.00</strong></td><td align="right"><strong>92.24 → 151.57</strong></td><td align="right"><strong>97.72 → 152.90</strong></td><td align="right"><strong>104.41 → 155.12</strong></td></tr>
    <tr><td><strong>H.265</strong></td><td align="right"><strong>8.46 → 9.13</strong></td><td align="right"><strong>50.32 → 88.10</strong></td><td align="right"><strong>83.59 → 151.07</strong></td><td align="right"><strong>92.55 → 153.72</strong></td><td align="right"><strong>102.33 → 155.64</strong></td></tr>
  </tbody>
</table>

</details>

<details>
<summary>

### DGX Spark (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5 and SDK 4 paired latency breakdowns: DGX Spark patient, x86 surgeon, MIRA Room Camera](../benchmarks/figures/sdk-comparison-mira-spark-room.svg)

<table>
  <thead>
    <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">P50</th><th align="right">P95</th><th align="right">P99</th><th align="right">P99.9</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.50 → 15.66</td><td align="right">26.07 → 24.83</td><td align="right">32.78 → 29.96</td><td align="right">33.81 → 30.88</td><td align="right">34.83 → 34.43</td></tr>
    <tr><td>nvJPEG</td><td align="right">15.38 → 15.45</td><td align="right">14.87 → 12.82</td><td align="right">18.93 → 15.85</td><td align="right">19.92 → 16.98</td><td align="right">20.76 → 17.51</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>15.45 → 15.53</strong></td><td align="right"><strong>12.50 → 10.58</strong></td><td align="right"><strong>17.41 → 13.60</strong></td><td align="right"><strong>18.03 → 14.39</strong></td><td align="right"><strong>18.37 → 14.92</strong></td></tr>
    <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.26 → 13.43</td><td align="right">41.88 → 41.89</td><td align="right">52.76 → 51.95</td><td align="right">56.20 → 54.66</td><td align="right">60.08 → 56.40</td></tr>
    <tr><td>nvJPEG</td><td align="right">13.15 → 13.33</td><td align="right">17.51 → 16.80</td><td align="right">24.93 → 23.48</td><td align="right">27.24 → 24.88</td><td align="right">44.59 → 29.91</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>13.25 → 13.45</strong></td><td align="right"><strong>15.85 → 15.68</strong></td><td align="right"><strong>22.57 → 21.94</strong></td><td align="right"><strong>23.76 → 23.39</strong></td><td align="right"><strong>24.54 → 24.40</strong></td></tr>
    <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.10 → 8.18</td><td align="right">98.18 → 99.88</td><td align="right">134.16 → 134.58</td><td align="right">216.52 → 259.78</td><td align="right">302.38 → 301.22</td></tr>
    <tr><td>nvJPEG</td><td align="right">8.12 → 8.15</td><td align="right">44.75 → 47.37</td><td align="right">71.86 → 70.69</td><td align="right">233.07 → 225.81</td><td align="right">264.16 → 258.92</td></tr>
    <tr><td><strong>H.264</strong></td><td align="right"><strong>8.22 → 9.12</strong></td><td align="right"><strong>43.39 → 24.47</strong></td><td align="right"><strong>73.66 → 27.78</strong></td><td align="right"><strong>76.34 → 28.73</strong></td><td align="right"><strong>256.76 → 30.22</strong></td></tr>
    <tr><td><strong>H.265</strong></td><td align="right"><strong>8.45 → 9.12</strong></td><td align="right"><strong>39.14 → 23.31</strong></td><td align="right"><strong>71.71 → 28.33</strong></td><td align="right"><strong>75.40 → 29.82</strong></td><td align="right"><strong>186.61 → 31.30</strong></td></tr>
  </tbody>
</table>

</details>

## Interpretation and limits

- Total starts at application buffer availability and ends at Holoviz handoff; it excludes sensor exposure and physical display scanout. Changes in Total include preparation and queues as well as encoding, transport and decoding.
- These are separate, single runs per configuration. Most measured for 60 seconds after warmup; earlier 10,000-sample runs were retained. Duration, frame count, background load and power/clocks were not controlled identically. P99.9 is especially sensitive to sparse samples. Differences do not establish an SDK-only cause or statistical significance.
- Remote totals use synchronized or estimated clock offsets. Bounds are recorded in the CSV; small differences may be within timing uncertainty. Compare latency together with FPS, especially for simulation.
- Codec settings match the source reports: NVENC P1, ultra-low-latency, QP 24, independent frames; nvJPEG quality 85. BRIO capture formats vary with resolution. This is not a comparison at equal visual quality.

<details>
<summary>

## Appendix: WebRTC

</summary>

H.264 in Chromium on the x86 surgeon. Values below are median paired percentage changes by camera, using the same calculation as the Holoviz summary. Browser Total includes delivery and scheduling; hardware decoding was not confirmed. Full per-resolution values are in the SDK report appendices.

| Patient · Camera | P50 | P95 | P99 | P99.9 |
| --- | --- | --- | --- | --- |
| x86 · MIRA Procedure Camera | -1.1% | -2.3% | -1.7% | -1.6% |
| x86 · MIRA Room Camera | -2.0% | +1.5% | +0.8% | -9.2% |
| x86 · Logitech BRIO Camera | +45.5% | -24.2% | -24.5% | +7.4% |
| Thor · IMX274 Camera | -3.0% | -5.9% | -5.7% | -4.8% |
| DGX Spark · MIRA Procedure Camera | -3.3% | -2.3% | -2.7% | -1.9% |
| DGX Spark · MIRA Room Camera | -1.9% | -2.6% | -4.4% | -3.3% |

<details open>
<summary>

### x86 (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5 and SDK 4 paired WebRTC latency breakdowns: x86 patient, x86 surgeon, MIRA Procedure Camera](../benchmarks/figures/sdk-comparison-mira-host-procedure-webrtc.svg)

</details>

<details>
<summary>

### x86 (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5 and SDK 4 paired WebRTC latency breakdowns: x86 patient, x86 surgeon, MIRA Room Camera](../benchmarks/figures/sdk-comparison-mira-host-room-webrtc.svg)

</details>

<details>
<summary>

### x86 (Patient) → x86 (Surgeon): Logitech BRIO Camera

</summary>

![SDK 5 and SDK 4 paired WebRTC latency breakdowns: x86 patient, x86 surgeon, Logitech BRIO Camera](../benchmarks/figures/sdk-comparison-brio-host-usb-1e29b43c150f-webrtc.svg)

</details>

<details open>
<summary>

### Thor (Patient) → x86 (Surgeon): IMX274 Camera

</summary>

![SDK 5 and SDK 4 paired WebRTC latency breakdowns: Thor patient, x86 surgeon, IMX274 Camera](../benchmarks/figures/sdk-comparison-imx274-thor-hsb-192.168.0.2-0-webrtc.svg)

</details>

<details>
<summary>

### DGX Spark (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5 and SDK 4 paired WebRTC latency breakdowns: DGX Spark patient, x86 surgeon, MIRA Procedure Camera](../benchmarks/figures/sdk-comparison-mira-spark-procedure-webrtc.svg)

</details>

<details>
<summary>

### DGX Spark (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5 and SDK 4 paired WebRTC latency breakdowns: DGX Spark patient, x86 surgeon, MIRA Room Camera](../benchmarks/figures/sdk-comparison-mira-spark-room-webrtc.svg)

</details>

</details>
