import asyncio
import sys
import tempfile
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = (
    "https://www.ausschreibungen.ls.brandenburg.de/NetServer/"
    "PublicationControllerServlet?function=Detail"
    "&TWOID=54321-Tender-19dd8f5cf0f-592e47d74c8f4cb2&PublicationType=0"
)


async def test():
    downloaded = []

    with tempfile.TemporaryDirectory(prefix="brand-test-") as tmpdir:
        out = Path(tmpdir)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            # Step 1
            print("\n" + "="*60)
            print("STEP 1: Loading detail page ...")
            await page.goto(URL, timeout=40_000)
            await page.wait_for_load_state("networkidle", timeout=15_000)
            print(f"  Title: {await page.title()}")
            print(f"  URL  : {page.url}")

            # Step 2: click Unterlagen link
            print("\n" + "="*60)
            print("STEP 2: Click 'Unterlagen zur Ansicht herunterladen' ...")
            link = page.locator("a:has-text('Unterlagen zur Ansicht herunterladen')")
            cnt = await link.count()
            print(f"  Found {cnt} link(s)")
            if cnt == 0:
                print("  [FAIL] Link missing -- abort.")
                await browser.close()
                return

            print(f"  href: {await link.first.get_attribute('href')}")
            try:
                async with page.expect_download(timeout=12_000) as dl_info:
                    await link.first.click()
                dl = await dl_info.value
                dest = out / dl.suggested_filename
                await dl.save_as(str(dest))
                downloaded.append(str(dest))
                print(f"  [OK] Direct download: {dl.suggested_filename} ({dest.stat().st_size} B)")
            except PWTimeout:
                print("  [INFO] No download triggered -- navigated to next page")
            except Exception as exc:
                print(f"  [WARN] {exc}")

            await page.wait_for_load_state("networkidle", timeout=15_000)
            await page.wait_for_timeout(2_000)
            print(f"  Now at: {page.url}")

            # Step 3: body text
            print("\n" + "="*60)
            print("STEP 3: Relevant body text on documents page ...")
            body = await page.inner_text("body")
            capture = False
            for line in body.splitlines():
                s = line.strip()
                if "Vergabeunterlagen" in s:
                    capture = True
                if capture and s:
                    print(f"  {s}")
                if capture and "Nachrichten" in s:
                    break

            # Step 4: all clickable elements
            print("\n" + "="*60)
            print("STEP 4: All clickable elements on documents page ...")
            clickables = []
            for sel in ["button", "input[type=submit]", "input[type=button]", "a"]:
                for el in await page.query_selector_all(sel):
                    t = (await el.inner_text()).strip()[:70]
                    h = (await el.get_attribute("href") or "")[:120]
                    o = (await el.get_attribute("onclick") or "")[:80]
                    if t or h:
                        clickables.append({"el": el, "text": t, "href": h, "onclick": o})
                        print(f"  [{t or '(empty)'}]  href={h}  onclick={o}")

            # Step 5: click every download-looking element
            print("\n" + "="*60)
            print("STEP 5: Clicking every download-looking element ...")
            kws = ["download", "herunterladen", "zip", "pdf", "unterlag", "datei", "file", "dokument"]
            for item in clickables:
                combined = (item["text"] + item["href"] + item["onclick"]).lower()
                if not any(k in combined for k in kws):
                    continue
                print(f"\n  -> [{item['text']}]  {item['href']}")
                try:
                    async with page.expect_download(timeout=10_000) as dl_info:
                        await item["el"].click(timeout=5_000)
                    dl = await dl_info.value
                    dest = out / dl.suggested_filename
                    await dl.save_as(str(dest))
                    downloaded.append(str(dest))
                    print(f"  [OK] {dl.suggested_filename}  {dest.stat().st_size:,} bytes")
                except PWTimeout:
                    print(f"  [INFO] no download -- now at {page.url}")
                    try:
                        await page.go_back()
                        await page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass
                except Exception as exc:
                    print(f"  [ERROR] {exc}")

            # Step 6: raw HTTP probes
            print("\n" + "="*60)
            print("STEP 6: Direct HTTP probes to servlet download endpoints ...")
            import httpx
            base = "https://www.ausschreibungen.ls.brandenburg.de/NetServer/"
            toid = "54321-NetTender-19df7e1739e-6576a42c974af37e"
            probes = [
                f"{base}TenderingProcedureDetails?function=DownloadDocuments&TenderOID={toid}",
                f"{base}TenderingProcedureDetails?function=GetDocuments&TenderOID={toid}",
                f"{base}DocumentDownloadServlet?TenderOID={toid}&function=DownloadZip",
                f"{base}DocumentDownloadServlet?TenderOID={toid}",
            ]
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for url in probes:
                    try:
                        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                        ct = r.headers.get("content-type", "")
                        cl = r.headers.get("content-length", "?")
                        short = url[len(base):]
                        print(f"  {r.status_code}  {ct[:35]:35}  {cl:>8} bytes  {short}")
                        if r.status_code == 200 and any(k in ct for k in ("zip", "octet", "pdf")):
                            fname = out / f"probe_{probes.index(url)}.bin"
                            fname.write_bytes(r.content)
                            downloaded.append(str(fname))
                            print(f"  [OK] saved {len(r.content):,} bytes as {fname.name}")
                    except Exception as exc:
                        print(f"  [ERROR] {exc}")

            await browser.close()

    print("\n" + "="*60)
    print(f"FINAL: {len(downloaded)} file(s) downloaded")
    for f in downloaded:
        p = Path(f)
        if p.exists():
            print(f"  [OK] {p.name}  {p.stat().st_size:,} bytes")
    if not downloaded:
        print("  [FAIL] Nothing -- portal requires authentication for downloads.")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test())
