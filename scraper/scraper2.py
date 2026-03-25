#!/usr/bin/env python3
# quick scraper for the hackathon - grabs tender data from german procurement sites
# run:  python3 scraper.py -i publications_b.csv -n 50
# need playwright installed:  pip install playwright && playwright install chromium

import asyncio, csv, json, logging, time, argparse, os
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler()])
log = logging.getLogger("s")


# try a list of xpaths, return first match
async def grab(page, xps):
    for xp in xps:
        try:
            els = await page.locator(f"xpath={xp}").all()
            if els:
                t = (await els[0].inner_text()).strip()
                if t and len(t) < 2000: return t
        except: pass
    return None


# --- xpaths for each field ---
# every portal uses different html so we just try a bunch and hope one works
# the dt/dd ones are for definition lists, th/td for tables, the generic ones
# just look for text containing the german keyword

xp_title = ["//h1", "//*[contains(@class,'title') and (self::h1 or self::h2)]", "//title"]

xp_auth = [
    "//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]",
    "//th[contains(.,'Auftraggeber')]/following-sibling::td[1]",
    "//td[contains(.,'Auftraggeber')]/following-sibling::td[1]",
    "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
    "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
]

xp_deadline = [
    "//dt[contains(.,'Angebotsfrist') or contains(.,'Frist')]/following-sibling::dd[1]",
    "//th[contains(.,'Frist')]/following-sibling::td[1]",
    "//td[contains(.,'Frist')]/following-sibling::td[1]",
    "//*[contains(text(),'Angebotsfrist') or contains(text(),'Teilnahmefrist')]/following-sibling::*[1]",
    "//*[contains(text(),'Frist')]/following-sibling::*[1]",
]

xp_pubdate = [
    "//dt[contains(.,'Veröffentlich')]/following-sibling::dd[1]",
    "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
    "//*[contains(text(),'Bekanntmachung')]/following-sibling::*[1]",
]

xp_type = [
    "//dt[contains(.,'Verfahrensart') or contains(.,'Vergabeart')]/following-sibling::dd[1]",
    "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
]

xp_cpv = ["//*[contains(text(),'CPV')]/following-sibling::*[1]",
           "//dt[contains(.,'CPV')]/following-sibling::dd[1]"]

xp_loc = ["//*[contains(text(),'Erfüllungsort') or contains(text(),'Ort der Leistung')]/following-sibling::*[1]"]

xp_ref = [
    "//dt[contains(.,'Vergabenummer') or contains(.,'Aktenzeichen')]/following-sibling::dd[1]",
    "//*[contains(text(),'Vergabenummer') or contains(text(),'Aktenzeichen')]/following-sibling::*[1]",
]

xp_desc = ["//*[contains(text(),'Beschreibung') or contains(text(),'Leistung')]/following-sibling::*[1]",
            "//*[contains(@class,'description')]"]

xp_contact = ["//*[contains(text(),'Kontakt')]/following-sibling::*[1]", "//*[contains(@class,'contact')]"]


def _sel(t=None, a=None, d=None):
    """merge site-specific xpaths with the defaults"""
    return {
        "title": (t or []) + xp_title,
        "contracting_authority": (a or []) + xp_auth,
        "description": xp_desc,
        "deadline": (d or []) + xp_deadline,
        "publication_date": xp_pubdate,
        "tender_type": xp_type,
        "cpv_codes": xp_cpv,
        "location": xp_loc,
        "reference_number": xp_ref,
        "contact_info": xp_contact,
    }


# ---- site configs ----
# added these as i found them in the dataset, some might be wrong
# TODO: test vergabe.bayern more, was getting wierd results earlier

