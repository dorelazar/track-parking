import asyncio, json, os
from playwright.async_api import async_playwright
OUT = "out"; os.makedirs(OUT, exist_ok=True)
CASES = [("demo-light", "?demo", "light", 390), ("demo-dark", "?demo", "dark", 390),
         ("live-light", "", "light", 390), ("live-wide", "", "light", 1100)]
async def main():
    log = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        for name, q, scheme, w in CASES:
            ctx = await b.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme, timezone_id="Asia/Jerusalem", device_scale_factor=2 if w < 500 else 1)
            pg = await ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
            pg.on("console", lambda m: m.type in ("error", "warning") and errs.append(m.type + ": " + m.text))
            pg.on("requestfailed", lambda r: errs.append("failed: " + r.url[:120]))
            await pg.goto("https://dorelazar.github.io/track-parking/" + q, wait_until="networkidle")
            await pg.wait_for_timeout(3500)
            info = await pg.evaluate("""() => ({
              scrollW: document.documentElement.scrollWidth, innerW: innerWidth,
              verdict: document.getElementById('verdict').innerText, why: document.getElementById('why').innerText,
              timing: document.getElementById('timing').innerText, lots: document.getElementById('lots').innerText,
              curbs: document.getElementById('curb-list').innerText, planb: document.getElementById('planb').innerText,
              rent: document.getElementById('rent').innerText, tonight: document.getElementById('tonight-body').innerText,
              health: document.getElementById('health').innerText, steps: document.getElementById('steps').innerText,
              route: document.getElementById('drive-route').href, lap: document.getElementById('drive-lap').href,
              tiles: document.querySelectorAll('.leaflet-tile-loaded').length })""")
            info["errors"] = errs
            log[name] = info
            await pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
            if name == "demo-light":
                # exercise "add a spot"
                await pg.click("#spot-add"); await pg.wait_for_timeout(600)
                box = await pg.locator("#map").bounding_box()
                await pg.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.55)
                await pg.fill("#spot-name", "Test spot"); await pg.click("#spot-save"); await pg.wait_for_timeout(500)
                log["add-spot"] = await pg.evaluate("document.getElementById('my-list').innerText + ' | stored=' + localStorage.getItem('track-parking-spots')")
                await pg.locator("#route").screenshot(path=f"{OUT}/map-with-spot.png")
            await ctx.close()
        await b.close()
    json.dump(log, open(f"{OUT}/log.json", "w"), ensure_ascii=False, indent=1)
asyncio.run(main())
