import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        url = "https://www.ausschreibungen.ls.brandenburg.de/NetServer/PublicationControllerServlet?function=Detail&TWOID=54321-Tender-19dd8f5cf0f-592e47d74c8f4cb2&PublicationType=0"
        await page.goto(url, timeout=40000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        link = page.locator("a:has-text('Unterlagen zur Ansicht herunterladen')")
        print("Found Unterlagen link:", await link.count())
        href = await link.get_attribute("href")
        print("href:", href)

        await link.click()
        await page.wait_for_load_state("networkidle", timeout=20000)
        await page.wait_for_timeout(2000)
        print("Now on:", page.url)
        print()

        print("=== BUTTONS on documents page ===")
        for el in await page.query_selector_all("button, input[type=button], input[type=submit]"):
            t = (await el.inner_text()).strip()
            v = await el.get_attribute("value") or ""
            if t or v:
                print(f"  BUTTON [{t or v}]")

        print()
        print("=== ALL LINKS on documents page ===")
        for el in await page.query_selector_all("a"):
            t = (await el.inner_text()).strip()[:80]
            h = (await el.get_attribute("href") or "")[:150]
            if t:
                print(f"  [{t}]  ->  {h}")

        print()
        print("=== FORMS on documents page ===")
        for f in await page.query_selector_all("form"):
            action = await f.get_attribute("action") or ""
            method = await f.get_attribute("method") or "get"
            print(f"  FORM action={action} method={method}")
            for inp in await f.query_selector_all("input,button,select"):
                nm  = await inp.get_attribute("name") or ""
                tp  = await inp.get_attribute("type") or ""
                vl  = (await inp.get_attribute("value") or "")[:50]
                tx  = (await inp.inner_text()).strip()[:50]
                print(f"    {tp:10} name={nm:25} value={vl:50} text={tx}")

        await browser.close()

asyncio.run(inspect())