SITES = {
    "www.evergabe.de": {
        "wait": "//h1 | //div[contains(@class,'content')]",
        "sel": _sel(a=["//*[contains(@class,'vergabestelle')]"]),
    },
    "www.subreport.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel": _sel(
            t=["//div[contains(@class,'bekanntmachungstitel')]"],
            a=["//span[contains(@id,'lblVergabestelle') or contains(@id,'lblAuftraggeber')]"],
            d=["//span[contains(@id,'lblAngebotsfrist')]"]),
    },
    "vergabemarktplatz.brandenburg.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel": _sel(a=["//*[contains(@class,'organisation-name')]"]),
    },
    "vergabe.niedersachsen.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "bieterzugang.deutsche-evergabe.de": {"wait": "//div | //h1", "sel": _sel()},
    "www.evergabe.nrw.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "www.vergabe-westfalen.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "www.deutsches-ausschreibungsblatt.de": {
        "wait": "//div[contains(@class,'content')]",
        "sel": _sel(a=["//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]"]),
    },
    "www.had.de": {
        "wait": "//div[contains(@class,'content')]",
        "sel": _sel(
            a=["//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]"],
            d=["//td[contains(text(),'Frist') or contains(text(),'Abgabetermin')]/following-sibling::td[1]"]),
    },
    "www.vergabe.metropoleruhr.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "fbhh-evergabe.web.hamburg.de": {"wait": "//div | //h1", "sel": _sel()},
    "bi-medien.de": {
        "wait": "//div[contains(@class,'content')]",
        "sel": _sel(a=["//span[contains(@class,'auftraggeber')]"]),
    },
    "www.tender24.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel": _sel(a=["//span[@id='lblVergabestelle']"], d=["//span[@id='lblAngebotsfrist']"]),
    },
    "vergabe.landbw.de": {"wait": "//div[contains(@class,'detail')]", "sel": _sel()},
    "www.vergabe24.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel": _sel(a=["//span[@id='lblVergabestelle']"]),
    },
    "vergabekooperation.berlin": {"wait": "//div[contains(@class,'detail')]", "sel": _sel()},
    "www.evergabe.bayern.de": {"wait": "//div | //h1", "sel": _sel()},  # this one is flaky
    "vergabeportal-bw.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "vergabe.fraunhofer.de": {"wait": "//div[contains(@class,'detail')]", "sel": _sel()},
    "www.ausschreibungen.ls.brandenburg.de": {"wait": "//div[contains(@class,'detail')]", "sel": _sel()},
    "landesverwaltung.vergabe.rlp.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "lbb.vergabe.rlp.de": {"wait": "//div[contains(@class,'notice')]", "sel": _sel()},
    "vergabe.deges.de": {"wait": "//div[contains(@class,'detail')]", "sel": _sel()},
    "www.evergabe.sachsen.de": {"wait": "//div[contains(@class,'detail')]", "sel": _sel()},
    "vergabe.muenchen.de": {"wait": "//div | //h1", "sel": _sel()},
    "vergabe.bremen.de": {"wait": "//div | //h1", "sel": _sel()},
}

FALLBACK = {"wait": "//body", "sel": _sel()}

def get_cfg(url):
    d = urlparse(url).netloc.lower()
    if d in SITES: return d, SITES[d]
    for k in SITES:
        if k in d or d in k: return d, SITES[k]
    return d, FALLBACK


# cookie banners.. every single site has one smh
async def kill_cookies(page):
    for sel in [
        "xpath=//button[contains(text(),'Akzeptieren')]",
        "xpath=//button[contains(text(),'Alle akzeptieren')]",
        "xpath=//button[contains(text(),'Accept')]",
        "xpath=//button[contains(text(),'Zustimmen')]",
        "xpath=//button[contains(text(),'Nur notwendige')]",
        "xpath=//button[contains(@class,'accept') or contains(@class,'consent')]",
        "xpath=//button[@id='accept' or @id='acceptCookies']",
    ]:
        try:
            b = page.locator(sel).first
            if await b.is_visible(timeout=800):
                await b.click()
                await page.wait_for_timeout(400)
                return
        except: pass


# fallback - just grab every label/value pair on the page
# if our xpaths miss we atleast get something
async def sweep(page):
    out = {}
    try:
        # <dt>/<dd> pairs
        for dt in await page.locator("xpath=//dt").all():
            try:
                k = (await dt.inner_text()).strip()
                v = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if k and v and len(k) < 150: out[k] = v
            except: pass

        # table rows
        for row in await page.locator("xpath=//tr").all():
            try:
                cells = await row.locator("td, th").all()
                if len(cells) >= 2:
                    k = (await cells[0].inner_text()).strip()
                    v = (await cells[1].inner_text()).strip()
                    if k and v and len(k) < 150: out[k] = v
            except: pass
    except: pass
    return out


# phrases that mean the tender page is dead
GONE = ["nicht mehr verfügbar", "nicht gefunden", "abgelaufen",
        "Seite existiert nicht", "Page not found",
        "Vergabe wurde aufgehoben", "Bekanntmachung wurde gelöscht",
        "kein Ergebnis", "Kein Treffer"]


async def scrape(page, row):
    url = row["url"]
    dom, cfg = get_cfg(url)

    r = {"id": row.get("id",""), "url": url, "domain": dom,
         "status": "pending", "title": None, "authority": None,
         "desc": None, "deadline": None, "pub_date": None,
         "type": None, "cpv": None, "location": None,
         "ref_num": None, "contact": None, "extra": {},
         "err": None, "ms": 0, "ts": ""}

    t0 = time.time()
    try:
        # skip urls that are obviously not tender pages
        if "login" in url or "register" in url:
            r["status"] = "invalid"; r["err"] = "login/register page"
            return r

        resp = await page.goto(url, wait_until="domcontentloaded", timeout=8000)

        if resp and resp.status >= 400:
            r["status"] = "invalid"; r["err"] = f"HTTP {resp.status}"
            return r

        await page.wait_for_timeout(500)
        await kill_cookies(page)

        # wait for page content, dont crash if it timesout
        try: await page.wait_for_selector(f"xpath={cfg['wait']}", timeout=3000)
        except PlaywrightTimeout: pass

        # check if page is dead
        try:
            body = await page.inner_text("body")
            for g in GONE:
                if g.lower() in body.lower()[:5000]:
                    r["status"] = "invalid"; r["err"] = f"gone: {g}"
                    return r
        except: pass

        # pull out each field
        sel = cfg["sel"]
        r["title"]     = await grab(page, sel["title"])
        r["authority"] = await grab(page, sel["contracting_authority"])
        r["desc"]      = await grab(page, sel["description"])
        r["deadline"]  = await grab(page, sel["deadline"])
        r["pub_date"]  = await grab(page, sel["publication_date"])
        r["type"]      = await grab(page, sel["tender_type"])
        r["cpv"]       = await grab(page, sel["cpv_codes"])
        r["location"]  = await grab(page, sel["location"])
        r["ref_num"]   = await grab(page, sel["reference_number"])
        r["contact"]   = await grab(page, sel["contact_info"])

        # only sweep if xpaths didnt find the main stuff
        if not r["title"] and not r["authority"]:
            r["extra"] = await sweep(page)

        if r["title"] or r["authority"] or r["extra"]:
            r["status"] = "success"
        else:
            r["status"] = "error"; r["err"] = "nothing found"

    except PlaywrightTimeout:
        r["status"] = "timeout"; r["err"] = "page took too long (8s)"
    except Exception as e:
        r["status"] = "error"; r["err"] = str(e)[:300]

    r["ms"] = int((time.time() - t0) * 1000)
    r["ts"] = datetime.now().isoformat()
    return r


