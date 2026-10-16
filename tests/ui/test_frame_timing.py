# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Browser timing correlates one frame and keeps every displayed breakdown additive."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright


@pytest.mark.asyncio
async def test_browser_endpoints_missing_clocks_rounding_and_history():
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(request):
                name = request.request.url.rsplit("/", 1)[-1]
                if name.endswith(".js"):
                    await request.fulfill(path=static / name)
                else:
                    await request.fulfill(
                        body="<html><body></body></html>", content_type="text/html"
                    )

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            result = await page.evaluate("""async () => {
                const {displayedPath,pathReport} = await import('/frame-timing.js');
                const {pathView} = await import('/path-view.js');
                const frame={at_ms:1000,stages:{encode_ms:2.003,send_queue_ms:.007},error_ms:0};
                const metadata={receiveTime:15,processingDuration:.002,
                    expectedDisplayTime:30,presentationTime:31};
                const path=displayedPath(frame,metadata,{offset:990,error:.1});
                const uncertain=displayedPath(frame,metadata,{offset:990,error:2});
                const missing=displayedPath(frame,metadata,{offset:990,error:20});
                const noClock=displayedPath(frame,metadata,null);
                const samples=[path,{...path,stages:{...path.stages,
                    encode_ms:9.999,browser_playout_ms:8.341}}];
                const report=pathReport(samples);
                report.history=[{at:0,p50:10,p95:12,p99:15,p99_9:20},
                    {at:5,p50:11,p95:13,p99:16,p99_9:21}];
                report.history_end=7;
                const root=document.createElement('section');
                root.innerHTML=`<div class="latency-bars"></div><div class="latency-history">
                    <select class="history-range"><option value="60">1 min</option>
                    <option value="300">5 min</option><option value="1800">30 min</option>
                    <option value="3600">1 hr</option></select><svg></svg><p></p></div>
                    <table><tbody></tbody></table>`;
                document.body.append(root);
                pathView(root,report);
                const rows=[...root.querySelectorAll('tr')].map(r=>
                    [...r.querySelectorAll('td')].map(td=>Number(td.textContent)));
                const sums=Array.from({length:4},(_,i)=>
                    rows.slice(0,-1).reduce((s,r)=>s+Math.round(r[i]*100),0));
                const totals=rows.at(-1).map(v=>Math.round(v*100));
                const range=root.querySelector('select'), windows=[];
                for(const value of ['60','300','1800','3600']) {
                    range.value=value;range.dispatchEvent(new Event('change'));
                    windows.push(root.querySelector('svg text:last-child').textContent);
                }
                return {path,uncertain,missing,noClock,sums,totals,windows,
                    bars:root.querySelectorAll('.latency-bar-row').length};
            }""")
            assert result["path"]["stages"]["browser_decode_ms"] == 2
            assert result["path"]["stages"]["browser_playout_ms"] == 18
            assert result["uncertain"]["stages"]["browser_playout_ms"] == 18
            assert result["uncertain"]["error_ms"] == 2
            assert result["missing"]["stages"]["browser_playout_ms"] is None
            assert result["noClock"]["stages"]["browser_playout_ms"] is None
            assert result["sums"] == result["totals"]
            assert result["bars"] == 4 and result["windows"] == ["Now"] * 4
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_summary_cards_and_trends_use_p99_for_patient_browser_and_holoviz():
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(request):
                name = request.request.url.rsplit("/", 1)[-1]
                if name.endswith(".js"):
                    await request.fulfill(path=static / name)
                else:
                    await request.fulfill(body="<div id='output'></div>", content_type="text/html")

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            results = await page.evaluate("""async () => {
                const {latencyReader}=await import('/latency.js');
                const {latencyView}=await import('/metrics.js');
                const sample=value=>({p50:1,p95:2,p99:value,p99_9:value+1,count:100});
                const path={total:sample(99),decode:sample(9)};
                const stats={frames:100,path,steady_metrics:{
                    encode_ms:sample(20),decode_ms:sample(30),
                    pack_ms:sample(21),unpack_ms:sample(31)}};
                const output=document.querySelector('#output'), results=[];
                for(const mode of ['patient','browser','holoviz','raw']) {
                    const camera={id:'room',codec:mode==='raw'?'raw-bgr8':'h264'};
                    const native=['holoviz','raw'].includes(mode);
                    const state={role:mode==='patient'?'patient':'surgeon',
                        cameras:[camera],selected:['room'],
                        session:{status:'approved',cameras:[camera]},video:{room:stats},
                        native_views:native?{room:{status:'running',frames:100,metrics:stats}}:{}};
                    window.fetch=async()=>new Response(JSON.stringify(state));
                    const peers=new Map([['room',{peer:{getStats:async()=>new Map()},
                        timing:{read:()=>path,stop(){}}}]]);
                    const read=latencyReader(peers,'room');
                    const report=await read(new AbortController().signal);
                    latencyView('room')(output,report);
                    const card=key=>({
                        label:output.querySelector(`[data-card="${key}"] h3`).textContent,
                        value:output.querySelector(`[data-card="${key}"] strong`).textContent});
                    results.push({mode,total:card('delivery'),encode:card('encode'),
                        decode:card('decode'),trend:report.streams[0].history[0]});
                    read.close();
                }
                return results;
            }""")
            for result in results:
                raw = result["mode"] == "raw"
                assert result["total"]["value"] == "99.00"
                assert result["total"]["label"] == (
                    "Source latency · P99" if result["mode"] == "patient" else "Total latency · P99"
                )
                assert result["encode"]["value"] == ("21.00" if raw else "20.00")
                assert "P99" in result["encode"]["label"]
                assert result["trend"]["delivery"] == 99
                assert result["trend"]["encode"] == (21 if raw else 20)
                if result["mode"] != "patient":
                    expected = 31 if raw else 30 if result["mode"] == "holoviz" else 9
                    assert result["decode"]["value"] == f"{expected:.2f}"
                    assert result["trend"]["decode"] == expected
                    assert "P99" in result["decode"]["label"]
        finally:
            await browser.close()
