# SDK 4 vs SDK 5 benchmark comparison

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}, "MD033": {"allowed_elements": ["details", "summary", "table", "thead", "tbody", "tr", "th", "td", "strong"]}} -->

October 2026 · Holoscan **4.6.0** vs **5.0.0a3 (public EA3)**.

SDK 5 measurements collected October 12, 2026 on public EA3. The SDK 4 baseline is retained from October 2, 2026.

[SDK 5 benchmark](../BENCHMARK.md) · [SDK 4 benchmark](BENCHMARK_SDK4.md) · [Measurements](../benchmarks/results/summary.csv)

**The surgeon always runs on the x86 workstation.** Matching results use the same patient host, camera, resolution, codec and receiver. This report pairs **57 Holoviz camera results** and **17 WebRTC camera results** per SDK; both MIRA cameras stream simultaneously.

## P99 overview

SDK 5 EA3 has lower P99 total latency in **22 of 57** matched Holoviz results. The median per-result change is **+7.3%**. These runs also include application changes since the SDK 4 baseline; differences cannot be attributed to the SDK alone.

![P99 total latency change from SDK 4 to SDK 5 for every matched source, resolution and codec](../benchmarks/figures/sdk-comparison.svg)

**Change = (SDK 5 / SDK 4 − 1) × 100.** Negative latency changes favor SDK 5. Gray cells were not tested. FHD = 1920×1080; QHD = 2560×1440; 4K = 3840×2160. H.265 was tested only at 4K.

## Total latency change

Each cell is the median percentage change across that camera’s matched resolution/codec configurations. These are summaries of per-configuration changes, not percentiles of pooled frames. Each configuration has equal weight.

| Patient · Camera                  | P50     | P95     | P99     | P99.9   |
| --------------------------------- | ------- | ------- | ------- | ------- |
| x86 · MIRA Procedure Camera       | -4.2%   | +0.4%   | +2.3%   | +2.5%   |
| x86 · MIRA Room Camera            | -10.8%  | -1.7%   | +3.9%   | +1.2%   |
| x86 · Logitech BRIO Camera        | +4.0%   | +2.8%   | +16.0%  | +20.7%  |
| Thor · IMX274 Camera              | +21.2%  | +20.2%  | +20.6%  | +44.8%  |
| DGX Spark · MIRA Procedure Camera | +120.0% | +131.7% | +133.1% | +128.1% |
| DGX Spark · MIRA Room Camera      | -26.7%  | -31.9%  | -33.3%  | -38.3%  |

## Stage and FPS changes

The same paired median calculation, using **P99** for each latency stage and observed viewer FPS. Positive FPS changes favor SDK 5. BGR8 uses pack/upload for Encode/Decode. Independent stage percentiles do not sum to Total.