# process one domains urls on a single tab
async def do_batch(dom, rows, cfg, results, sem, ctx, prog, total):
    log.info(f"  {dom} - {len(rows)} urls")
    tab = await ctx.new_page()
    for row in rows:
        async with sem:
            rec = await scrape(tab, row)
            results.append(rec)
            prog["n"] += 1
            p = prog["n"]
            ico = "✓" if rec["status"]=="success" else ("⏱" if rec["status"]=="timeout" else "✗")
            log.info(f"  {ico} [{p}/{total} {100*p/total:.1f}%] {dom} {rec['status']} {rec['ms']}ms")
    await tab.close()


async def main(args):
    rows = []
    with open(args.input, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            u = row.get("url","").strip()
            if u: rows.append(row)
    log.info(f"{len(rows)} urls loaded")

    if args.skip_done:
        b = len(rows)
        rows = [r for r in rows if r.get("state","") != "COMPLETED"]
        log.info(f"skipped {b-len(rows)} done, {len(rows)} left")

    if args.limit > 0:
        rows = rows[:args.limit]
        log.info(f"limiting to {args.limit}")

    if not rows:
        print("nothing to scrape"); return

    # group by domain
    groups = {}
    for r in rows:
        d = urlparse(r["url"]).netloc.lower()
        groups.setdefault(d, []).append(r)

    for d, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        log.info(f"    {d}: {len(g)}")

    results = []
    sem = asyncio.Semaphore(args.workers)
    prog = {"n": 0}
    tot = len(rows)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--disable-extensions", "--blink-settings=imagesEnabled=false",
        ])
        ctx = await browser.new_context(
            locale="de-DE", timezone_id="Europe/Berlin",
            user_agent="Mozilla/5.0 (Macintosh; Apple M4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )

        tasks = [do_batch(d, g, SITES.get(d, FALLBACK), results, sem, ctx, prog, tot)
                 for d, g in groups.items()]
        await asyncio.gather(*tasks)
        await browser.close()

    # save json
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # save csv too for quick look
    csvf = args.output.replace(".json",".csv")
    cols = ["id","url","domain","status","title","authority","deadline",
            "pub_date","type","ref_num","ms","err"]
    with open(csvf, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(results)

    # stats
    t = len(results)
    ok  = sum(1 for x in results if x["status"]=="success")
    err = sum(1 for x in results if x["status"]=="error")
    to  = sum(1 for x in results if x["status"]=="timeout")
    inv = sum(1 for x in results if x["status"]=="invalid")
    avg = sum(x["ms"] for x in results) / t if t else 0

    print(f"\n{'='*50}")
    print(f"  total:    {t}")
    print(f"  success:  {ok} ({100*ok/t:.1f}%)")
    print(f"  errors:   {err} ({100*err/t:.1f}%)")
    print(f"  timeouts: {to} ({100*to/t:.1f}%)")
    print(f"  invalid:  {inv} ({100*inv/t:.1f}%)")
    print(f"  avg:      {avg:.0f}ms/url")
    print(f"{'='*50}")

    # per domain
    ds = {}
    for x in results:
        d = x["domain"]
        if d not in ds: ds[d] = [0,0]
        ds[d][1] += 1
        if x["status"]=="success": ds[d][0] += 1

    print("\n  domains:")
    for d, (ok,tot) in sorted(ds.items(), key=lambda x:-x[1][1]):
        print(f"    {d:40s} {ok:>4}/{tot:<4} ({100*ok/tot:.0f}%)" if tot else "")
    print()

    log.info(f"done - {args.output} + {csvf}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="publications_b.csv")
    p.add_argument("-o", "--output", default="results.json")
    p.add_argument("-w", "--workers", type=int, default=16, help="parallel tabs (m4 can handle more)")
    p.add_argument("-n", "--limit", type=int, default=0)
    p.add_argument("--skip-done", action="store_true")
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"file not found: {args.input}"); exit(1)

    asyncio.run(main(args))