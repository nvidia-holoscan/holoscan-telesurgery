# SDK 5 benchmark

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}, "MD033": {"allowed_elements": ["details", "summary", "table", "thead", "tbody", "tr", "th", "td", "strong"]}} -->

October 2026 · Holoscan `5.0.0.dev20260928` · **48 configurations, 74 camera results**.

These measurements predate the switch to public EA3; they are not EA3 results.

Compare resolutions and codecs for each patient source. **The surgeon always runs on the x86 workstation.** The main tables use Holoviz; [WebRTC](#appendix-webrtc) is in the appendix. [SDK 4 report](docs/BENCHMARK_SDK4.md) · [SDK comparison](docs/BENCHMARK_COMPARISON.md).

[Measurements](benchmarks/results/summary.csv) · [Matched-frame breakdowns](benchmarks/results/stages.csv) · [Raw records](benchmarks/results/matrix/) · [Hardware details](benchmarks/results/matrix/hardware.json)

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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.86</td><td align="right">5.93 MiB</td><td align="right">0.56</td><td align="right">6.65</td><td align="right">1.96</td><td align="right">20.08</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.18</td><td align="right">62.4 KiB</td><td align="right">3.33</td><td align="right">0.36</td><td align="right">4.01</td><td align="right">14.82</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.63</strong></td><td align="right"><strong>0.31</strong></td><td align="right"><strong>3.43</strong></td><td align="right"><strong>13.09</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">24.03</td><td align="right">10.55 MiB</td><td align="right">1.13</td><td align="right">11.74</td><td align="right">2.46</td><td align="right">32.12</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.71</td><td align="right">101.8 KiB</td><td align="right">4.37</td><td align="right">0.41</td><td align="right">4.07</td><td align="right">18.84</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>25.00</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>4.45</strong></td><td align="right"><strong>0.31</strong></td><td align="right"><strong>3.14</strong></td><td align="right"><strong>18.33</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">2.25</td><td align="right">26.27</td><td align="right">4.55</td><td align="right">77.59</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.66</td><td align="right">209.2 KiB</td><td align="right">3.82</td><td align="right">0.61</td><td align="right">5.16</td><td align="right">38.39</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.47</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>7.66</strong></td><td align="right"><strong>0.34</strong></td><td align="right"><strong>3.21</strong></td><td align="right"><strong>40.15</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.71</strong></td><td align="right"><strong>18.5 KiB</strong></td><td align="right"><strong>6.64</strong></td><td align="right"><strong>0.34</strong></td><td align="right"><strong>3.38</strong></td><td align="right"><strong>39.00</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.86</td><td align="right">5.93 MiB</td><td align="right">1.24</td><td align="right">10.71</td><td align="right">3.26</td><td align="right">25.57</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.18</td><td align="right">62.4 KiB</td><td align="right">5.37</td><td align="right">0.47</td><td align="right">5.26</td><td align="right">16.56</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>3.77</strong></td><td align="right"><strong>0.40</strong></td><td align="right"><strong>4.92</strong></td><td align="right"><strong>15.33</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">24.03</td><td align="right">10.55 MiB</td><td align="right">2.51</td><td align="right">19.55</td><td align="right">4.24</td><td align="right">41.23</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.71</td><td align="right">101.8 KiB</td><td align="right">7.00</td><td align="right">0.52</td><td align="right">5.51</td><td align="right">22.14</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>25.00</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>6.24</strong></td><td align="right"><strong>0.39</strong></td><td align="right"><strong>5.03</strong></td><td align="right"><strong>20.90</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">4.74</td><td align="right">45.08</td><td align="right">9.72</td><td align="right">98.70</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.66</td><td align="right">209.2 KiB</td><td align="right">6.24</td><td align="right">1.20</td><td align="right">7.25</td><td align="right">43.34</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.47</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>10.07</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>5.69</strong></td><td align="right"><strong>46.28</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.71</strong></td><td align="right"><strong>18.5 KiB</strong></td><td align="right"><strong>8.97</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>6.14</strong></td><td align="right"><strong>45.18</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.86</td><td align="right">5.93 MiB</td><td align="right">1.35</td><td align="right">11.50</td><td align="right">3.64</td><td align="right">29.00</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.18</td><td align="right">62.4 KiB</td><td align="right">6.32</td><td align="right">0.54</td><td align="right">5.50</td><td align="right">18.11</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.46</strong></td><td align="right"><strong>0.47</strong></td><td align="right"><strong>5.22</strong></td><td align="right"><strong>16.15</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">24.03</td><td align="right">10.55 MiB</td><td align="right">2.68</td><td align="right">20.86</td><td align="right">4.89</td><td align="right">45.73</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.71</td><td align="right">101.8 KiB</td><td align="right">8.04</td><td align="right">0.69</td><td align="right">6.05</td><td align="right">24.21</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>25.00</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>6.82</strong></td><td align="right"><strong>0.43</strong></td><td align="right"><strong>5.26</strong></td><td align="right"><strong>22.48</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">5.57</td><td align="right">52.13</td><td align="right">10.88</td><td align="right">109.25</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.66</td><td align="right">209.2 KiB</td><td align="right">8.36</td><td align="right">1.42</td><td align="right">7.63</td><td align="right">47.34</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.47</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>10.35</strong></td><td align="right"><strong>0.66</strong></td><td align="right"><strong>6.02</strong></td><td align="right"><strong>49.49</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.71</strong></td><td align="right"><strong>18.5 KiB</strong></td><td align="right"><strong>9.29</strong></td><td align="right"><strong>0.76</strong></td><td align="right"><strong>6.51</strong></td><td align="right"><strong>48.56</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.86</td><td align="right">5.93 MiB</td><td align="right">1.46</td><td align="right">14.92</td><td align="right">4.06</td><td align="right">31.70</td></tr>
        <tr><td>nvJPEG</td><td align="right">27.18</td><td align="right">62.4 KiB</td><td align="right">7.51</td><td align="right">0.96</td><td align="right">5.64</td><td align="right">20.78</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.45</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>5.31</strong></td><td align="right"><strong>1.17</strong></td><td align="right"><strong>5.76</strong></td><td align="right"><strong>23.40</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">24.03</td><td align="right">10.55 MiB</td><td align="right">3.12</td><td align="right">22.25</td><td align="right">5.45</td><td align="right">53.13</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.71</td><td align="right">101.8 KiB</td><td align="right">8.56</td><td align="right">0.94</td><td align="right">6.72</td><td align="right">24.96</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>25.00</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>7.38</strong></td><td align="right"><strong>0.90</strong></td><td align="right"><strong>5.59</strong></td><td align="right"><strong>24.04</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">6.45</td><td align="right">68.29</td><td align="right">11.66</td><td align="right">122.56</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.66</td><td align="right">209.2 KiB</td><td align="right">10.23</td><td align="right">1.73</td><td align="right">8.90</td><td align="right">55.00</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.47</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>11.60</strong></td><td align="right"><strong>3.29</strong></td><td align="right"><strong>8.47</strong></td><td align="right"><strong>66.54</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.71</strong></td><td align="right"><strong>18.5 KiB</strong></td><td align="right"><strong>10.57</strong></td><td align="right"><strong>3.41</strong></td><td align="right"><strong>8.82</strong></td><td align="right"><strong>53.78</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.63</td><td align="right">5.93 MiB</td><td align="right">0.84</td><td align="right">6.55</td><td align="right">1.76</td><td align="right">20.83</td></tr>
        <tr><td>nvJPEG</td><td align="right">26.98</td><td align="right">54.7 KiB</td><td align="right">4.55</td><td align="right">0.30</td><td align="right">3.87</td><td align="right">13.66</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.20</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>2.79</strong></td><td align="right"><strong>0.24</strong></td><td align="right"><strong>2.71</strong></td><td align="right"><strong>11.78</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.83</td><td align="right">10.55 MiB</td><td align="right">1.07</td><td align="right">10.77</td><td align="right">2.19</td><td align="right">32.37</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.53</td><td align="right">88.8 KiB</td><td align="right">4.35</td><td align="right">0.34</td><td align="right">4.33</td><td align="right">18.83</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>24.77</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>4.55</strong></td><td align="right"><strong>0.25</strong></td><td align="right"><strong>2.85</strong></td><td align="right"><strong>16.97</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">1.88</td><td align="right">27.59</td><td align="right">3.86</td><td align="right">71.15</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.53</td><td align="right">181.4 KiB</td><td align="right">5.34</td><td align="right">0.47</td><td align="right">5.12</td><td align="right">33.83</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.46</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>7.96</strong></td><td align="right"><strong>0.30</strong></td><td align="right"><strong>3.88</strong></td><td align="right"><strong>32.10</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.72</strong></td><td align="right"><strong>24.6 KiB</strong></td><td align="right"><strong>6.78</strong></td><td align="right"><strong>0.29</strong></td><td align="right"><strong>3.58</strong></td><td align="right"><strong>31.51</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.63</td><td align="right">5.93 MiB</td><td align="right">1.25</td><td align="right">10.06</td><td align="right">3.14</td><td align="right">27.21</td></tr>
        <tr><td>nvJPEG</td><td align="right">26.98</td><td align="right">54.7 KiB</td><td align="right">5.88</td><td align="right">0.38</td><td align="right">4.82</td><td align="right">17.40</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.20</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>4.18</strong></td><td align="right"><strong>0.30</strong></td><td align="right"><strong>4.49</strong></td><td align="right"><strong>13.49</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.83</td><td align="right">10.55 MiB</td><td align="right">2.40</td><td align="right">18.68</td><td align="right">3.88</td><td align="right">46.42</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.53</td><td align="right">88.8 KiB</td><td align="right">6.40</td><td align="right">0.43</td><td align="right">4.97</td><td align="right">20.77</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>24.77</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>6.12</strong></td><td align="right"><strong>0.32</strong></td><td align="right"><strong>4.86</strong></td><td align="right"><strong>20.03</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">3.65</td><td align="right">41.95</td><td align="right">7.98</td><td align="right">92.03</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.53</td><td align="right">181.4 KiB</td><td align="right">7.44</td><td align="right">0.60</td><td align="right">7.30</td><td align="right">37.31</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.46</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>10.12</strong></td><td align="right"><strong>0.35</strong></td><td align="right"><strong>5.62</strong></td><td align="right"><strong>37.46</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.72</strong></td><td align="right"><strong>24.6 KiB</strong></td><td align="right"><strong>8.86</strong></td><td align="right"><strong>0.35</strong></td><td align="right"><strong>5.88</strong></td><td align="right"><strong>36.54</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.63</td><td align="right">5.93 MiB</td><td align="right">1.38</td><td align="right">10.93</td><td align="right">3.47</td><td align="right">28.31</td></tr>
        <tr><td>nvJPEG</td><td align="right">26.98</td><td align="right">54.7 KiB</td><td align="right">6.50</td><td align="right">0.45</td><td align="right">5.00</td><td align="right">18.34</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.20</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>4.68</strong></td><td align="right"><strong>0.36</strong></td><td align="right"><strong>4.95</strong></td><td align="right"><strong>15.51</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.83</td><td align="right">10.55 MiB</td><td align="right">2.51</td><td align="right">22.05</td><td align="right">4.73</td><td align="right">49.97</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.53</td><td align="right">88.8 KiB</td><td align="right">6.93</td><td align="right">0.51</td><td align="right">5.15</td><td align="right">21.85</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>24.77</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>6.60</strong></td><td align="right"><strong>0.37</strong></td><td align="right"><strong>5.03</strong></td><td align="right"><strong>21.14</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">4.02</td><td align="right">48.99</td><td align="right">10.06</td><td align="right">100.70</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.53</td><td align="right">181.4 KiB</td><td align="right">8.87</td><td align="right">0.76</td><td align="right">8.75</td><td align="right">39.58</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.46</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>10.47</strong></td><td align="right"><strong>0.46</strong></td><td align="right"><strong>5.73</strong></td><td align="right"><strong>39.96</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.72</strong></td><td align="right"><strong>24.6 KiB</strong></td><td align="right"><strong>9.29</strong></td><td align="right"><strong>0.46</strong></td><td align="right"><strong>6.09</strong></td><td align="right"><strong>38.79</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">26.63</td><td align="right">5.93 MiB</td><td align="right">1.50</td><td align="right">13.31</td><td align="right">3.75</td><td align="right">29.19</td></tr>
        <tr><td>nvJPEG</td><td align="right">26.98</td><td align="right">54.7 KiB</td><td align="right">7.57</td><td align="right">0.96</td><td align="right">6.14</td><td align="right">19.68</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>27.20</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>4.97</strong></td><td align="right"><strong>0.84</strong></td><td align="right"><strong>5.32</strong></td><td align="right"><strong>22.27</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">23.83</td><td align="right">10.55 MiB</td><td align="right">2.78</td><td align="right">23.83</td><td align="right">5.74</td><td align="right">66.36</td></tr>
        <tr><td>nvJPEG</td><td align="right">24.53</td><td align="right">88.8 KiB</td><td align="right">7.28</td><td align="right">0.88</td><td align="right">6.39</td><td align="right">23.40</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>24.77</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>6.87</strong></td><td align="right"><strong>0.71</strong></td><td align="right"><strong>5.32</strong></td><td align="right"><strong>21.82</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">14.58</td><td align="right">23.73 MiB</td><td align="right">4.53</td><td align="right">52.52</td><td align="right">10.69</td><td align="right">112.53</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.53</td><td align="right">181.4 KiB</td><td align="right">9.11</td><td align="right">1.03</td><td align="right">9.18</td><td align="right">45.60</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.46</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>10.70</strong></td><td align="right"><strong>3.46</strong></td><td align="right"><strong>6.11</strong></td><td align="right"><strong>46.26</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>15.72</strong></td><td align="right"><strong>24.6 KiB</strong></td><td align="right"><strong>9.59</strong></td><td align="right"><strong>2.51</strong></td><td align="right"><strong>7.43</strong></td><td align="right"><strong>62.60</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">5.93 MiB</td><td align="right">0.41</td><td align="right">5.41</td><td align="right">0.93</td><td align="right">9.73</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">200.4 KiB</td><td align="right">1.09</td><td align="right">0.40</td><td align="right">1.16</td><td align="right">4.05</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>89.5 KiB</strong></td><td align="right"><strong>2.04</strong></td><td align="right"><strong>0.31</strong></td><td align="right"><strong>1.08</strong></td><td align="right"><strong>4.75</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">10.55 MiB</td><td align="right">0.78</td><td align="right">8.76</td><td align="right">1.48</td><td align="right">15.06</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">338.3 KiB</td><td align="right">1.74</td><td align="right">0.46</td><td align="right">1.69</td><td align="right">5.28</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>149.0 KiB</strong></td><td align="right"><strong>3.50</strong></td><td align="right"><strong>0.33</strong></td><td align="right"><strong>1.45</strong></td><td align="right"><strong>6.50</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">29.85</td><td align="right">23.73 MiB</td><td align="right">1.49</td><td align="right">26.15</td><td align="right">3.16</td><td align="right">40.95</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.71</td><td align="right">692.7 KiB</td><td align="right">2.75</td><td align="right">0.74</td><td align="right">3.41</td><td align="right">8.45</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>282.5 KiB</strong></td><td align="right"><strong>6.78</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>2.46</strong></td><td align="right"><strong>10.99</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>241.8 KiB</strong></td><td align="right"><strong>5.74</strong></td><td align="right"><strong>0.37</strong></td><td align="right"><strong>2.85</strong></td><td align="right"><strong>10.31</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">5.93 MiB</td><td align="right">0.85</td><td align="right">9.72</td><td align="right">1.10</td><td align="right">14.72</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">200.4 KiB</td><td align="right">1.28</td><td align="right">0.58</td><td align="right">1.33</td><td align="right">4.65</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>89.5 KiB</strong></td><td align="right"><strong>2.57</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>1.28</strong></td><td align="right"><strong>5.54</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">10.55 MiB</td><td align="right">0.85</td><td align="right">14.83</td><td align="right">1.67</td><td align="right">22.33</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">338.3 KiB</td><td align="right">1.81</td><td align="right">0.76</td><td align="right">1.84</td><td align="right">5.92</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>149.0 KiB</strong></td><td align="right"><strong>3.57</strong></td><td align="right"><strong>0.45</strong></td><td align="right"><strong>1.61</strong></td><td align="right"><strong>7.03</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">29.85</td><td align="right">23.73 MiB</td><td align="right">3.48</td><td align="right">37.19</td><td align="right">4.93</td><td align="right">52.11</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.71</td><td align="right">692.7 KiB</td><td align="right">3.22</td><td align="right">1.26</td><td align="right">3.58</td><td align="right">9.52</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>282.5 KiB</strong></td><td align="right"><strong>6.98</strong></td><td align="right"><strong>0.65</strong></td><td align="right"><strong>2.69</strong></td><td align="right"><strong>11.65</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>241.8 KiB</strong></td><td align="right"><strong>5.98</strong></td><td align="right"><strong>0.57</strong></td><td align="right"><strong>3.22</strong></td><td align="right"><strong>11.07</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">5.93 MiB</td><td align="right">1.05</td><td align="right">10.30</td><td align="right">1.51</td><td align="right">15.40</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">200.4 KiB</td><td align="right">1.74</td><td align="right">0.73</td><td align="right">1.48</td><td align="right">5.14</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>89.5 KiB</strong></td><td align="right"><strong>2.82</strong></td><td align="right"><strong>0.59</strong></td><td align="right"><strong>1.39</strong></td><td align="right"><strong>5.86</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">10.55 MiB</td><td align="right">1.72</td><td align="right">16.67</td><td align="right">2.48</td><td align="right">24.56</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">338.3 KiB</td><td align="right">2.89</td><td align="right">0.93</td><td align="right">1.91</td><td align="right">6.31</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>149.0 KiB</strong></td><td align="right"><strong>3.70</strong></td><td align="right"><strong>0.52</strong></td><td align="right"><strong>1.84</strong></td><td align="right"><strong>7.36</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">29.85</td><td align="right">23.73 MiB</td><td align="right">3.76</td><td align="right">43.94</td><td align="right">5.38</td><td align="right">59.53</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.71</td><td align="right">692.7 KiB</td><td align="right">4.87</td><td align="right">1.45</td><td align="right">3.65</td><td align="right">10.84</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>282.5 KiB</strong></td><td align="right"><strong>8.80</strong></td><td align="right"><strong>0.84</strong></td><td align="right"><strong>2.83</strong></td><td align="right"><strong>13.27</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>241.8 KiB</strong></td><td align="right"><strong>7.81</strong></td><td align="right"><strong>0.74</strong></td><td align="right"><strong>3.38</strong></td><td align="right"><strong>12.62</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">5.93 MiB</td><td align="right">1.22</td><td align="right">11.20</td><td align="right">1.65</td><td align="right">16.91</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">200.4 KiB</td><td align="right">1.90</td><td align="right">0.91</td><td align="right">1.65</td><td align="right">5.38</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>89.5 KiB</strong></td><td align="right"><strong>2.98</strong></td><td align="right"><strong>0.74</strong></td><td align="right"><strong>1.50</strong></td><td align="right"><strong>6.40</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">29.83</td><td align="right">10.55 MiB</td><td align="right">2.00</td><td align="right">29.01</td><td align="right">2.78</td><td align="right">39.42</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.85</td><td align="right">338.3 KiB</td><td align="right">3.11</td><td align="right">1.19</td><td align="right">2.14</td><td align="right">7.23</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.85</strong></td><td align="right"><strong>149.0 KiB</strong></td><td align="right"><strong>4.58</strong></td><td align="right"><strong>0.74</strong></td><td align="right"><strong>1.94</strong></td><td align="right"><strong>7.74</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">29.85</td><td align="right">23.73 MiB</td><td align="right">4.18</td><td align="right">51.73</td><td align="right">5.64</td><td align="right">68.91</td></tr>
        <tr><td>nvJPEG</td><td align="right">29.71</td><td align="right">692.7 KiB</td><td align="right">5.25</td><td align="right">2.70</td><td align="right">4.08</td><td align="right">12.35</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>282.5 KiB</strong></td><td align="right"><strong>9.01</strong></td><td align="right"><strong>4.28</strong></td><td align="right"><strong>4.79</strong></td><td align="right"><strong>17.11</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>29.97</strong></td><td align="right"><strong>241.8 KiB</strong></td><td align="right"><strong>7.93</strong></td><td align="right"><strong>3.09</strong></td><td align="right"><strong>5.29</strong></td><td align="right"><strong>15.91</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">45.96</td><td align="right">5.93 MiB</td><td align="right">20.40</td><td align="right">20.03</td><td align="right">0.91</td><td align="right">51.12</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.66</td><td align="right">221.0 KiB</td><td align="right">4.50</td><td align="right">1.28</td><td align="right">1.04</td><td align="right">15.77</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.64</strong></td><td align="right"><strong>53.4 KiB</strong></td><td align="right"><strong>6.25</strong></td><td align="right"><strong>0.62</strong></td><td align="right"><strong>0.94</strong></td><td align="right"><strong>15.94</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.16</td><td align="right">23.73 MiB</td><td align="right">2.30</td><td align="right">109.37</td><td align="right">2.72</td><td align="right">141.53</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.90</td><td align="right">1.09 MiB</td><td align="right">9.99</td><td align="right">4.05</td><td align="right">3.37</td><td align="right">26.83</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.11</strong></td><td align="right"><strong>182.4 KiB</strong></td><td align="right"><strong>6.74</strong></td><td align="right"><strong>1.04</strong></td><td align="right"><strong>2.28</strong></td><td align="right"><strong>18.24</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>60.12</strong></td><td align="right"><strong>175.0 KiB</strong></td><td align="right"><strong>6.40</strong></td><td align="right"><strong>1.03</strong></td><td align="right"><strong>2.73</strong></td><td align="right"><strong>18.35</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">45.96</td><td align="right">5.93 MiB</td><td align="right">22.92</td><td align="right">25.37</td><td align="right">1.11</td><td align="right">62.93</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.66</td><td align="right">221.0 KiB</td><td align="right">4.74</td><td align="right">1.68</td><td align="right">1.14</td><td align="right">18.16</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.64</strong></td><td align="right"><strong>53.4 KiB</strong></td><td align="right"><strong>7.97</strong></td><td align="right"><strong>0.86</strong></td><td align="right"><strong>1.10</strong></td><td align="right"><strong>18.85</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.16</td><td align="right">23.73 MiB</td><td align="right">3.69</td><td align="right">126.68</td><td align="right">4.28</td><td align="right">162.18</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.90</td><td align="right">1.09 MiB</td><td align="right">15.46</td><td align="right">4.71</td><td align="right">3.55</td><td align="right">35.00</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.11</strong></td><td align="right"><strong>182.4 KiB</strong></td><td align="right"><strong>7.58</strong></td><td align="right"><strong>1.27</strong></td><td align="right"><strong>2.51</strong></td><td align="right"><strong>19.68</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>60.12</strong></td><td align="right"><strong>175.0 KiB</strong></td><td align="right"><strong>7.72</strong></td><td align="right"><strong>1.33</strong></td><td align="right"><strong>2.94</strong></td><td align="right"><strong>20.18</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">45.96</td><td align="right">5.93 MiB</td><td align="right">24.69</td><td align="right">27.71</td><td align="right">1.53</td><td align="right">78.94</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.66</td><td align="right">221.0 KiB</td><td align="right">4.96</td><td align="right">1.94</td><td align="right">1.25</td><td align="right">19.17</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.64</strong></td><td align="right"><strong>53.4 KiB</strong></td><td align="right"><strong>8.49</strong></td><td align="right"><strong>1.04</strong></td><td align="right"><strong>1.18</strong></td><td align="right"><strong>19.91</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.16</td><td align="right">23.73 MiB</td><td align="right">4.40</td><td align="right">134.28</td><td align="right">4.71</td><td align="right">171.34</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.90</td><td align="right">1.09 MiB</td><td align="right">16.14</td><td align="right">5.37</td><td align="right">3.62</td><td align="right">36.60</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.11</strong></td><td align="right"><strong>182.4 KiB</strong></td><td align="right"><strong>8.10</strong></td><td align="right"><strong>1.42</strong></td><td align="right"><strong>2.68</strong></td><td align="right"><strong>20.62</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>60.12</strong></td><td align="right"><strong>175.0 KiB</strong></td><td align="right"><strong>8.33</strong></td><td align="right"><strong>1.60</strong></td><td align="right"><strong>3.11</strong></td><td align="right"><strong>21.26</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">45.96</td><td align="right">5.93 MiB</td><td align="right">26.67</td><td align="right">33.08</td><td align="right">2.01</td><td align="right">83.69</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.66</td><td align="right">221.0 KiB</td><td align="right">5.24</td><td align="right">2.75</td><td align="right">1.60</td><td align="right">20.13</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>59.64</strong></td><td align="right"><strong>53.4 KiB</strong></td><td align="right"><strong>9.00</strong></td><td align="right"><strong>1.36</strong></td><td align="right"><strong>1.28</strong></td><td align="right"><strong>22.62</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">15.16</td><td align="right">23.73 MiB</td><td align="right">5.77</td><td align="right">138.91</td><td align="right">5.14</td><td align="right">174.61</td></tr>
        <tr><td>nvJPEG</td><td align="right">59.90</td><td align="right">1.09 MiB</td><td align="right">16.74</td><td align="right">6.62</td><td align="right">4.75</td><td align="right">38.00</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>60.11</strong></td><td align="right"><strong>182.4 KiB</strong></td><td align="right"><strong>8.54</strong></td><td align="right"><strong>3.80</strong></td><td align="right"><strong>4.18</strong></td><td align="right"><strong>25.41</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>60.12</strong></td><td align="right"><strong>175.0 KiB</strong></td><td align="right"><strong>9.66</strong></td><td align="right"><strong>4.36</strong></td><td align="right"><strong>5.83</strong></td><td align="right"><strong>24.18</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.78</td><td align="right">5.93 MiB</td><td align="right">0.34</td><td align="right">13.39</td><td align="right">1.10</td><td align="right">24.10</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.58</td><td align="right">62.4 KiB</td><td align="right">3.83</td><td align="right">0.58</td><td align="right">1.14</td><td align="right">13.56</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.67</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.47</strong></td><td align="right"><strong>0.47</strong></td><td align="right"><strong>0.88</strong></td><td align="right"><strong>11.80</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.55</td><td align="right">10.55 MiB</td><td align="right">0.63</td><td align="right">26.14</td><td align="right">1.79</td><td align="right">42.84</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">102.6 KiB</td><td align="right">5.16</td><td align="right">0.70</td><td align="right">1.70</td><td align="right">19.09</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.57</strong></td><td align="right"><strong>14.0 KiB</strong></td><td align="right"><strong>4.23</strong></td><td align="right"><strong>0.50</strong></td><td align="right"><strong>1.10</strong></td><td align="right"><strong>16.87</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.25</td><td align="right">23.73 MiB</td><td align="right">1.69</td><td align="right">55.45</td><td align="right">2.97</td><td align="right">113.68</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.20</td><td align="right">209.1 KiB</td><td align="right">5.74</td><td align="right">1.09</td><td align="right">3.36</td><td align="right">51.16</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>7.06</strong></td><td align="right"><strong>0.46</strong></td><td align="right"><strong>1.82</strong></td><td align="right"><strong>87.00</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.13</strong></td><td align="right"><strong>18.3 KiB</strong></td><td align="right"><strong>8.32</strong></td><td align="right"><strong>0.48</strong></td><td align="right"><strong>2.29</strong></td><td align="right"><strong>88.10</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.78</td><td align="right">5.93 MiB</td><td align="right">0.79</td><td align="right">17.14</td><td align="right">1.87</td><td align="right">31.74</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.58</td><td align="right">62.4 KiB</td><td align="right">5.63</td><td align="right">0.85</td><td align="right">1.26</td><td align="right">17.43</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.67</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>3.67</strong></td><td align="right"><strong>0.74</strong></td><td align="right"><strong>1.05</strong></td><td align="right"><strong>15.31</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.55</td><td align="right">10.55 MiB</td><td align="right">2.11</td><td align="right">33.14</td><td align="right">3.50</td><td align="right">56.78</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">102.6 KiB</td><td align="right">7.14</td><td align="right">1.02</td><td align="right">1.83</td><td align="right">24.04</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.57</strong></td><td align="right"><strong>14.0 KiB</strong></td><td align="right"><strong>6.13</strong></td><td align="right"><strong>0.81</strong></td><td align="right"><strong>1.21</strong></td><td align="right"><strong>22.74</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.25</td><td align="right">23.73 MiB</td><td align="right">7.53</td><td align="right">70.76</td><td align="right">5.42</td><td align="right">170.73</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.20</td><td align="right">209.1 KiB</td><td align="right">14.06</td><td align="right">1.78</td><td align="right">3.50</td><td align="right">87.96</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>8.39</strong></td><td align="right"><strong>0.74</strong></td><td align="right"><strong>1.96</strong></td><td align="right"><strong>151.57</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.13</strong></td><td align="right"><strong>18.3 KiB</strong></td><td align="right"><strong>9.81</strong></td><td align="right"><strong>0.77</strong></td><td align="right"><strong>2.49</strong></td><td align="right"><strong>151.07</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.78</td><td align="right">5.93 MiB</td><td align="right">1.10</td><td align="right">18.24</td><td align="right">2.35</td><td align="right">34.51</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.58</td><td align="right">62.4 KiB</td><td align="right">6.09</td><td align="right">1.01</td><td align="right">1.35</td><td align="right">18.44</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.67</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.13</strong></td><td align="right"><strong>0.91</strong></td><td align="right"><strong>1.19</strong></td><td align="right"><strong>15.87</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.55</td><td align="right">10.55 MiB</td><td align="right">3.27</td><td align="right">36.33</td><td align="right">4.29</td><td align="right">60.20</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">102.6 KiB</td><td align="right">7.88</td><td align="right">1.13</td><td align="right">1.89</td><td align="right">25.19</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.57</strong></td><td align="right"><strong>14.0 KiB</strong></td><td align="right"><strong>7.00</strong></td><td align="right"><strong>0.98</strong></td><td align="right"><strong>1.35</strong></td><td align="right"><strong>23.74</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.25</td><td align="right">23.73 MiB</td><td align="right">9.37</td><td align="right">73.90</td><td align="right">7.13</td><td align="right">176.54</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.20</td><td align="right">209.1 KiB</td><td align="right">15.88</td><td align="right">2.19</td><td align="right">3.63</td><td align="right">92.87</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>8.90</strong></td><td align="right"><strong>0.95</strong></td><td align="right"><strong>2.12</strong></td><td align="right"><strong>152.90</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.13</strong></td><td align="right"><strong>18.3 KiB</strong></td><td align="right"><strong>10.49</strong></td><td align="right"><strong>0.97</strong></td><td align="right"><strong>2.61</strong></td><td align="right"><strong>153.72</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.78</td><td align="right">5.93 MiB</td><td align="right">1.89</td><td align="right">19.22</td><td align="right">3.60</td><td align="right">36.04</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.58</td><td align="right">62.4 KiB</td><td align="right">6.81</td><td align="right">1.39</td><td align="right">2.02</td><td align="right">19.43</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.67</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.60</strong></td><td align="right"><strong>1.32</strong></td><td align="right"><strong>1.32</strong></td><td align="right"><strong>16.45</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.55</td><td align="right">10.55 MiB</td><td align="right">4.04</td><td align="right">39.26</td><td align="right">5.00</td><td align="right">64.39</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">102.6 KiB</td><td align="right">8.94</td><td align="right">1.21</td><td align="right">2.56</td><td align="right">26.41</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.57</strong></td><td align="right"><strong>14.0 KiB</strong></td><td align="right"><strong>7.98</strong></td><td align="right"><strong>1.13</strong></td><td align="right"><strong>1.47</strong></td><td align="right"><strong>24.65</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.25</td><td align="right">23.73 MiB</td><td align="right">9.86</td><td align="right">76.83</td><td align="right">9.33</td><td align="right">182.43</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.20</td><td align="right">209.1 KiB</td><td align="right">16.67</td><td align="right">2.29</td><td align="right">3.73</td><td align="right">96.78</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>9.45</strong></td><td align="right"><strong>2.80</strong></td><td align="right"><strong>4.03</strong></td><td align="right"><strong>155.12</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.13</strong></td><td align="right"><strong>18.3 KiB</strong></td><td align="right"><strong>11.18</strong></td><td align="right"><strong>3.41</strong></td><td align="right"><strong>4.43</strong></td><td align="right"><strong>155.64</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.66</td><td align="right">5.93 MiB</td><td align="right">0.33</td><td align="right">11.03</td><td align="right">1.01</td><td align="right">24.83</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.45</td><td align="right">54.7 KiB</td><td align="right">4.64</td><td align="right">0.49</td><td align="right">1.08</td><td align="right">12.82</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.53</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>2.91</strong></td><td align="right"><strong>0.38</strong></td><td align="right"><strong>0.81</strong></td><td align="right"><strong>10.58</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.43</td><td align="right">10.55 MiB</td><td align="right">0.54</td><td align="right">22.23</td><td align="right">1.71</td><td align="right">41.89</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">88.8 KiB</td><td align="right">5.10</td><td align="right">0.58</td><td align="right">1.62</td><td align="right">16.80</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.45</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>4.28</strong></td><td align="right"><strong>0.47</strong></td><td align="right"><strong>1.05</strong></td><td align="right"><strong>15.68</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.18</td><td align="right">23.73 MiB</td><td align="right">1.13</td><td align="right">46.73</td><td align="right">2.78</td><td align="right">99.88</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.15</td><td align="right">181.2 KiB</td><td align="right">7.90</td><td align="right">0.95</td><td align="right">3.33</td><td align="right">47.37</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>7.70</strong></td><td align="right"><strong>0.47</strong></td><td align="right"><strong>1.76</strong></td><td align="right"><strong>24.47</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>24.7 KiB</strong></td><td align="right"><strong>10.19</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>2.10</strong></td><td align="right"><strong>23.31</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.66</td><td align="right">5.93 MiB</td><td align="right">0.67</td><td align="right">13.00</td><td align="right">1.83</td><td align="right">29.96</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.45</td><td align="right">54.7 KiB</td><td align="right">6.09</td><td align="right">0.76</td><td align="right">1.26</td><td align="right">15.85</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.53</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>4.11</strong></td><td align="right"><strong>0.57</strong></td><td align="right"><strong>1.03</strong></td><td align="right"><strong>13.60</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.43</td><td align="right">10.55 MiB</td><td align="right">1.19</td><td align="right">27.16</td><td align="right">3.13</td><td align="right">51.95</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">88.8 KiB</td><td align="right">6.53</td><td align="right">0.88</td><td align="right">1.82</td><td align="right">23.48</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.45</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>5.40</strong></td><td align="right"><strong>0.74</strong></td><td align="right"><strong>1.27</strong></td><td align="right"><strong>21.94</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.18</td><td align="right">23.73 MiB</td><td align="right">2.86</td><td align="right">58.01</td><td align="right">4.87</td><td align="right">134.58</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.15</td><td align="right">181.2 KiB</td><td align="right">13.44</td><td align="right">1.41</td><td align="right">3.51</td><td align="right">70.69</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>8.81</strong></td><td align="right"><strong>0.73</strong></td><td align="right"><strong>1.87</strong></td><td align="right"><strong>27.78</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>24.7 KiB</strong></td><td align="right"><strong>12.14</strong></td><td align="right"><strong>0.70</strong></td><td align="right"><strong>2.27</strong></td><td align="right"><strong>28.33</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.66</td><td align="right">5.93 MiB</td><td align="right">0.79</td><td align="right">14.51</td><td align="right">2.31</td><td align="right">30.88</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.45</td><td align="right">54.7 KiB</td><td align="right">6.50</td><td align="right">0.86</td><td align="right">1.63</td><td align="right">16.98</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.53</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>4.49</strong></td><td align="right"><strong>0.67</strong></td><td align="right"><strong>1.15</strong></td><td align="right"><strong>14.39</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.43</td><td align="right">10.55 MiB</td><td align="right">1.50</td><td align="right">31.14</td><td align="right">4.13</td><td align="right">54.66</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">88.8 KiB</td><td align="right">7.16</td><td align="right">1.01</td><td align="right">2.43</td><td align="right">24.88</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.45</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>5.75</strong></td><td align="right"><strong>1.23</strong></td><td align="right"><strong>1.34</strong></td><td align="right"><strong>23.39</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.18</td><td align="right">23.73 MiB</td><td align="right">3.97</td><td align="right">66.69</td><td align="right">5.85</td><td align="right">259.78</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.15</td><td align="right">181.2 KiB</td><td align="right">15.06</td><td align="right">1.57</td><td align="right">3.60</td><td align="right">225.81</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>9.83</strong></td><td align="right"><strong>0.91</strong></td><td align="right"><strong>1.97</strong></td><td align="right"><strong>28.73</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>24.7 KiB</strong></td><td align="right"><strong>13.19</strong></td><td align="right"><strong>0.83</strong></td><td align="right"><strong>2.39</strong></td><td align="right"><strong>29.82</strong></td></tr>
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
        <tr><td rowspan="3">FHD</td><td>BGR8</td><td align="right">15.66</td><td align="right">5.93 MiB</td><td align="right">0.96</td><td align="right">17.26</td><td align="right">2.66</td><td align="right">34.43</td></tr>
        <tr><td>nvJPEG</td><td align="right">15.45</td><td align="right">54.7 KiB</td><td align="right">6.92</td><td align="right">1.88</td><td align="right">1.91</td><td align="right">17.51</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>15.53</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>4.95</strong></td><td align="right"><strong>0.85</strong></td><td align="right"><strong>1.34</strong></td><td align="right"><strong>14.92</strong></td></tr>
        <tr><td rowspan="3">QHD</td><td>BGR8</td><td align="right">13.43</td><td align="right">10.55 MiB</td><td align="right">1.79</td><td align="right">34.18</td><td align="right">4.49</td><td align="right">56.40</td></tr>
        <tr><td>nvJPEG</td><td align="right">13.33</td><td align="right">88.8 KiB</td><td align="right">11.52</td><td align="right">1.07</td><td align="right">2.62</td><td align="right">29.91</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>13.45</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>6.26</strong></td><td align="right"><strong>1.30</strong></td><td align="right"><strong>1.44</strong></td><td align="right"><strong>24.40</strong></td></tr>
        <tr><td rowspan="4">4K</td><td>BGR8</td><td align="right">8.18</td><td align="right">23.73 MiB</td><td align="right">4.13</td><td align="right">84.13</td><td align="right">8.00</td><td align="right">301.22</td></tr>
        <tr><td>nvJPEG</td><td align="right">8.15</td><td align="right">181.2 KiB</td><td align="right">16.13</td><td align="right">1.71</td><td align="right">3.75</td><td align="right">258.92</td></tr>
        <tr><td><strong>H.264</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>10.69</strong></td><td align="right"><strong>2.76</strong></td><td align="right"><strong>2.22</strong></td><td align="right"><strong>30.22</strong></td></tr>
        <tr><td><strong>H.265</strong></td><td align="right"><strong>9.12</strong></td><td align="right"><strong>24.7 KiB</strong></td><td align="right"><strong>14.17</strong></td><td align="right"><strong>2.82</strong></td><td align="right"><strong>3.45</strong></td><td align="right"><strong>31.30</strong></td></tr>
    </tbody>
</table>

</details>

</details>

## Method and limits

- Source and receiver both use Holoscan `5.0.0.dev20260928`. Runs collect 60 seconds after a 30-second warmup; 8 earlier configurations retain their longer 10,000-sample runs. Actual durations, sample counts, incomplete timing coverage and frame-loss counters are in the CSV.
- H.264/H.265 use NVENC P1, ultra-low-latency, QP 24, independent frames, no B frames and no lookahead. nvJPEG quality is 85. Equal QP does not imply equal visual quality.
- BRIO captures YUYV at FHD and MJPEG at QHD/4K. MJPEG decoding inside camera capture precedes the measured buffer boundary. IMX274 uses native sensor modes. Simulation recreates each camera at the requested render resolution.
- Timing starts when a USB BGR buffer, processed HSB Bayer buffer or simulator RGB buffer is available. Sensor exposure, earlier producer work and physical scanout are excluded. The full path includes frame preparation, encoder queue, encode/pack, source relay/queue, send queue, transport, receive queue, decode/upload and viewer handoff.
- Percentiles use linear interpolation over at most 10,000 valid samples. Timing excludes the first two seconds after reset; native summaries refresh every five seconds. Browser totals use frames matched by RTP timestamp. Transport uses the receiver's recorded `steady_metrics.delivery_ms` percentiles.
- Same-host timing uses a monotonic clock. Remote timing uses fresh UTC bounds or four-timestamp relative estimates. Clock uncertainty is recorded in the CSV; unresolved timing remains unavailable.
- Frame size excludes TLS/TCP/IP overhead. FPS, frame spacing, sequence gaps and browser drops are separate from latency. Browser FPS subtracts dropped frames from the [total video frame counter](https://w3c.github.io/media-playback-quality/); sequence gaps use application stream numbers.
- Streams retain their requested resolution through decoding. Native windows are capped at 1280×720; Chromium uses a 1600×1000 dashboard viewport. These are stream-resolution tests with display scaling afterward. Browser hardware decoding was not confirmed.

Each configuration has one measured run. P99.9 can depend on only a few frames in a 60-second sample, especially for slower simulation sources. Background services remained running; power, clocks and physical camera scenes were not held constant. Remote tests also change source hardware, so their differences are not solely network overhead. Isaac Sim rendering and CPU readback/IPC can limit throughput independently of the codec.

## Repeat one configuration

Start patient and surgeon services on SDK 5, discover the cameras, then collect a run:

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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.43</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.63</strong></td><td align="right"><strong>0.30</strong></td><td align="right"><strong>2.60</strong></td><td align="right"><strong>37.18</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.17</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>4.50</strong></td><td align="right"><strong>0.31</strong></td><td align="right"><strong>4.20</strong></td><td align="right"><strong>43.10</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.07</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>8.86</strong></td><td align="right"><strong>0.32</strong></td><td align="right"><strong>9.30</strong></td><td align="right"><strong>64.00</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.43</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>3.74</strong></td><td align="right"><strong>0.41</strong></td><td align="right"><strong>3.20</strong></td><td align="right"><strong>53.28</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.17</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>6.43</strong></td><td align="right"><strong>0.40</strong></td><td align="right"><strong>5.40</strong></td><td align="right"><strong>60.15</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.07</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>11.76</strong></td><td align="right"><strong>0.41</strong></td><td align="right"><strong>12.00</strong></td><td align="right"><strong>81.24</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.43</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.24</strong></td><td align="right"><strong>0.49</strong></td><td align="right"><strong>3.35</strong></td><td align="right"><strong>56.66</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.17</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>7.14</strong></td><td align="right"><strong>0.45</strong></td><td align="right"><strong>5.60</strong></td><td align="right"><strong>64.59</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.07</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>15.02</strong></td><td align="right"><strong>0.46</strong></td><td align="right"><strong>12.60</strong></td><td align="right"><strong>84.89</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.43</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.90</strong></td><td align="right"><strong>0.96</strong></td><td align="right"><strong>4.89</strong></td><td align="right"><strong>58.86</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.17</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>7.56</strong></td><td align="right"><strong>0.57</strong></td><td align="right"><strong>6.41</strong></td><td align="right"><strong>67.05</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.07</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>16.08</strong></td><td align="right"><strong>0.56</strong></td><td align="right"><strong>43.36</strong></td><td align="right"><strong>98.34</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.22</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>2.84</strong></td><td align="right"><strong>0.19</strong></td><td align="right"><strong>2.80</strong></td><td align="right"><strong>35.79</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.20</strong></td><td align="right"><strong>19.2 KiB</strong></td><td align="right"><strong>4.66</strong></td><td align="right"><strong>0.21</strong></td><td align="right"><strong>4.70</strong></td><td align="right"><strong>43.64</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.09</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>8.50</strong></td><td align="right"><strong>0.23</strong></td><td align="right"><strong>10.50</strong></td><td align="right"><strong>61.75</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.22</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>4.27</strong></td><td align="right"><strong>0.61</strong></td><td align="right"><strong>3.50</strong></td><td align="right"><strong>52.21</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.20</strong></td><td align="right"><strong>19.2 KiB</strong></td><td align="right"><strong>6.26</strong></td><td align="right"><strong>0.32</strong></td><td align="right"><strong>5.90</strong></td><td align="right"><strong>60.59</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.09</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>10.53</strong></td><td align="right"><strong>0.34</strong></td><td align="right"><strong>13.20</strong></td><td align="right"><strong>79.13</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.22</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>4.71</strong></td><td align="right"><strong>0.85</strong></td><td align="right"><strong>3.60</strong></td><td align="right"><strong>55.28</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.20</strong></td><td align="right"><strong>19.2 KiB</strong></td><td align="right"><strong>6.84</strong></td><td align="right"><strong>0.60</strong></td><td align="right"><strong>6.10</strong></td><td align="right"><strong>64.67</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.09</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>11.16</strong></td><td align="right"><strong>0.40</strong></td><td align="right"><strong>14.18</strong></td><td align="right"><strong>83.82</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>26.22</strong></td><td align="right"><strong>13.7 KiB</strong></td><td align="right"><strong>5.10</strong></td><td align="right"><strong>1.23</strong></td><td align="right"><strong>4.46</strong></td><td align="right"><strong>58.16</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>24.20</strong></td><td align="right"><strong>19.2 KiB</strong></td><td align="right"><strong>7.30</strong></td><td align="right"><strong>0.95</strong></td><td align="right"><strong>7.23</strong></td><td align="right"><strong>67.33</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>20.09</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>12.16</strong></td><td align="right"><strong>1.05</strong></td><td align="right"><strong>38.77</strong></td><td align="right"><strong>89.46</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>30.00</strong></td><td align="right"><strong>84.2 KiB</strong></td><td align="right"><strong>2.11</strong></td><td align="right"><strong>0.35</strong></td><td align="right"><strong>6.20</strong></td><td align="right"><strong>31.77</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>29.69</strong></td><td align="right"><strong>130.3 KiB</strong></td><td align="right"><strong>3.48</strong></td><td align="right"><strong>0.40</strong></td><td align="right"><strong>10.30</strong></td><td align="right"><strong>44.87</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.26</strong></td><td align="right"><strong>283.4 KiB</strong></td><td align="right"><strong>6.81</strong></td><td align="right"><strong>0.60</strong></td><td align="right"><strong>22.70</strong></td><td align="right"><strong>72.69</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>30.00</strong></td><td align="right"><strong>84.2 KiB</strong></td><td align="right"><strong>2.83</strong></td><td align="right"><strong>0.52</strong></td><td align="right"><strong>6.60</strong></td><td align="right"><strong>34.36</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>29.69</strong></td><td align="right"><strong>130.3 KiB</strong></td><td align="right"><strong>3.88</strong></td><td align="right"><strong>0.55</strong></td><td align="right"><strong>11.10</strong></td><td align="right"><strong>47.39</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.26</strong></td><td align="right"><strong>283.4 KiB</strong></td><td align="right"><strong>7.38</strong></td><td align="right"><strong>0.88</strong></td><td align="right"><strong>24.10</strong></td><td align="right"><strong>77.77</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>30.00</strong></td><td align="right"><strong>84.2 KiB</strong></td><td align="right"><strong>3.05</strong></td><td align="right"><strong>0.66</strong></td><td align="right"><strong>8.00</strong></td><td align="right"><strong>34.99</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>29.69</strong></td><td align="right"><strong>130.3 KiB</strong></td><td align="right"><strong>5.04</strong></td><td align="right"><strong>0.70</strong></td><td align="right"><strong>14.18</strong></td><td align="right"><strong>47.98</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.26</strong></td><td align="right"><strong>283.4 KiB</strong></td><td align="right"><strong>9.02</strong></td><td align="right"><strong>1.04</strong></td><td align="right"><strong>26.18</strong></td><td align="right"><strong>79.00</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>30.00</strong></td><td align="right"><strong>84.2 KiB</strong></td><td align="right"><strong>3.81</strong></td><td align="right"><strong>0.88</strong></td><td align="right"><strong>16.94</strong></td><td align="right"><strong>48.50</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>29.69</strong></td><td align="right"><strong>130.3 KiB</strong></td><td align="right"><strong>6.50</strong></td><td align="right"><strong>2.14</strong></td><td align="right"><strong>31.76</strong></td><td align="right"><strong>69.30</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>26.26</strong></td><td align="right"><strong>283.4 KiB</strong></td><td align="right"><strong>9.92</strong></td><td align="right"><strong>1.37</strong></td><td align="right"><strong>76.73</strong></td><td align="right"><strong>120.35</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>59.62</strong></td><td align="right"><strong>38.8 KiB</strong></td><td align="right"><strong>6.10</strong></td><td align="right"><strong>0.54</strong></td><td align="right"><strong>4.10</strong></td><td align="right"><strong>43.55</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>32.11</strong></td><td align="right"><strong>346.2 KiB</strong></td><td align="right"><strong>7.27</strong></td><td align="right"><strong>1.60</strong></td><td align="right"><strong>28.00</strong></td><td align="right"><strong>69.26</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>59.62</strong></td><td align="right"><strong>38.8 KiB</strong></td><td align="right"><strong>7.86</strong></td><td align="right"><strong>0.75</strong></td><td align="right"><strong>4.20</strong></td><td align="right"><strong>50.87</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>32.11</strong></td><td align="right"><strong>346.2 KiB</strong></td><td align="right"><strong>7.74</strong></td><td align="right"><strong>2.03</strong></td><td align="right"><strong>28.80</strong></td><td align="right"><strong>80.35</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>59.62</strong></td><td align="right"><strong>38.8 KiB</strong></td><td align="right"><strong>8.49</strong></td><td align="right"><strong>0.88</strong></td><td align="right"><strong>5.20</strong></td><td align="right"><strong>51.67</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>32.11</strong></td><td align="right"><strong>346.2 KiB</strong></td><td align="right"><strong>8.17</strong></td><td align="right"><strong>2.20</strong></td><td align="right"><strong>30.83</strong></td><td align="right"><strong>84.13</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>59.62</strong></td><td align="right"><strong>38.8 KiB</strong></td><td align="right"><strong>9.04</strong></td><td align="right"><strong>1.33</strong></td><td align="right"><strong>5.32</strong></td><td align="right"><strong>52.10</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>32.11</strong></td><td align="right"><strong>346.2 KiB</strong></td><td align="right"><strong>8.49</strong></td><td align="right"><strong>2.57</strong></td><td align="right"><strong>34.77</strong></td><td align="right"><strong>87.45</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>2.45</strong></td><td align="right"><strong>0.51</strong></td><td align="right"><strong>2.30</strong></td><td align="right"><strong>36.22</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>4.21</strong></td><td align="right"><strong>0.56</strong></td><td align="right"><strong>3.90</strong></td><td align="right"><strong>41.17</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>8.32</strong></td><td align="right"><strong>0.69</strong></td><td align="right"><strong>8.60</strong></td><td align="right"><strong>99.11</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>3.84</strong></td><td align="right"><strong>0.76</strong></td><td align="right"><strong>3.00</strong></td><td align="right"><strong>54.51</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>6.64</strong></td><td align="right"><strong>1.03</strong></td><td align="right"><strong>4.00</strong></td><td align="right"><strong>59.07</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>15.96</strong></td><td align="right"><strong>1.14</strong></td><td align="right"><strong>9.33</strong></td><td align="right"><strong>125.96</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>4.44</strong></td><td align="right"><strong>0.87</strong></td><td align="right"><strong>3.13</strong></td><td align="right"><strong>58.21</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>7.31</strong></td><td align="right"><strong>1.19</strong></td><td align="right"><strong>5.30</strong></td><td align="right"><strong>63.22</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>17.69</strong></td><td align="right"><strong>1.36</strong></td><td align="right"><strong>11.82</strong></td><td align="right"><strong>136.48</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>10.1 KiB</strong></td><td align="right"><strong>5.20</strong></td><td align="right"><strong>1.13</strong></td><td align="right"><strong>3.50</strong></td><td align="right"><strong>59.66</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>14.1 KiB</strong></td><td align="right"><strong>8.52</strong></td><td align="right"><strong>1.40</strong></td><td align="right"><strong>5.93</strong></td><td align="right"><strong>66.89</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>23.2 KiB</strong></td><td align="right"><strong>19.02</strong></td><td align="right"><strong>1.63</strong></td><td align="right"><strong>25.44</strong></td><td align="right"><strong>244.93</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>2.76</strong></td><td align="right"><strong>0.44</strong></td><td align="right"><strong>2.50</strong></td><td align="right"><strong>36.56</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>4.24</strong></td><td align="right"><strong>0.43</strong></td><td align="right"><strong>4.30</strong></td><td align="right"><strong>40.63</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>8.05</strong></td><td align="right"><strong>0.68</strong></td><td align="right"><strong>9.50</strong></td><td align="right"><strong>83.69</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>4.03</strong></td><td align="right"><strong>0.76</strong></td><td align="right"><strong>2.80</strong></td><td align="right"><strong>53.69</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>5.25</strong></td><td align="right"><strong>0.92</strong></td><td align="right"><strong>4.40</strong></td><td align="right"><strong>58.47</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>11.47</strong></td><td align="right"><strong>1.25</strong></td><td align="right"><strong>12.30</strong></td><td align="right"><strong>111.38</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>4.47</strong></td><td align="right"><strong>0.97</strong></td><td align="right"><strong>3.30</strong></td><td align="right"><strong>57.94</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>5.50</strong></td><td align="right"><strong>1.10</strong></td><td align="right"><strong>5.60</strong></td><td align="right"><strong>63.58</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>12.56</strong></td><td align="right"><strong>1.47</strong></td><td align="right"><strong>13.32</strong></td><td align="right"><strong>253.69</strong></td></tr>
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
        <tr><td>FHD</td><td><strong>H.264</strong></td><td align="right"><strong>15.69</strong></td><td align="right"><strong>13.6 KiB</strong></td><td align="right"><strong>4.65</strong></td><td align="right"><strong>1.19</strong></td><td align="right"><strong>3.51</strong></td><td align="right"><strong>59.93</strong></td></tr>
        <tr><td>QHD</td><td><strong>H.264</strong></td><td align="right"><strong>13.53</strong></td><td align="right"><strong>19.1 KiB</strong></td><td align="right"><strong>6.19</strong></td><td align="right"><strong>1.34</strong></td><td align="right"><strong>6.38</strong></td><td align="right"><strong>66.54</strong></td></tr>
        <tr><td>4K</td><td><strong>H.264</strong></td><td align="right"><strong>8.26</strong></td><td align="right"><strong>31.7 KiB</strong></td><td align="right"><strong>13.07</strong></td><td align="right"><strong>1.74</strong></td><td align="right"><strong>32.47</strong></td><td align="right"><strong>315.47</strong></td></tr>
    </tbody>
</table>

</details>

</details>

</details>