| Patient · Camera                  | Encode | Transport | Decode | FPS    |
| --------------------------------- | ------ | --------- | ------ | ------ |
| x86 · MIRA Procedure Camera       | -6.2%  | +20.5%    | -5.9%  | +12.0% |
| x86 · MIRA Room Camera            | +0.9%  | +41.5%    | -28.6% | +12.1% |
| x86 · Logitech BRIO Camera        | +6.8%  | +30.5%    | +19.2% | -30.7% |
| Thor · IMX274 Camera              | -6.3%  | +93.1%    | +63.7% | -0.2%  |
| DGX Spark · MIRA Procedure Camera | -52.0% | +30.8%    | +42.3% | +8.4%  |
| DGX Spark · MIRA Room Camera      | -42.4% | +55.2%    | +57.4% | +8.3%  |

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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.88 → 28.91</td><td align="right">18.54 → 17.69</td><td align="right">24.24 → 28.99</td><td align="right">27.02 → 36.85</td><td align="right">29.66 → 44.11</td></tr>
        <tr><td>nvJPEG</td><td align="right">26.88 → 28.23</td><td align="right">14.60 → 12.08</td><td align="right">16.40 → 16.37</td><td align="right">18.01 → 18.29</td><td align="right">20.66 → 23.65</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.43 → 27.54</strong></td><td align="right"><strong>12.72 → 11.12</strong></td><td align="right"><strong>15.16 → 16.24</strong></td><td align="right"><strong>15.80 → 19.82</strong></td><td align="right"><strong>21.47 → 23.30</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.81 → 28.21</td><td align="right">32.06 → 31.01</td><td align="right">42.28 → 42.69</td><td align="right">48.22 → 50.11</td><td align="right">58.23 → 57.87</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.78 → 27.96</td><td align="right">18.87 → 18.15</td><td align="right">23.14 → 21.93</td><td align="right">24.66 → 25.38</td><td align="right">29.65 → 29.55</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>25.00 → 27.76</strong></td><td align="right"><strong>18.14 → 17.01</strong></td><td align="right"><strong>20.74 → 21.06</strong></td><td align="right"><strong>22.44 → 24.08</strong></td><td align="right"><strong>24.93 → 29.27</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.61 → 16.21</td><td align="right">73.72 → 79.51</td><td align="right">90.50 → 95.13</td><td align="right">103.59 → 105.15</td><td align="right">137.49 → 111.98</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.55 → 19.65</td><td align="right">37.51 → 32.54</td><td align="right">43.57 → 38.66</td><td align="right">47.47 → 43.01</td><td align="right">52.93 → 47.31</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.93 → 17.50</strong></td><td align="right"><strong>42.06 → 40.63</strong></td><td align="right"><strong>49.63 → 48.32</strong></td><td align="right"><strong>53.18 → 51.46</strong></td><td align="right"><strong>60.18 → 53.19</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.10 → 17.45</strong></td><td align="right"><strong>41.18 → 39.63</strong></td><td align="right"><strong>47.81 → 47.36</strong></td><td align="right"><strong>51.14 → 51.63</strong></td><td align="right"><strong>53.20 → 56.01</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.65 → 28.65</td><td align="right">20.13 → 19.06</td><td align="right">26.13 → 31.74</td><td align="right">27.89 → 38.57</td><td align="right">30.63 → 44.29</td></tr>
        <tr><td>nvJPEG</td><td align="right">26.88 → 28.00</td><td align="right">13.52 → 10.94</td><td align="right">17.51 → 16.64</td><td align="right">18.18 → 19.68</td><td align="right">18.70 → 23.02</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.20 → 27.31</strong></td><td align="right"><strong>11.54 → 10.11</strong></td><td align="right"><strong>12.91 → 16.56</strong></td><td align="right"><strong>14.92 → 20.37</strong></td><td align="right"><strong>18.82 → 25.11</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.81 → 27.98</td><td align="right">33.14 → 33.31</td><td align="right">46.66 → 47.43</td><td align="right">52.80 → 52.61</td><td align="right">56.80 → 57.20</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.56 → 27.75</td><td align="right">18.73 → 17.54</td><td align="right">20.63 → 21.33</td><td align="right">21.87 → 24.80</td><td align="right">29.98 → 30.48</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>24.78 → 27.55</strong></td><td align="right"><strong>16.88 → 15.33</strong></td><td align="right"><strong>20.11 → 20.85</strong></td><td align="right"><strong>21.17 → 25.19</strong></td><td align="right"><strong>35.88 → 33.08</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.60 → 16.08</td><td align="right">80.45 → 69.87</td><td align="right">99.17 → 87.42</td><td align="right">112.11 → 100.18</td><td align="right">132.93 → 125.18</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.55 → 19.46</td><td align="right">32.27 → 30.17</td><td align="right">35.82 → 33.59</td><td align="right">38.59 → 36.51</td><td align="right">41.66 → 42.53</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.81 → 17.35</strong></td><td align="right"><strong>34.02 → 29.29</strong></td><td align="right"><strong>39.14 → 33.90</strong></td><td align="right"><strong>40.71 → 36.40</strong></td><td align="right"><strong>48.60 → 43.54</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>14.97 → 17.32</strong></td><td align="right"><strong>32.87 → 28.54</strong></td><td align="right"><strong>37.76 → 32.45</strong></td><td align="right"><strong>40.63 → 35.39</strong></td><td align="right"><strong>44.69 → 37.52</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">16.87 → 14.96</td><td align="right">10.69 → 30.42</td><td align="right">15.25 → 35.86</td><td align="right">15.63 → 39.96</td><td align="right">16.27 → 46.42</td></tr>
        <tr><td>nvJPEG</td><td align="right">16.95 → 14.98</td><td align="right">4.15 → 7.96</td><td align="right">5.00 → 9.56</td><td align="right">5.36 → 11.33</td><td align="right">5.88 → 12.12</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>16.88 → 14.96</strong></td><td align="right"><strong>4.98 → 8.85</strong></td><td align="right"><strong>5.63 → 10.78</strong></td><td align="right"><strong>5.97 → 11.85</strong></td><td align="right"><strong>6.30 → 12.61</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">29.83 → 14.95</td><td align="right">15.22 → 24.50</td><td align="right">21.66 → 38.40</td><td align="right">24.88 → 42.66</td><td align="right">35.96 → 50.66</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85 → 14.96</td><td align="right">5.84 → 5.53</td><td align="right">6.74 → 6.24</td><td align="right">7.56 → 6.83</td><td align="right">7.97 → 8.20</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85 → 14.96</strong></td><td align="right"><strong>6.40 → 6.84</strong></td><td align="right"><strong>7.13 → 7.98</strong></td><td align="right"><strong>7.63 → 10.14</strong></td><td align="right"><strong>8.38 → 11.49</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.70 → 14.93</td><td align="right">29.95 → 30.26</td><td align="right">44.37 → 41.52</td><td align="right">52.43 → 45.87</td><td align="right">66.10 → 52.39</td></tr>
        <tr><td>nvJPEG</td><td align="right">16.70 → 14.95</td><td align="right">9.15 → 7.49</td><td align="right">9.94 → 8.17</td><td align="right">11.59 → 9.82</td><td align="right">12.12 → 12.64</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.95 → 14.95</strong></td><td align="right"><strong>11.26 → 9.73</strong></td><td align="right"><strong>12.25 → 11.13</strong></td><td align="right"><strong>13.88 → 13.75</strong></td><td align="right"><strong>18.12 → 15.83</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>29.94 → 14.95</strong></td><td align="right"><strong>10.70 → 8.96</strong></td><td align="right"><strong>11.58 → 9.70</strong></td><td align="right"><strong>13.25 → 11.18</strong></td><td align="right"><strong>18.90 → 12.69</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">59.64 → 54.42</td><td align="right">30.53 → 50.69</td><td align="right">36.45 → 59.14</td><td align="right">39.20 → 67.95</td><td align="right">42.61 → 83.99</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.68 → 59.94</td><td align="right">14.65 → 16.24</td><td align="right">16.03 → 18.35</td><td align="right">16.59 → 19.35</td><td align="right">18.11 → 24.88</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.66 → 59.54</strong></td><td align="right"><strong>14.77 → 18.55</strong></td><td align="right"><strong>16.90 → 21.12</strong></td><td align="right"><strong>17.72 → 22.35</strong></td><td align="right"><strong>18.81 → 31.60</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.23 → 15.23</td><td align="right">133.29 → 134.43</td><td align="right">154.25 → 153.69</td><td align="right">161.21 → 159.28</td><td align="right">165.47 → 174.22</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.84 → 59.71</td><td align="right">24.99 → 28.06</td><td align="right">31.07 → 34.29</td><td align="right">33.55 → 36.73</td><td align="right">35.95 → 44.95</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.12 → 60.17</strong></td><td align="right"><strong>18.79 → 24.22</strong></td><td align="right"><strong>20.09 → 26.15</strong></td><td align="right"><strong>20.72 → 27.20</strong></td><td align="right"><strong>25.07 → 36.30</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>60.11 → 59.74</strong></td><td align="right"><strong>18.34 → 22.23</strong></td><td align="right"><strong>20.24 → 24.32</strong></td><td align="right"><strong>21.24 → 25.61</strong></td><td align="right"><strong>23.48 → 35.62</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.65 → 17.33</td><td align="right">25.60 → 53.02</td><td align="right">33.53 → 81.17</td><td align="right">35.48 → 86.49</td><td align="right">37.58 → 90.82</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.38 → 17.38</td><td align="right">15.39 → 35.84</td><td align="right">20.66 → 64.41</td><td align="right">21.74 → 65.54</td><td align="right">22.63 → 66.98</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.57 → 17.36</strong></td><td align="right"><strong>13.44 → 57.40</strong></td><td align="right"><strong>18.69 → 62.84</strong></td><td align="right"><strong>19.34 → 64.92</strong></td><td align="right"><strong>20.24 → 66.41</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.38 → 13.95</td><td align="right">41.35 → 48.01</td><td align="right">55.51 → 122.90</td><td align="right">57.81 → 128.57</td><td align="right">60.89 → 130.68</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.15 → 13.90</td><td align="right">19.36 → 50.14</td><td align="right">25.08 → 91.96</td><td align="right">26.22 → 93.48</td><td align="right">34.50 → 96.11</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.37 → 13.91</strong></td><td align="right"><strong>16.11 → 51.84</strong></td><td align="right"><strong>22.86 → 94.37</strong></td><td align="right"><strong>24.32 → 95.82</strong></td><td align="right"><strong>24.85 → 97.54</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.10 → 8.91</td><td align="right">112.86 → 187.24</td><td align="right">170.68 → 278.67</td><td align="right">179.13 → 301.89</td><td align="right">182.50 → 309.70</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.12 → 8.81</td><td align="right">49.06 → 98.10</td><td align="right">87.48 → 177.46</td><td align="right">92.81 → 180.15</td><td align="right">95.82 → 182.36</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.22 → 8.90</strong></td><td align="right"><strong>52.42 → 170.77</strong></td><td align="right"><strong>92.24 → 177.17</strong></td><td align="right"><strong>97.72 → 178.52</strong></td><td align="right"><strong>104.41 → 181.50</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.46 → 8.90</strong></td><td align="right"><strong>50.32 → 99.34</strong></td><td align="right"><strong>83.59 → 178.84</strong></td><td align="right"><strong>92.55 → 180.30</strong></td><td align="right"><strong>102.33 → 181.58</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.50 → 17.30</td><td align="right">26.07 → 25.20</td><td align="right">32.78 → 30.22</td><td align="right">33.81 → 34.19</td><td align="right">34.83 → 37.62</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.38 → 17.36</td><td align="right">14.87 → 9.83</td><td align="right">18.93 → 12.60</td><td align="right">19.92 → 13.20</td><td align="right">20.76 → 15.81</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.45 → 17.38</strong></td><td align="right"><strong>12.50 → 9.77</strong></td><td align="right"><strong>17.41 → 12.13</strong></td><td align="right"><strong>18.03 → 12.57</strong></td><td align="right"><strong>18.37 → 13.19</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.26 → 13.81</td><td align="right">41.88 → 38.38</td><td align="right">52.76 → 45.57</td><td align="right">56.20 → 47.83</td><td align="right">60.08 → 51.81</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.15 → 13.91</td><td align="right">17.51 → 11.99</td><td align="right">24.93 → 14.84</td><td align="right">27.24 → 15.59</td><td align="right">44.59 → 19.63</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.25 → 13.91</strong></td><td align="right"><strong>15.85 → 13.18</strong></td><td align="right"><strong>22.57 → 15.69</strong></td><td align="right"><strong>23.76 → 16.54</strong></td><td align="right"><strong>24.54 → 18.08</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.10 → 8.83</td><td align="right">98.18 → 90.48</td><td align="right">134.16 → 136.62</td><td align="right">216.52 → 145.44</td><td align="right">302.38 → 155.85</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.12 → 8.83</td><td align="right">44.75 → 20.45</td><td align="right">71.86 → 22.09</td><td align="right">233.07 → 22.63</td><td align="right">264.16 → 26.88</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.22 → 8.87</strong></td><td align="right"><strong>43.39 → 21.59</strong></td><td align="right"><strong>73.66 → 23.75</strong></td><td align="right"><strong>76.34 → 24.53</strong></td><td align="right"><strong>256.76 → 26.57</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.45 → 8.88</strong></td><td align="right"><strong>39.14 → 24.79</strong></td><td align="right"><strong>71.71 → 26.28</strong></td><td align="right"><strong>75.40 → 27.53</strong></td><td align="right"><strong>186.61 → 29.92</strong></td></tr>
    </tbody>
