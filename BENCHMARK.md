# SDK 5 benchmark

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}, "MD033": {"allowed_elements": ["details", "summary", "table", "thead", "tbody", "tr", "th", "td", "strong"]}} -->

October 2026 · Holoscan `5.0.0a3 (public EA3)` · **48 configurations, 74 camera results**.

SDK 5 measurements collected October 12, 2026 on public EA3. The SDK 4 baseline is retained from October 2, 2026.

Compare resolutions and codecs for each patient source. **The surgeon always runs on the x86 workstation.** The main tables use Holoviz; [WebRTC](#appendix-webrtc) is in the appendix. [SDK 4 report](docs/BENCHMARK_SDK4.md) · [SDK comparison](docs/BENCHMARK_COMPARISON.md).

[Measurements](benchmarks/results/summary.csv) · [Matched-frame breakdowns](benchmarks/results/stages.csv) · [Raw records](benchmarks/results/matrix/) · [Hardware details](benchmarks/results/matrix/hardware-ea3.json)

## Sources and hosts

Titles identify the patient and surgeon roles. **x86** is the Host Machine described below.

| Patient → Surgeon                   | Scenario                 | Camera                   |
| ----------------------------------- | ------------------------ | ------------------------ |
| x86 (Patient) → x86 (Surgeon)       | Same host · Simulation   | MIRA procedure and room  |
| x86 (Patient) → x86 (Surgeon)       | Same host · Physical     | Logitech BRIO webcam     |
| Thor (Patient) → x86 (Surgeon)      | Remote host · Physical   | IMX274 via HSB, sensor 0 |
| DGX Spark (Patient) → x86 (Surgeon) | Remote host · Simulation | MIRA procedure and room  |

Both MIRA cameras stream simultaneously.

Same-host tests run patient and surgeon on the same physical workstation. Remote patient nodes capture, encode and send directly to the surgeon. The patient dashboard/coordinator runs on the x86 workstation in all tests; it does not relay remote video.

| Host      | Hardware                                                                                            | Ethernet link |
| --------- | --------------------------------------------------------------------------------------------------- | ------------: |
| x86       | x86_64 · Intel Core i9-14900K · NVIDIA RTX PRO 6000 Blackwell GPUs (Workstation and Max-Q editions) |     10 Gbit/s |
| Thor      | ARM64 · NVIDIA Thor                                                                                 |      5 Gbit/s |
| DGX Spark | ARM64 · NVIDIA GB10                                                                                 |     10 Gbit/s |

Link rates are the negotiated Ethernet speeds during testing.

| Resolution | Name           | Pixels    |
| ---------- | -------------- | --------- |
| FHD        | Full HD        | 1920×1080 |
| QHD        | Quad HD        | 2560×1440 |
| 4K         | Ultra HD (UHD) | 3840×2160 |

MIRA and BRIO request 30 FPS; IMX274 requests 60 FPS in its native FHD and 4K modes. QHD has no IMX274 result. H.265 is tested only at 4K.

## Reading the charts and tables

Latency is in **milliseconds**. **RES** = resolution; **CC** = codec; **FPS** = viewer frame rate; **FS** = mean transport frame size.

**Total** is measured end-to-end latency, including preparation, queues and display handoff. Table stages are independent percentiles; they need not sum to Total. For BGR8, Encode/Decode mean packing/upload.

<details open>
<summary>

## x86 (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5: x86 patient to x86 surgeon, MIRA Procedure Camera, stacked total latency breakdowns comparing codecs within each resolution](benchmarks/figures/sdk5-mira-host-procedure.svg)

<details>
<summary>

### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.91</td><td align="right">5.93 MiB</td><td align="right">0.53</td><td align="right">6.20</td><td align="right">1.73</td><td align="right">17.69</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.23</td><td align="right">62.0 KiB</td><td align="right">1.99</td><td align="right">0.34</td><td align="right">1.50</td><td align="right">12.08</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.54</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.49</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>1.21</strong></td><td align="right"><strong>11.12</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">28.21</td><td align="right">10.55 MiB</td><td align="right">1.12</td><td align="right">12.40</td><td align="right">2.26</td><td align="right">31.01</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.96</td><td align="right">102.4 KiB</td><td align="right">3.47</td><td align="right">0.39</td><td align="right">3.23</td><td align="right">18.15</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.76</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>4.14</strong></td><td align="right"><strong>0.28</strong></td><td align="right"><strong>1.89</strong></td><td align="right"><strong>17.01</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.21</td><td align="right">23.73 MiB</td><td align="right">2.01</td><td align="right">28.33</td><td align="right">4.43</td><td align="right">79.51</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.65</td><td align="right">209.6 KiB</td><td align="right">4.15</td><td align="right">0.55</td><td align="right">3.99</td><td align="right">32.54</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.50</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>7.50</strong></td><td align="right"><strong>0.31</strong></td><td align="right"><strong>2.66</strong></td><td align="right"><strong>40.63</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.45</strong></td><td align="right"><strong>18.6 KiB</strong></td><td align="right"><strong>6.32</strong></td><td align="right"><strong>0.30</strong></td><td align="right"><strong>2.63</strong></td><td align="right"><strong>39.63</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.91</td><td align="right">5.93 MiB</td><td align="right">1.18</td><td align="right">14.69</td><td align="right">3.32</td><td align="right">28.99</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.23</td><td align="right">62.0 KiB</td><td align="right">5.03</td><td align="right">0.70</td><td align="right">3.72</td><td align="right">16.37</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.54</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>3.71</strong></td><td align="right"><strong>0.59</strong></td><td align="right"><strong>3.25</strong></td><td align="right"><strong>16.24</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">28.21</td><td align="right">10.55 MiB</td><td align="right">2.56</td><td align="right">20.16</td><td align="right">4.04</td><td align="right">42.69</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.96</td><td align="right">102.4 KiB</td><td align="right">6.26</td><td align="right">0.61</td><td align="right">5.58</td><td align="right">21.93</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.76</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>6.17</strong></td><td align="right"><strong>0.45</strong></td><td align="right"><strong>3.75</strong></td><td align="right"><strong>21.06</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.21</td><td align="right">23.73 MiB</td><td align="right">4.57</td><td align="right">43.20</td><td align="right">9.39</td><td align="right">95.13</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.65</td><td align="right">209.6 KiB</td><td align="right">6.51</td><td align="right">1.03</td><td align="right">5.79</td><td align="right">38.66</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.50</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>9.93</strong></td><td align="right"><strong>0.42</strong></td><td align="right"><strong>4.03</strong></td><td align="right"><strong>48.32</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.45</strong></td><td align="right"><strong>18.6 KiB</strong></td><td align="right"><strong>8.68</strong></td><td align="right"><strong>0.45</strong></td><td align="right"><strong>4.48</strong></td><td align="right"><strong>47.36</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.91</td><td align="right">5.93 MiB</td><td align="right">1.45</td><td align="right">20.39</td><td align="right">3.95</td><td align="right">36.85</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.23</td><td align="right">62.0 KiB</td><td align="right">5.61</td><td align="right">1.11</td><td align="right">5.56</td><td align="right">18.29</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.54</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.48</strong></td><td align="right"><strong>0.95</strong></td><td align="right"><strong>4.19</strong></td><td align="right"><strong>19.82</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">28.21</td><td align="right">10.55 MiB</td><td align="right">2.98</td><td align="right">24.23</td><td align="right">4.87</td><td align="right">50.11</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.96</td><td align="right">102.4 KiB</td><td align="right">8.00</td><td align="right">0.90</td><td align="right">6.18</td><td align="right">25.38</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.76</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>7.01</strong></td><td align="right"><strong>0.65</strong></td><td align="right"><strong>4.82</strong></td><td align="right"><strong>24.08</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.21</td><td align="right">23.73 MiB</td><td align="right">5.72</td><td align="right">48.46</td><td align="right">10.59</td><td align="right">105.15</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.65</td><td align="right">209.6 KiB</td><td align="right">7.65</td><td align="right">1.35</td><td align="right">6.28</td><td align="right">43.01</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.50</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>10.72</strong></td><td align="right"><strong>0.57</strong></td><td align="right"><strong>4.20</strong></td><td align="right"><strong>51.46</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.45</strong></td><td align="right"><strong>18.6 KiB</strong></td><td align="right"><strong>8.97</strong></td><td align="right"><strong>0.61</strong></td><td align="right"><strong>4.68</strong></td><td align="right"><strong>51.63</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.91</td><td align="right">5.93 MiB</td><td align="right">2.10</td><td align="right">25.42</td><td align="right">4.86</td><td align="right">44.11</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.23</td><td align="right">62.0 KiB</td><td align="right">7.40</td><td align="right">1.55</td><td align="right">6.26</td><td align="right">23.65</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.54</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>5.20</strong></td><td align="right"><strong>1.22</strong></td><td align="right"><strong>4.99</strong></td><td align="right"><strong>23.30</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">28.21</td><td align="right">10.55 MiB</td><td align="right">3.46</td><td align="right">31.42</td><td align="right">5.84</td><td align="right">57.87</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.96</td><td align="right">102.4 KiB</td><td align="right">9.16</td><td align="right">1.63</td><td align="right">6.77</td><td align="right">29.55</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.76</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>8.28</strong></td><td align="right"><strong>1.06</strong></td><td align="right"><strong>5.84</strong></td><td align="right"><strong>29.27</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.21</td><td align="right">23.73 MiB</td><td align="right">6.39</td><td align="right">54.22</td><td align="right">11.60</td><td align="right">111.98</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.65</td><td align="right">209.6 KiB</td><td align="right">8.67</td><td align="right">1.51</td><td align="right">6.73</td><td align="right">47.31</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.50</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>11.62</strong></td><td align="right"><strong>0.84</strong></td><td align="right"><strong>4.37</strong></td><td align="right"><strong>53.19</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.45</strong></td><td align="right"><strong>18.6 KiB</strong></td><td align="right"><strong>9.93</strong></td><td align="right"><strong>0.85</strong></td><td align="right"><strong>4.86</strong></td><td align="right"><strong>56.01</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

## x86 (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5: x86 patient to x86 surgeon, MIRA Room Camera, stacked total latency breakdowns comparing codecs within each resolution](benchmarks/figures/sdk5-mira-host-room.svg)

<details>
<summary>

### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.65</td><td align="right">5.93 MiB</td><td align="right">0.55</td><td align="right">7.05</td><td align="right">1.53</td><td align="right">19.06</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.00</td><td align="right">68.0 KiB</td><td align="right">2.22</td><td align="right">0.30</td><td align="right">1.83</td><td align="right">10.94</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.31</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>2.51</strong></td><td align="right"><strong>0.25</strong></td><td align="right"><strong>1.05</strong></td><td align="right"><strong>10.11</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">27.98</td><td align="right">10.55 MiB</td><td align="right">1.14</td><td align="right">11.26</td><td align="right">2.26</td><td align="right">33.31</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.75</td><td align="right">108.5 KiB</td><td align="right">3.35</td><td align="right">0.35</td><td align="right">3.43</td><td align="right">17.54</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.55</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>4.01</strong></td><td align="right"><strong>0.26</strong></td><td align="right"><strong>1.47</strong></td><td align="right"><strong>15.33</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.08</td><td align="right">23.73 MiB</td><td align="right">1.77</td><td align="right">27.55</td><td align="right">4.03</td><td align="right">69.87</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.46</td><td align="right">221.7 KiB</td><td align="right">4.84</td><td align="right">0.50</td><td align="right">4.53</td><td align="right">30.17</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.35</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>7.53</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>1.80</strong></td><td align="right"><strong>29.29</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.32</strong></td><td align="right"><strong>36.4 KiB</strong></td><td align="right"><strong>6.27</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>2.25</strong></td><td align="right"><strong>28.54</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.65</td><td align="right">5.93 MiB</td><td align="right">1.26</td><td align="right">14.74</td><td align="right">3.03</td><td align="right">31.74</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.00</td><td align="right">68.0 KiB</td><td align="right">5.10</td><td align="right">0.65</td><td align="right">3.32</td><td align="right">16.64</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.31</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>4.35</strong></td><td align="right"><strong>0.59</strong></td><td align="right"><strong>2.83</strong></td><td align="right"><strong>16.56</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">27.98</td><td align="right">10.55 MiB</td><td align="right">2.43</td><td align="right">18.79</td><td align="right">4.21</td><td align="right">47.43</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.75</td><td align="right">108.5 KiB</td><td align="right">6.19</td><td align="right">0.68</td><td align="right">5.50</td><td align="right">21.33</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.55</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>6.05</strong></td><td align="right"><strong>0.51</strong></td><td align="right"><strong>3.24</strong></td><td align="right"><strong>20.85</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.08</td><td align="right">23.73 MiB</td><td align="right">3.54</td><td align="right">39.47</td><td align="right">6.51</td><td align="right">87.42</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.46</td><td align="right">221.7 KiB</td><td align="right">6.81</td><td align="right">0.68</td><td align="right">5.27</td><td align="right">33.59</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.35</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>9.74</strong></td><td align="right"><strong>0.38</strong></td><td align="right"><strong>2.09</strong></td><td align="right"><strong>33.90</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.32</strong></td><td align="right"><strong>36.4 KiB</strong></td><td align="right"><strong>8.66</strong></td><td align="right"><strong>0.38</strong></td><td align="right"><strong>3.06</strong></td><td align="right"><strong>32.45</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.65</td><td align="right">5.93 MiB</td><td align="right">1.47</td><td align="right">18.56</td><td align="right">3.55</td><td align="right">38.57</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.00</td><td align="right">68.0 KiB</td><td align="right">6.40</td><td align="right">1.04</td><td align="right">3.61</td><td align="right">19.68</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.31</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>5.21</strong></td><td align="right"><strong>1.06</strong></td><td align="right"><strong>3.23</strong></td><td align="right"><strong>20.37</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">27.98</td><td align="right">10.55 MiB</td><td align="right">2.79</td><td align="right">23.07</td><td align="right">4.95</td><td align="right">52.61</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.75</td><td align="right">108.5 KiB</td><td align="right">7.04</td><td align="right">0.99</td><td align="right">5.75</td><td align="right">24.80</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.55</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>6.96</strong></td><td align="right"><strong>0.92</strong></td><td align="right"><strong>3.53</strong></td><td align="right"><strong>25.19</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.08</td><td align="right">23.73 MiB</td><td align="right">3.99</td><td align="right">47.57</td><td align="right">7.63</td><td align="right">100.18</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.46</td><td align="right">221.7 KiB</td><td align="right">7.09</td><td align="right">0.87</td><td align="right">5.60</td><td align="right">36.51</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.35</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>10.40</strong></td><td align="right"><strong>0.55</strong></td><td align="right"><strong>3.13</strong></td><td align="right"><strong>36.40</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.32</strong></td><td align="right"><strong>36.4 KiB</strong></td><td align="right"><strong>9.33</strong></td><td align="right"><strong>0.47</strong></td><td align="right"><strong>4.10</strong></td><td align="right"><strong>35.39</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">28.65</td><td align="right">5.93 MiB</td><td align="right">2.20</td><td align="right">23.02</td><td align="right">3.88</td><td align="right">44.29</td></tr>
        <tr><td>nvJPEG</td><td align="right">28.00</td><td align="right">68.0 KiB</td><td align="right">7.12</td><td align="right">1.49</td><td align="right">5.21</td><td align="right">23.02</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.31</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>5.89</strong></td><td align="right"><strong>1.75</strong></td><td align="right"><strong>4.22</strong></td><td align="right"><strong>25.11</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">27.98</td><td align="right">10.55 MiB</td><td align="right">3.79</td><td align="right">25.08</td><td align="right">5.89</td><td align="right">57.20</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.75</td><td align="right">108.5 KiB</td><td align="right">7.83</td><td align="right">1.67</td><td align="right">5.85</td><td align="right">30.48</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.55</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>8.22</strong></td><td align="right"><strong>1.41</strong></td><td align="right"><strong>4.53</strong></td><td align="right"><strong>33.08</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">16.08</td><td align="right">23.73 MiB</td><td align="right">4.70</td><td align="right">62.93</td><td align="right">8.59</td><td align="right">125.18</td></tr>
        <tr><td>nvJPEG</td><td align="right">19.46</td><td align="right">221.7 KiB</td><td align="right">7.43</td><td align="right">1.17</td><td align="right">6.23</td><td align="right">42.53</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.35</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>10.65</strong></td><td align="right"><strong>0.82</strong></td><td align="right"><strong>3.84</strong></td><td align="right"><strong>43.54</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>17.32</strong></td><td align="right"><strong>36.4 KiB</strong></td><td align="right"><strong>10.45</strong></td><td align="right"><strong>0.66</strong></td><td align="right"><strong>4.26</strong></td><td align="right"><strong>37.52</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

## x86 (Patient) → x86 (Surgeon): Logitech BRIO Camera

</summary>

![SDK 5: x86 patient to x86 surgeon, Logitech BRIO Camera, stacked total latency breakdowns comparing codecs within each resolution](benchmarks/figures/sdk5-brio-host-usb-1e29b43c150f.svg)

<details>
<summary>

### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">14.96</td><td align="right">5.93 MiB</td><td align="right">1.32</td><td align="right">19.62</td><td align="right">1.81</td><td align="right">30.42</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.98</td><td align="right">58.8 KiB</td><td align="right">2.35</td><td align="right">0.81</td><td align="right">1.64</td><td align="right">7.96</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>13.4 KiB</strong></td><td align="right"><strong>3.45</strong></td><td align="right"><strong>0.71</strong></td><td align="right"><strong>1.57</strong></td><td align="right"><strong>8.85</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">14.95</td><td align="right">10.55 MiB</td><td align="right">1.00</td><td align="right">17.10</td><td align="right">1.68</td><td align="right">24.50</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.96</td><td align="right">130.8 KiB</td><td align="right">1.98</td><td align="right">0.36</td><td align="right">1.74</td><td align="right">5.53</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>25.7 KiB</strong></td><td align="right"><strong>3.66</strong></td><td align="right"><strong>0.33</strong></td><td align="right"><strong>1.29</strong></td><td align="right"><strong>6.84</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.93</td><td align="right">23.73 MiB</td><td align="right">1.18</td><td align="right">20.00</td><td align="right">2.59</td><td align="right">30.26</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.95</td><td align="right">261.4 KiB</td><td align="right">2.63</td><td align="right">0.34</td><td align="right">3.30</td><td align="right">7.49</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>51.0 KiB</strong></td><td align="right"><strong>6.44</strong></td><td align="right"><strong>0.22</strong></td><td align="right"><strong>1.83</strong></td><td align="right"><strong>9.73</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>41.4 KiB</strong></td><td align="right"><strong>5.22</strong></td><td align="right"><strong>0.20</strong></td><td align="right"><strong>2.33</strong></td><td align="right"><strong>8.96</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">14.96</td><td align="right">5.93 MiB</td><td align="right">2.57</td><td align="right">24.53</td><td align="right">2.33</td><td align="right">35.86</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.98</td><td align="right">58.8 KiB</td><td align="right">3.59</td><td align="right">1.33</td><td align="right">1.97</td><td align="right">9.56</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>13.4 KiB</strong></td><td align="right"><strong>5.30</strong></td><td align="right"><strong>1.09</strong></td><td align="right"><strong>2.05</strong></td><td align="right"><strong>10.78</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">14.95</td><td align="right">10.55 MiB</td><td align="right">1.69</td><td align="right">27.76</td><td align="right">2.44</td><td align="right">38.40</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.96</td><td align="right">130.8 KiB</td><td align="right">2.11</td><td align="right">0.60</td><td align="right">1.86</td><td align="right">6.24</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>25.7 KiB</strong></td><td align="right"><strong>3.83</strong></td><td align="right"><strong>0.55</strong></td><td align="right"><strong>1.62</strong></td><td align="right"><strong>7.98</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.93</td><td align="right">23.73 MiB</td><td align="right">1.24</td><td align="right">30.91</td><td align="right">2.75</td><td align="right">41.52</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.95</td><td align="right">261.4 KiB</td><td align="right">2.80</td><td align="right">0.58</td><td align="right">3.42</td><td align="right">8.17</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>51.0 KiB</strong></td><td align="right"><strong>6.88</strong></td><td align="right"><strong>0.43</strong></td><td align="right"><strong>2.13</strong></td><td align="right"><strong>11.13</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>41.4 KiB</strong></td><td align="right"><strong>5.35</strong></td><td align="right"><strong>0.32</strong></td><td align="right"><strong>2.53</strong></td><td align="right"><strong>9.70</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">14.96</td><td align="right">5.93 MiB</td><td align="right">2.97</td><td align="right">28.79</td><td align="right">2.57</td><td align="right">39.96</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.98</td><td align="right">58.8 KiB</td><td align="right">4.87</td><td align="right">1.41</td><td align="right">2.14</td><td align="right">11.33</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>13.4 KiB</strong></td><td align="right"><strong>5.65</strong></td><td align="right"><strong>1.22</strong></td><td align="right"><strong>2.25</strong></td><td align="right"><strong>11.85</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">14.95</td><td align="right">10.55 MiB</td><td align="right">2.55</td><td align="right">31.74</td><td align="right">3.09</td><td align="right">42.66</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.96</td><td align="right">130.8 KiB</td><td align="right">3.13</td><td align="right">0.67</td><td align="right">1.92</td><td align="right">6.83</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>25.7 KiB</strong></td><td align="right"><strong>4.95</strong></td><td align="right"><strong>0.83</strong></td><td align="right"><strong>1.86</strong></td><td align="right"><strong>10.14</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.93</td><td align="right">23.73 MiB</td><td align="right">3.08</td><td align="right">34.07</td><td align="right">4.22</td><td align="right">45.87</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.95</td><td align="right">261.4 KiB</td><td align="right">4.59</td><td align="right">0.80</td><td align="right">3.54</td><td align="right">9.82</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>51.0 KiB</strong></td><td align="right"><strong>8.46</strong></td><td align="right"><strong>0.80</strong></td><td align="right"><strong>2.49</strong></td><td align="right"><strong>13.75</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>41.4 KiB</strong></td><td align="right"><strong>6.40</strong></td><td align="right"><strong>0.49</strong></td><td align="right"><strong>2.86</strong></td><td align="right"><strong>11.18</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">14.96</td><td align="right">5.93 MiB</td><td align="right">3.07</td><td align="right">33.65</td><td align="right">3.89</td><td align="right">46.42</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.98</td><td align="right">58.8 KiB</td><td align="right">5.07</td><td align="right">2.24</td><td align="right">2.41</td><td align="right">12.12</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>13.4 KiB</strong></td><td align="right"><strong>5.82</strong></td><td align="right"><strong>1.79</strong></td><td align="right"><strong>2.62</strong></td><td align="right"><strong>12.61</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">14.95</td><td align="right">10.55 MiB</td><td align="right">3.84</td><td align="right">37.14</td><td align="right">3.93</td><td align="right">50.66</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.96</td><td align="right">130.8 KiB</td><td align="right">3.67</td><td align="right">0.76</td><td align="right">1.98</td><td align="right">8.20</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.96</strong></td><td align="right"><strong>25.7 KiB</strong></td><td align="right"><strong>5.33</strong></td><td align="right"><strong>1.62</strong></td><td align="right"><strong>2.07</strong></td><td align="right"><strong>11.49</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.93</td><td align="right">23.73 MiB</td><td align="right">3.16</td><td align="right">41.26</td><td align="right">4.61</td><td align="right">52.39</td></tr>
        <tr><td>nvJPEG</td><td align="right">14.95</td><td align="right">261.4 KiB</td><td align="right">4.75</td><td align="right">2.69</td><td align="right">3.83</td><td align="right">12.64</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>51.0 KiB</strong></td><td align="right"><strong>8.99</strong></td><td align="right"><strong>1.17</strong></td><td align="right"><strong>2.76</strong></td><td align="right"><strong>15.83</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>14.95</strong></td><td align="right"><strong>41.4 KiB</strong></td><td align="right"><strong>7.43</strong></td><td align="right"><strong>0.96</strong></td><td align="right"><strong>3.18</strong></td><td align="right"><strong>12.69</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details open>
<summary>

## Thor (Patient) → x86 (Surgeon): IMX274 Camera

</summary>

![SDK 5: Thor patient to x86 surgeon, IMX274 Camera, stacked total latency breakdowns comparing codecs within each resolution](benchmarks/figures/sdk5-imx274-thor-hsb-192.168.0.2-0.svg)

<details>
<summary>

### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">54.42</td><td align="right">5.93 MiB</td><td align="right">20.36</td><td align="right">22.07</td><td align="right">1.07</td><td align="right">50.69</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.94</td><td align="right">249.3 KiB</td><td align="right">4.46</td><td align="right">1.92</td><td align="right">1.61</td><td align="right">16.24</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.54</strong></td><td align="right"><strong>246.8 KiB</strong></td><td align="right"><strong>6.35</strong></td><td align="right"><strong>1.93</strong></td><td align="right"><strong>2.89</strong></td><td align="right"><strong>18.55</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.23</td><td align="right">23.73 MiB</td><td align="right">2.22</td><td align="right">104.65</td><td align="right">2.74</td><td align="right">134.43</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.71</td><td align="right">1.13 MiB</td><td align="right">8.22</td><td align="right">7.11</td><td align="right">4.37</td><td align="right">28.06</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.17</strong></td><td align="right"><strong>466.7 KiB</strong></td><td align="right"><strong>8.33</strong></td><td align="right"><strong>2.52</strong></td><td align="right"><strong>5.39</strong></td><td align="right"><strong>24.22</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>59.74</strong></td><td align="right"><strong>465.9 KiB</strong></td><td align="right"><strong>6.01</strong></td><td align="right"><strong>2.94</strong></td><td align="right"><strong>5.18</strong></td><td align="right"><strong>22.23</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">54.42</td><td align="right">5.93 MiB</td><td align="right">23.19</td><td align="right">25.24</td><td align="right">1.48</td><td align="right">59.14</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.94</td><td align="right">249.3 KiB</td><td align="right">4.78</td><td align="right">2.76</td><td align="right">1.81</td><td align="right">18.35</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.54</strong></td><td align="right"><strong>246.8 KiB</strong></td><td align="right"><strong>7.27</strong></td><td align="right"><strong>2.88</strong></td><td align="right"><strong>3.77</strong></td><td align="right"><strong>21.12</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.23</td><td align="right">23.73 MiB</td><td align="right">2.55</td><td align="right">114.99</td><td align="right">4.75</td><td align="right">153.69</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.71</td><td align="right">1.13 MiB</td><td align="right">11.67</td><td align="right">8.56</td><td align="right">4.58</td><td align="right">34.29</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.17</strong></td><td align="right"><strong>466.7 KiB</strong></td><td align="right"><strong>8.64</strong></td><td align="right"><strong>3.85</strong></td><td align="right"><strong>5.68</strong></td><td align="right"><strong>26.15</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>59.74</strong></td><td align="right"><strong>465.9 KiB</strong></td><td align="right"><strong>7.17</strong></td><td align="right"><strong>4.08</strong></td><td align="right"><strong>5.61</strong></td><td align="right"><strong>24.32</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">54.42</td><td align="right">5.93 MiB</td><td align="right">25.90</td><td align="right">28.11</td><td align="right">2.08</td><td align="right">67.95</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.94</td><td align="right">249.3 KiB</td><td align="right">4.91</td><td align="right">3.01</td><td align="right">2.13</td><td align="right">19.35</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.54</strong></td><td align="right"><strong>246.8 KiB</strong></td><td align="right"><strong>7.55</strong></td><td align="right"><strong>3.16</strong></td><td align="right"><strong>4.08</strong></td><td align="right"><strong>22.35</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.23</td><td align="right">23.73 MiB</td><td align="right">3.87</td><td align="right">121.03</td><td align="right">5.22</td><td align="right">159.28</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.71</td><td align="right">1.13 MiB</td><td align="right">12.55</td><td align="right">9.29</td><td align="right">5.33</td><td align="right">36.73</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.17</strong></td><td align="right"><strong>466.7 KiB</strong></td><td align="right"><strong>8.83</strong></td><td align="right"><strong>4.67</strong></td><td align="right"><strong>6.97</strong></td><td align="right"><strong>27.20</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>59.74</strong></td><td align="right"><strong>465.9 KiB</strong></td><td align="right"><strong>7.73</strong></td><td align="right"><strong>4.85</strong></td><td align="right"><strong>7.01</strong></td><td align="right"><strong>25.61</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">54.42</td><td align="right">5.93 MiB</td><td align="right">27.71</td><td align="right">31.87</td><td align="right">2.96</td><td align="right">83.99</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.94</td><td align="right">249.3 KiB</td><td align="right">5.66</td><td align="right">7.67</td><td align="right">3.49</td><td align="right">24.88</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.54</strong></td><td align="right"><strong>246.8 KiB</strong></td><td align="right"><strong>7.91</strong></td><td align="right"><strong>9.01</strong></td><td align="right"><strong>5.97</strong></td><td align="right"><strong>31.60</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.23</td><td align="right">23.73 MiB</td><td align="right">4.53</td><td align="right">143.10</td><td align="right">6.03</td><td align="right">174.22</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.71</td><td align="right">1.13 MiB</td><td align="right">15.45</td><td align="right">19.45</td><td align="right">6.81</td><td align="right">44.95</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.17</strong></td><td align="right"><strong>466.7 KiB</strong></td><td align="right"><strong>9.11</strong></td><td align="right"><strong>10.33</strong></td><td align="right"><strong>7.33</strong></td><td align="right"><strong>36.30</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>59.74</strong></td><td align="right"><strong>465.9 KiB</strong></td><td align="right"><strong>8.19</strong></td><td align="right"><strong>14.84</strong></td><td align="right"><strong>7.73</strong></td><td align="right"><strong>35.62</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

## DGX Spark (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5: DGX Spark patient to x86 surgeon, MIRA Procedure Camera, stacked total latency breakdowns comparing codecs within each resolution](benchmarks/figures/sdk5-mira-spark-procedure.svg)

<details>
<summary>

### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.33</td><td align="right">5.93 MiB</td><td align="right">0.29</td><td align="right">17.93</td><td align="right">1.13</td><td align="right">53.02</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.38</td><td align="right">62.3 KiB</td><td align="right">1.07</td><td align="right">1.06</td><td align="right">1.60</td><td align="right">35.84</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.10</strong></td><td align="right"><strong>0.71</strong></td><td align="right"><strong>1.54</strong></td><td align="right"><strong>57.40</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.95</td><td align="right">10.55 MiB</td><td align="right">0.50</td><td align="right">25.44</td><td align="right">1.69</td><td align="right">48.01</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.90</td><td align="right">102.3 KiB</td><td align="right">1.54</td><td align="right">1.18</td><td align="right">2.21</td><td align="right">50.14</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>3.23</strong></td><td align="right"><strong>0.75</strong></td><td align="right"><strong>1.73</strong></td><td align="right"><strong>51.84</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.91</td><td align="right">23.73 MiB</td><td align="right">1.11</td><td align="right">70.03</td><td align="right">2.78</td><td align="right">187.24</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.81</td><td align="right">209.7 KiB</td><td align="right">3.16</td><td align="right">1.63</td><td align="right">3.96</td><td align="right">98.10</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>6.78</strong></td><td align="right"><strong>0.86</strong></td><td align="right"><strong>2.53</strong></td><td align="right"><strong>170.77</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>18.4 KiB</strong></td><td align="right"><strong>8.18</strong></td><td align="right"><strong>0.78</strong></td><td align="right"><strong>3.08</strong></td><td align="right"><strong>99.34</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.33</td><td align="right">5.93 MiB</td><td align="right">0.39</td><td align="right">22.86</td><td align="right">1.75</td><td align="right">81.17</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.38</td><td align="right">62.3 KiB</td><td align="right">4.27</td><td align="right">1.45</td><td align="right">1.91</td><td align="right">64.41</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.54</strong></td><td align="right"><strong>0.95</strong></td><td align="right"><strong>2.00</strong></td><td align="right"><strong>62.84</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.95</td><td align="right">10.55 MiB</td><td align="right">0.68</td><td align="right">30.97</td><td align="right">2.60</td><td align="right">122.90</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.90</td><td align="right">102.3 KiB</td><td align="right">2.04</td><td align="right">1.78</td><td align="right">2.60</td><td align="right">91.96</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>4.78</strong></td><td align="right"><strong>1.05</strong></td><td align="right"><strong>2.22</strong></td><td align="right"><strong>94.37</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.91</td><td align="right">23.73 MiB</td><td align="right">1.54</td><td align="right">112.60</td><td align="right">4.59</td><td align="right">278.67</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.81</td><td align="right">209.7 KiB</td><td align="right">6.41</td><td align="right">2.61</td><td align="right">4.25</td><td align="right">177.46</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>8.03</strong></td><td align="right"><strong>1.18</strong></td><td align="right"><strong>3.00</strong></td><td align="right"><strong>177.17</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>18.4 KiB</strong></td><td align="right"><strong>8.81</strong></td><td align="right"><strong>1.08</strong></td><td align="right"><strong>3.64</strong></td><td align="right"><strong>178.84</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.33</td><td align="right">5.93 MiB</td><td align="right">0.52</td><td align="right">26.27</td><td align="right">2.01</td><td align="right">86.49</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.38</td><td align="right">62.3 KiB</td><td align="right">4.63</td><td align="right">1.71</td><td align="right">2.26</td><td align="right">65.54</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.36</strong></td><td align="right"><strong>1.10</strong></td><td align="right"><strong>2.15</strong></td><td align="right"><strong>64.92</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.95</td><td align="right">10.55 MiB</td><td align="right">0.78</td><td align="right">33.22</td><td align="right">3.32</td><td align="right">128.57</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.90</td><td align="right">102.3 KiB</td><td align="right">2.42</td><td align="right">1.99</td><td align="right">2.79</td><td align="right">93.48</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>5.42</strong></td><td align="right"><strong>1.24</strong></td><td align="right"><strong>2.55</strong></td><td align="right"><strong>95.82</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.91</td><td align="right">23.73 MiB</td><td align="right">1.66</td><td align="right">122.19</td><td align="right">5.39</td><td align="right">301.89</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.81</td><td align="right">209.7 KiB</td><td align="right">7.39</td><td align="right">2.84</td><td align="right">4.58</td><td align="right">180.15</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>9.16</strong></td><td align="right"><strong>1.37</strong></td><td align="right"><strong>3.16</strong></td><td align="right"><strong>178.52</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>18.4 KiB</strong></td><td align="right"><strong>10.28</strong></td><td align="right"><strong>1.19</strong></td><td align="right"><strong>3.85</strong></td><td align="right"><strong>180.30</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.33</td><td align="right">5.93 MiB</td><td align="right">0.79</td><td align="right">30.15</td><td align="right">2.42</td><td align="right">90.82</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.38</td><td align="right">62.3 KiB</td><td align="right">4.95</td><td align="right">3.47</td><td align="right">4.72</td><td align="right">66.98</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.61</strong></td><td align="right"><strong>2.11</strong></td><td align="right"><strong>2.43</strong></td><td align="right"><strong>66.41</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.95</td><td align="right">10.55 MiB</td><td align="right">0.92</td><td align="right">38.35</td><td align="right">4.85</td><td align="right">130.68</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.90</td><td align="right">102.3 KiB</td><td align="right">5.54</td><td align="right">2.89</td><td align="right">3.37</td><td align="right">96.11</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>5.71</strong></td><td align="right"><strong>2.52</strong></td><td align="right"><strong>2.86</strong></td><td align="right"><strong>97.54</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.91</td><td align="right">23.73 MiB</td><td align="right">2.12</td><td align="right">131.48</td><td align="right">6.18</td><td align="right">309.70</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.81</td><td align="right">209.7 KiB</td><td align="right">7.84</td><td align="right">6.04</td><td align="right">6.03</td><td align="right">182.36</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>9.75</strong></td><td align="right"><strong>3.07</strong></td><td align="right"><strong>3.37</strong></td><td align="right"><strong>181.50</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>18.4 KiB</strong></td><td align="right"><strong>10.73</strong></td><td align="right"><strong>2.42</strong></td><td align="right"><strong>3.97</strong></td><td align="right"><strong>181.58</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

## DGX Spark (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5: DGX Spark patient to x86 surgeon, MIRA Room Camera, stacked total latency breakdowns comparing codecs within each resolution](benchmarks/figures/sdk5-mira-spark-room.svg)

<details>
<summary>

### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.30</td><td align="right">5.93 MiB</td><td align="right">0.28</td><td align="right">14.36</td><td align="right">1.22</td><td align="right">25.20</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.36</td><td align="right">67.5 KiB</td><td align="right">1.27</td><td align="right">1.02</td><td align="right">1.64</td><td align="right">9.83</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.38</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>2.29</strong></td><td align="right"><strong>0.71</strong></td><td align="right"><strong>1.47</strong></td><td align="right"><strong>9.77</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.81</td><td align="right">10.55 MiB</td><td align="right">0.50</td><td align="right">23.29</td><td align="right">1.68</td><td align="right">38.38</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.91</td><td align="right">108.2 KiB</td><td align="right">1.75</td><td align="right">1.26</td><td align="right">2.23</td><td align="right">11.99</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>29.7 KiB</strong></td><td align="right"><strong>3.62</strong></td><td align="right"><strong>0.81</strong></td><td align="right"><strong>1.77</strong></td><td align="right"><strong>13.18</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.83</td><td align="right">23.73 MiB</td><td align="right">1.11</td><td align="right">62.76</td><td align="right">2.79</td><td align="right">90.48</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.83</td><td align="right">219.8 KiB</td><td align="right">3.60</td><td align="right">1.66</td><td align="right">3.94</td><td align="right">20.45</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.87</strong></td><td align="right"><strong>48.0 KiB</strong></td><td align="right"><strong>7.36</strong></td><td align="right"><strong>0.95</strong></td><td align="right"><strong>2.53</strong></td><td align="right"><strong>21.59</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.88</strong></td><td align="right"><strong>35.0 KiB</strong></td><td align="right"><strong>10.24</strong></td><td align="right"><strong>0.92</strong></td><td align="right"><strong>3.02</strong></td><td align="right"><strong>24.79</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.30</td><td align="right">5.93 MiB</td><td align="right">0.37</td><td align="right">19.05</td><td align="right">1.97</td><td align="right">30.22</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.36</td><td align="right">67.5 KiB</td><td align="right">3.80</td><td align="right">1.42</td><td align="right">2.10</td><td align="right">12.60</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.38</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>3.96</strong></td><td align="right"><strong>1.01</strong></td><td align="right"><strong>1.90</strong></td><td align="right"><strong>12.13</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.81</td><td align="right">10.55 MiB</td><td align="right">0.71</td><td align="right">29.10</td><td align="right">2.19</td><td align="right">45.57</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.91</td><td align="right">108.2 KiB</td><td align="right">4.43</td><td align="right">1.75</td><td align="right">2.72</td><td align="right">14.84</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>29.7 KiB</strong></td><td align="right"><strong>5.30</strong></td><td align="right"><strong>1.18</strong></td><td align="right"><strong>2.46</strong></td><td align="right"><strong>15.69</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.83</td><td align="right">23.73 MiB</td><td align="right">1.51</td><td align="right">102.25</td><td align="right">4.81</td><td align="right">136.62</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.83</td><td align="right">219.8 KiB</td><td align="right">5.24</td><td align="right">2.49</td><td align="right">4.40</td><td align="right">22.09</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.87</strong></td><td align="right"><strong>48.0 KiB</strong></td><td align="right"><strong>8.91</strong></td><td align="right"><strong>1.29</strong></td><td align="right"><strong>3.14</strong></td><td align="right"><strong>23.75</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.88</strong></td><td align="right"><strong>35.0 KiB</strong></td><td align="right"><strong>11.29</strong></td><td align="right"><strong>1.23</strong></td><td align="right"><strong>3.82</strong></td><td align="right"><strong>26.28</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.30</td><td align="right">5.93 MiB</td><td align="right">0.42</td><td align="right">22.74</td><td align="right">2.62</td><td align="right">34.19</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.36</td><td align="right">67.5 KiB</td><td align="right">4.17</td><td align="right">1.59</td><td align="right">2.37</td><td align="right">13.20</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.38</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>4.40</strong></td><td align="right"><strong>1.13</strong></td><td align="right"><strong>2.12</strong></td><td align="right"><strong>12.57</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.81</td><td align="right">10.55 MiB</td><td align="right">0.88</td><td align="right">30.99</td><td align="right">2.80</td><td align="right">47.83</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.91</td><td align="right">108.2 KiB</td><td align="right">4.73</td><td align="right">2.06</td><td align="right">3.08</td><td align="right">15.59</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>29.7 KiB</strong></td><td align="right"><strong>5.77</strong></td><td align="right"><strong>1.36</strong></td><td align="right"><strong>2.59</strong></td><td align="right"><strong>16.54</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.83</td><td align="right">23.73 MiB</td><td align="right">1.83</td><td align="right">111.65</td><td align="right">5.42</td><td align="right">145.44</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.83</td><td align="right">219.8 KiB</td><td align="right">5.91</td><td align="right">2.69</td><td align="right">5.30</td><td align="right">22.63</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.87</strong></td><td align="right"><strong>48.0 KiB</strong></td><td align="right"><strong>9.87</strong></td><td align="right"><strong>1.42</strong></td><td align="right"><strong>3.30</strong></td><td align="right"><strong>24.53</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.88</strong></td><td align="right"><strong>35.0 KiB</strong></td><td align="right"><strong>12.81</strong></td><td align="right"><strong>1.37</strong></td><td align="right"><strong>4.07</strong></td><td align="right"><strong>27.53</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">17.30</td><td align="right">5.93 MiB</td><td align="right">0.46</td><td align="right">25.04</td><td align="right">3.31</td><td align="right">37.62</td></tr>
        <tr><td>nvJPEG</td><td align="right">17.36</td><td align="right">67.5 KiB</td><td align="right">4.52</td><td align="right">3.74</td><td align="right">2.87</td><td align="right">15.81</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>17.38</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>4.72</strong></td><td align="right"><strong>1.71</strong></td><td align="right"><strong>2.52</strong></td><td align="right"><strong>13.19</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.81</td><td align="right">10.55 MiB</td><td align="right">1.03</td><td align="right">34.09</td><td align="right">3.48</td><td align="right">51.81</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.91</td><td align="right">108.2 KiB</td><td align="right">4.89</td><td align="right">2.95</td><td align="right">5.44</td><td align="right">19.63</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.91</strong></td><td align="right"><strong>29.7 KiB</strong></td><td align="right"><strong>6.29</strong></td><td align="right"><strong>1.61</strong></td><td align="right"><strong>3.96</strong></td><td align="right"><strong>18.08</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.83</td><td align="right">23.73 MiB</td><td align="right">2.07</td><td align="right">120.68</td><td align="right">7.72</td><td align="right">155.85</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.83</td><td align="right">219.8 KiB</td><td align="right">6.03</td><td align="right">6.77</td><td align="right">6.15</td><td align="right">26.88</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>8.87</strong></td><td align="right"><strong>48.0 KiB</strong></td><td align="right"><strong>10.44</strong></td><td align="right"><strong>3.73</strong></td><td align="right"><strong>4.56</strong></td><td align="right"><strong>26.57</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>8.88</strong></td><td align="right"><strong>35.0 KiB</strong></td><td align="right"><strong>13.54</strong></td><td align="right"><strong>2.61</strong></td><td align="right"><strong>4.55</strong></td><td align="right"><strong>29.92</strong></td></tr>
    </tbody>
</table>

</details>

</details>

## Method and limits

- Source and receiver both use Holoscan `5.0.0a3 (public EA3)`. All 48 configurations collect 60 seconds after a 30-second warmup. Actual durations, sample counts, incomplete timing coverage and frame-loss counters are in the CSV.
- H.264/H.265 use NVENC P1, ultra-low-latency, QP 24, independent frames, no B frames and no lookahead. nvJPEG quality is 85. Equal QP does not imply equal visual quality.
- BRIO captures YUYV at FHD and MJPEG at QHD/4K. MJPEG decoding inside camera capture precedes the measured buffer boundary. IMX274 uses native sensor modes. Simulation recreates each camera at the requested render resolution.
- Timing starts when a USB BGR buffer, processed HSB Bayer buffer or simulator RGB buffer is available. Sensor exposure, earlier producer work and physical scanout are excluded. The full path includes frame preparation, encoder queue, encode/pack, source relay/queue, send queue, transport, receive queue, decode/upload and viewer handoff.
- Percentiles use linear interpolation over at most 10,000 valid samples. Timing excludes the first two seconds after reset; native summaries refresh every five seconds. Browser totals use frames matched by RTP timestamp. Transport uses the receiver's recorded `steady_metrics.delivery_ms` percentiles.
- Same-host timing uses a monotonic clock. Remote timing uses fresh UTC bounds or four-timestamp relative estimates. Clock uncertainty is recorded in the CSV; unresolved timing remains unavailable.
- Frame size excludes TLS/TCP/IP overhead. FPS, frame spacing, sequence gaps and browser drops are separate from latency. Browser FPS subtracts dropped frames from the [total video frame counter](https://w3c.github.io/media-playback-quality/); sequence gaps use application stream numbers.
- Streams retain their requested resolution through decoding. Native windows are capped at 1280×720; Chromium uses a 1600×1000 dashboard viewport. These are stream-resolution tests with display scaling afterward. Browser hardware decoding was not confirmed.

Each configuration has one measured run. P99.9 can depend on only a few frames in a 60-second sample, especially for slower simulation sources. Unrelated telesurgery streams and simulations were stopped. Power and clocks were observed rather than fixed; physical camera scenes were not controlled. Remote tests also change source hardware, so their differences are not solely network overhead. Isaac Sim rendering and CPU readback/IPC can limit throughput independently of the codec.

## Repeat one configuration

Start patient, node and surgeon services on SDK 5 EA3, approve the node and discover the cameras, then collect a run:

```bash
.venv-sdk5/bin/python scripts/benchmark.py \
  --camera host:procedure --camera host:room \
  --width 3840 --height 2160 --fps 30 \
  --codec h265 --receiver holoviz \
  --seconds 60 --output runs/benchmark.json
```

The collector starts/stops the selected streams and viewers and resets their metrics. It never moves robots. `--patient`, `--surgeon` and `--endpoint` select service addresses. For browser viewing, use `--codec h264 --receiver webrtc`; install Playwright/Chromium as described in [Contributing](CONTRIBUTING.md).

<details>
<summary>

## Appendix: WebRTC

</summary>

H.264 viewing in a visible Chromium browser on the surgeon's x86 workstation. The same source titles and percentiles apply. Total includes browser delivery and scheduling; Transport covers patient-to-surgeon-service delivery only.

<details open>
<summary>

### x86 (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5: x86 patient to x86 surgeon, MIRA Procedure Camera, WebRTC stacked total latency breakdowns across resolutions](benchmarks/figures/sdk5-mira-host-procedure-webrtc.svg)

<details>
<summary>

#### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.50</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>3.60</strong></td><td align="right"><strong>36.76</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.67</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>4.14</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>4.90</strong></td><td align="right"><strong>43.40</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>7.86</strong></td><td align="right"><strong>0.33</strong></td><td align="right"><strong>9.20</strong></td><td align="right"><strong>74.02</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

#### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>3.64</strong></td><td align="right"><strong>0.57</strong></td><td align="right"><strong>10.10</strong></td><td align="right"><strong>54.92</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.67</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>6.33</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>9.80</strong></td><td align="right"><strong>59.93</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>10.22</strong></td><td align="right"><strong>0.47</strong></td><td align="right"><strong>14.12</strong></td><td align="right"><strong>93.22</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.32</strong></td><td align="right"><strong>0.82</strong></td><td align="right"><strong>13.81</strong></td><td align="right"><strong>60.52</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.67</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>7.24</strong></td><td align="right"><strong>0.78</strong></td><td align="right"><strong>15.01</strong></td><td align="right"><strong>64.09</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>10.83</strong></td><td align="right"><strong>0.62</strong></td><td align="right"><strong>16.79</strong></td><td align="right"><strong>99.57</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>5.53</strong></td><td align="right"><strong>1.24</strong></td><td align="right"><strong>16.26</strong></td><td align="right"><strong>66.15</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.67</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>1.12</strong></td><td align="right"><strong>19.94</strong></td><td align="right"><strong>70.28</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>12.27</strong></td><td align="right"><strong>1.01</strong></td><td align="right"><strong>18.95</strong></td><td align="right"><strong>104.00</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

### x86 (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5: x86 patient to x86 surgeon, MIRA Room Camera, WebRTC stacked total latency breakdowns across resolutions](benchmarks/figures/sdk5-mira-host-room-webrtc.svg)

<details>
<summary>

#### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.47</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>2.47</strong></td><td align="right"><strong>0.22</strong></td><td align="right"><strong>4.70</strong></td><td align="right"><strong>36.97</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.61</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>4.28</strong></td><td align="right"><strong>0.22</strong></td><td align="right"><strong>6.10</strong></td><td align="right"><strong>44.00</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>7.57</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>13.80</strong></td><td align="right"><strong>70.40</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

#### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.47</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>4.10</strong></td><td align="right"><strong>0.76</strong></td><td align="right"><strong>11.77</strong></td><td align="right"><strong>54.46</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.61</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>6.23</strong></td><td align="right"><strong>0.55</strong></td><td align="right"><strong>10.80</strong></td><td align="right"><strong>60.18</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>9.58</strong></td><td align="right"><strong>0.41</strong></td><td align="right"><strong>18.81</strong></td><td align="right"><strong>88.70</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.47</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>4.71</strong></td><td align="right"><strong>1.32</strong></td><td align="right"><strong>15.29</strong></td><td align="right"><strong>59.85</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.61</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>6.95</strong></td><td align="right"><strong>1.04</strong></td><td align="right"><strong>14.60</strong></td><td align="right"><strong>65.96</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>10.45</strong></td><td align="right"><strong>0.63</strong></td><td align="right"><strong>20.80</strong></td><td align="right"><strong>94.95</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>25.47</strong></td><td align="right"><strong>21.7 KiB</strong></td><td align="right"><strong>5.73</strong></td><td align="right"><strong>3.31</strong></td><td align="right"><strong>18.16</strong></td><td align="right"><strong>62.73</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.61</strong></td><td align="right"><strong>29.9 KiB</strong></td><td align="right"><strong>7.87</strong></td><td align="right"><strong>2.49</strong></td><td align="right"><strong>16.63</strong></td><td align="right"><strong>72.73</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>17.36</strong></td><td align="right"><strong>49.3 KiB</strong></td><td align="right"><strong>10.80</strong></td><td align="right"><strong>1.26</strong></td><td align="right"><strong>22.23</strong></td><td align="right"><strong>99.84</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

### x86 (Patient) → x86 (Surgeon): Logitech BRIO Camera

</summary>

![SDK 5: x86 patient to x86 surgeon, Logitech BRIO Camera, WebRTC stacked total latency breakdowns across resolutions](benchmarks/figures/sdk5-brio-host-usb-1e29b43c150f-webrtc.svg)

<details>
<summary>

#### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>12.7 KiB</strong></td><td align="right"><strong>3.49</strong></td><td align="right"><strong>0.79</strong></td><td align="right"><strong>12.60</strong></td><td align="right"><strong>67.66</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.04</strong></td><td align="right"><strong>28.2 KiB</strong></td><td align="right"><strong>3.66</strong></td><td align="right"><strong>0.34</strong></td><td align="right"><strong>14.80</strong></td><td align="right"><strong>61.06</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>53.6 KiB</strong></td><td align="right"><strong>6.55</strong></td><td align="right"><strong>0.30</strong></td><td align="right"><strong>18.80</strong></td><td align="right"><strong>46.87</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

#### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>12.7 KiB</strong></td><td align="right"><strong>5.28</strong></td><td align="right"><strong>1.28</strong></td><td align="right"><strong>13.20</strong></td><td align="right"><strong>76.44</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.04</strong></td><td align="right"><strong>28.2 KiB</strong></td><td align="right"><strong>4.68</strong></td><td align="right"><strong>0.64</strong></td><td align="right"><strong>20.20</strong></td><td align="right"><strong>73.98</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>53.6 KiB</strong></td><td align="right"><strong>6.87</strong></td><td align="right"><strong>0.49</strong></td><td align="right"><strong>26.50</strong></td><td align="right"><strong>63.03</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>12.7 KiB</strong></td><td align="right"><strong>5.70</strong></td><td align="right"><strong>1.43</strong></td><td align="right"><strong>13.89</strong></td><td align="right"><strong>90.88</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.04</strong></td><td align="right"><strong>28.2 KiB</strong></td><td align="right"><strong>5.43</strong></td><td align="right"><strong>0.85</strong></td><td align="right"><strong>23.33</strong></td><td align="right"><strong>77.40</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>53.6 KiB</strong></td><td align="right"><strong>8.10</strong></td><td align="right"><strong>0.81</strong></td><td align="right"><strong>27.99</strong></td><td align="right"><strong>68.68</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>12.7 KiB</strong></td><td align="right"><strong>6.01</strong></td><td align="right"><strong>1.71</strong></td><td align="right"><strong>16.14</strong></td><td align="right"><strong>91.92</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.04</strong></td><td align="right"><strong>28.2 KiB</strong></td><td align="right"><strong>6.25</strong></td><td align="right"><strong>1.54</strong></td><td align="right"><strong>25.76</strong></td><td align="right"><strong>79.45</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>53.6 KiB</strong></td><td align="right"><strong>8.69</strong></td><td align="right"><strong>1.09</strong></td><td align="right"><strong>34.63</strong></td><td align="right"><strong>80.56</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details open>
<summary>

### Thor (Patient) → x86 (Surgeon): IMX274 Camera

</summary>

![SDK 5: Thor patient to x86 surgeon, IMX274 Camera, WebRTC stacked total latency breakdowns across resolutions](benchmarks/figures/sdk5-imx274-thor-hsb-192.168.0.2-0-webrtc.svg)

<details>
<summary>

#### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>58.35</strong></td><td align="right"><strong>68.8 KiB</strong></td><td align="right"><strong>6.70</strong></td><td align="right"><strong>0.66</strong></td><td align="right"><strong>7.40</strong></td><td align="right"><strong>52.34</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.25</strong></td><td align="right"><strong>466.8 KiB</strong></td><td align="right"><strong>8.28</strong></td><td align="right"><strong>1.89</strong></td><td align="right"><strong>34.70</strong></td><td align="right"><strong>79.82</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

#### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>58.35</strong></td><td align="right"><strong>68.8 KiB</strong></td><td align="right"><strong>7.37</strong></td><td align="right"><strong>0.99</strong></td><td align="right"><strong>14.90</strong></td><td align="right"><strong>63.07</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.25</strong></td><td align="right"><strong>466.8 KiB</strong></td><td align="right"><strong>8.66</strong></td><td align="right"><strong>2.25</strong></td><td align="right"><strong>37.80</strong></td><td align="right"><strong>92.67</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>58.35</strong></td><td align="right"><strong>68.8 KiB</strong></td><td align="right"><strong>7.74</strong></td><td align="right"><strong>1.26</strong></td><td align="right"><strong>16.90</strong></td><td align="right"><strong>64.01</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.25</strong></td><td align="right"><strong>466.8 KiB</strong></td><td align="right"><strong>8.95</strong></td><td align="right"><strong>2.43</strong></td><td align="right"><strong>41.06</strong></td><td align="right"><strong>99.93</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>58.35</strong></td><td align="right"><strong>68.8 KiB</strong></td><td align="right"><strong>8.01</strong></td><td align="right"><strong>1.66</strong></td><td align="right"><strong>22.03</strong></td><td align="right"><strong>65.19</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.25</strong></td><td align="right"><strong>466.8 KiB</strong></td><td align="right"><strong>9.39</strong></td><td align="right"><strong>3.02</strong></td><td align="right"><strong>44.25</strong></td><td align="right"><strong>102.22</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

### DGX Spark (Patient) → x86 (Surgeon): MIRA Procedure Camera

</summary>

![SDK 5: DGX Spark patient to x86 surgeon, MIRA Procedure Camera, WebRTC stacked total latency breakdowns across resolutions](benchmarks/figures/sdk5-mira-spark-procedure-webrtc.svg)

<details>
<summary>

#### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.89</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.09</strong></td><td align="right"><strong>0.70</strong></td><td align="right"><strong>9.70</strong></td><td align="right"><strong>50.62</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.02</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>3.23</strong></td><td align="right"><strong>0.71</strong></td><td align="right"><strong>11.00</strong></td><td align="right"><strong>56.33</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.16</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>6.74</strong></td><td align="right"><strong>0.65</strong></td><td align="right"><strong>13.55</strong></td><td align="right"><strong>64.75</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

#### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.89</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.45</strong></td><td align="right"><strong>1.11</strong></td><td align="right"><strong>12.00</strong></td><td align="right"><strong>99.34</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.02</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>3.55</strong></td><td align="right"><strong>1.24</strong></td><td align="right"><strong>18.40</strong></td><td align="right"><strong>134.42</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.16</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>7.78</strong></td><td align="right"><strong>1.22</strong></td><td align="right"><strong>25.32</strong></td><td align="right"><strong>221.50</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.89</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.13</strong></td><td align="right"><strong>1.47</strong></td><td align="right"><strong>13.00</strong></td><td align="right"><strong>105.07</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.02</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>3.73</strong></td><td align="right"><strong>1.55</strong></td><td align="right"><strong>19.87</strong></td><td align="right"><strong>140.56</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.16</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>8.87</strong></td><td align="right"><strong>1.61</strong></td><td align="right"><strong>26.09</strong></td><td align="right"><strong>226.27</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.89</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.51</strong></td><td align="right"><strong>3.00</strong></td><td align="right"><strong>15.45</strong></td><td align="right"><strong>109.82</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.02</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>3.91</strong></td><td align="right"><strong>3.13</strong></td><td align="right"><strong>21.75</strong></td><td align="right"><strong>144.03</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.16</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>9.70</strong></td><td align="right"><strong>3.13</strong></td><td align="right"><strong>32.28</strong></td><td align="right"><strong>230.19</strong></td></tr>
    </tbody>
</table>

</details>

</details>

<details>
<summary>

### DGX Spark (Patient) → x86 (Surgeon): MIRA Room Camera

</summary>

![SDK 5: DGX Spark patient to x86 surgeon, MIRA Room Camera, WebRTC stacked total latency breakdowns across resolutions](benchmarks/figures/sdk5-mira-spark-room-webrtc.svg)

<details>
<summary>

#### P50

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.66</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>2.18</strong></td><td align="right"><strong>1.45</strong></td><td align="right"><strong>10.80</strong></td><td align="right"><strong>42.82</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.15</strong></td><td align="right"><strong>29.6 KiB</strong></td><td align="right"><strong>3.80</strong></td><td align="right"><strong>1.33</strong></td><td align="right"><strong>12.00</strong></td><td align="right"><strong>48.48</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.52</strong></td><td align="right"><strong>48.2 KiB</strong></td><td align="right"><strong>7.34</strong></td><td align="right"><strong>0.68</strong></td><td align="right"><strong>13.60</strong></td><td align="right"><strong>56.16</strong></td></tr>
    </tbody>
</table>

</details>

<details>
<summary>

#### P95

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.66</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>4.00</strong></td><td align="right"><strong>3.41</strong></td><td align="right"><strong>14.90</strong></td><td align="right"><strong>60.97</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.15</strong></td><td align="right"><strong>29.6 KiB</strong></td><td align="right"><strong>5.26</strong></td><td align="right"><strong>4.40</strong></td><td align="right"><strong>20.20</strong></td><td align="right"><strong>64.96</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.52</strong></td><td align="right"><strong>48.2 KiB</strong></td><td align="right"><strong>8.53</strong></td><td align="right"><strong>4.25</strong></td><td align="right"><strong>24.40</strong></td><td align="right"><strong>72.34</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.66</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>4.37</strong></td><td align="right"><strong>4.32</strong></td><td align="right"><strong>15.80</strong></td><td align="right"><strong>66.15</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.15</strong></td><td align="right"><strong>29.6 KiB</strong></td><td align="right"><strong>5.48</strong></td><td align="right"><strong>5.39</strong></td><td align="right"><strong>20.93</strong></td><td align="right"><strong>70.54</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.52</strong></td><td align="right"><strong>48.2 KiB</strong></td><td align="right"><strong>9.82</strong></td><td align="right"><strong>5.24</strong></td><td align="right"><strong>26.60</strong></td><td align="right"><strong>75.47</strong></td></tr>
    </tbody>
</table>

</details>

<details open>
<summary>

#### P99.9

</summary>

<table>
    <thead>
        <tr><th align="left">RES</th><th align="left">CC</th><th align="right">FPS</th><th align="right">FS</th><th align="right">Encode (ms)</th><th align="right">Transport (ms)</th><th align="right">Decode (ms)</th><th align="right">Total (ms)</th></tr>
    </thead>
    <tbody>
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.66</strong></td><td align="right"><strong>21.4 KiB</strong></td><td align="right"><strong>4.52</strong></td><td align="right"><strong>5.26</strong></td><td align="right"><strong>17.65</strong></td><td align="right"><strong>68.91</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>11.15</strong></td><td align="right"><strong>29.6 KiB</strong></td><td align="right"><strong>5.69</strong></td><td align="right"><strong>6.49</strong></td><td align="right"><strong>22.23</strong></td><td align="right"><strong>72.69</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>7.52</strong></td><td align="right"><strong>48.2 KiB</strong></td><td align="right"><strong>10.42</strong></td><td align="right"><strong>7.55</strong></td><td align="right"><strong>27.86</strong></td><td align="right"><strong>78.76</strong></td></tr>
    </tbody>
</table>

</details>

</details>

</details>
