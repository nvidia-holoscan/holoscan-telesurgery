# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Delayed depth presents complete pairs without flashing or reusing stale measurements."""

import struct
import zlib
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


def packet(timestamp, value):
    return list(
        struct.pack("!IHHHH", timestamp, 2, 2, 0, 1)
        + zlib.compress(struct.pack("<4f", *([value] * 4)))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["side", "overlay", "depth"])
async def test_delayed_depth_keeps_matching_color_and_expires_without_repainting(mode):
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
                        body='<div id="stage"></div><div id="caption"></div>',
                        content_type="text/html",
                    )

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.evaluate("""async () => {
                const {depthView} = await import('/depth.js');
                const video=document.createElement('canvas'); video.width=video.height=2;
                video.readyState=4;
                let callback;
                video.requestVideoFrameCallback=f=>{callback=f;return 1};
                video.cancelVideoFrameCallback=()=>{callback=undefined};
                window.channel={readyState:'open',send(){}};
                window.view=depthView({createDataChannel:()=>channel},video,
                    document.querySelector('#stage'),document.querySelector('#caption'),
                    {name:'Camera',depth:true,depth_source:'simulated'});
                window.present=(rtp,color)=>{
                    const ctx=video.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,2,2);
                    callback(performance.now(),{rtpTimestamp:rtp,mediaTime:rtp/90000});
                };
                window.receive=data=>channel.onmessage({data:new Uint8Array(data).buffer});
                window.pixels=()=>[...document.querySelectorAll('#stage canvas')].map(c=>
                    [...c.getContext('2d').getImageData(0,0,1,1).data]);
            }""")
            await page.get_by_label("Depth display", exact=True).select_option(mode)
            reading = page.locator(".depth-reading")
            await page.evaluate("data=>receive(data)", packet(10, 0.5))
            await page.evaluate("present(10,'red')")
            await expect(reading).to_contain_text("Simulated depth")
            initial = await page.evaluate("pixels()")
            assert initial[0] == [255, 0, 0, 255]
            assert initial[1][3] > 0

            # SCTP depth can lead the video jitter buffer by several frames.
            # Retaining just three decoded depth frames made pairing fail forever.
            for timestamp in range(20, 26):
                await page.evaluate("data=>receive(data)", packet(timestamp, 0.6))
            await page.evaluate("present(20,'red')")
            await page.wait_for_function("pixels()[1][0] !== " + str(initial[1][0]))
            initial = await page.evaluate("pixels()")

            # New color arrives first. Hold both old images until a matching depth arrives.
            await page.clock.run_for(40)
            await page.evaluate("present(11,'green'); present(12,'blue')")
            assert await page.evaluate("pixels()") == initial
            await expect(reading).to_contain_text("Simulated depth")
            await page.evaluate("data=>receive(data)", packet(11, 0.75))
            await page.wait_for_function("pixels()[0][1] === 128")
            await page.evaluate("data=>receive(data)", packet(12, 1.0))
            await page.wait_for_function("pixels()[0][2] === 255")
            latest = await page.evaluate("pixels()")
            assert latest[1] != initial[1]

            # Late/out-of-order data cannot roll the displayed pair backwards.
            await page.evaluate("data=>receive(data)", packet(10, 0.5))
            await page.clock.run_for(100)
            assert await page.evaluate("pixels()") == latest
            await page.get_by_label("Depth range", exact=True).select_option("5")
            await page.clock.run_for(501)
            await expect(reading).to_contain_text("unavailable")
            assert (await page.evaluate("pixels()"))[1] == [0, 0, 0, 0]
            await expect(page.locator(".depth-color")).to_be_hidden()

            # A fresh pair recovers; switching off must release pending color frames.
            await page.evaluate("present(13,'white')")
            await page.evaluate("data=>receive(data)", packet(13, 0.2))
            await expect(reading).to_contain_text("Simulated depth")
            await page.get_by_label("Depth display", exact=True).select_option("color")
            await expect(page.locator("canvas:not(.depth-color)")).to_be_hidden()
            await page.evaluate("view.stop()")
        finally:
            await browser.close()