</table>

</details>

## Interpretation and limits

- Total starts at application buffer availability and ends at Holoviz handoff; it excludes sensor exposure and physical display scanout. Changes in Total include preparation and queues as well as encoding, transport and decoding.
- These are separate, single runs per configuration. All EA3 configurations measured for 60 seconds after 30 seconds of warmup. The SDK 4 baseline retains its original durations, including earlier 10,000-sample runs. Application code, simulation scenes, duration, frame count, background load and power/clocks were not controlled identically between collection dates. P99.9 is especially sensitive to sparse samples. Differences do not establish an SDK-only cause or statistical significance.
- Remote totals use synchronized or estimated clock offsets. Bounds are recorded in the CSV; small differences may be within timing uncertainty. Compare latency together with FPS, especially for simulation.
- Refreshed BRIO runs requested 30 FPS but delivered about 15 FPS. The recorded Aperture Priority exposure and enabled dynamic framerate allow the camera to reduce its capture rate in low light. This source-rate difference confounds FPS and latency comparisons with SDK 4; it does not establish an SDK regression.
- Codec settings match the source reports: NVENC P1, ultra-low-latency, QP 24, independent frames; nvJPEG quality 85. BRIO capture formats vary with resolution. This is not a comparison at equal visual quality.

<details>
<summary>

## Appendix: WebRTC

</summary>

H.264 in Chromium on the x86 surgeon. Values below are median paired percentage changes by camera, using the same calculation as the Holoviz summary. Browser Total includes delivery and scheduling; hardware decoding was not confirmed. Full per-resolution values are in the SDK report appendices.

| Patient · Camera                  | P50    | P95    | P99    | P99.9  |
| --------------------------------- | ------ | ------ | ------ | ------ |
| x86 · MIRA Procedure Camera       | -0.4%  | +3.1%  | +2.6%  | +3.1%  |
| x86 · MIRA Room Camera            | +1.2%  | +3.8%  | +3.3%  | -2.1%  |
| x86 · Logitech BRIO Camera        | +89.7% | +18.3% | +21.7% | +23.1% |
| Thor · IMX274 Camera              | +14.3% | +12.8% | +14.5% | +15.3% |
| DGX Spark · MIRA Procedure Camera | +30.7% | +79.1% | +75.5% | +75.3% |
| DGX Spark · MIRA Room Camera      | +11.1% | +4.9%  | +6.0%  | +5.4%  |

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
