# Vergabepilot.AI — Phase 1: Manual Web Scraping

> **Hackathon Phase 1** — Manual scraping of German public procurement portals using Playwright + XPath. **No LLMs used during scraping.** Goal: maximize scraped websites from `publications_b.csv` (~7,500 URLs).

---

## 📁 Project Files

| File | What it does |
|------|-------------|
| `publications_b.csv` | **Input** — 7,500 URLs to German procurement portals |
| `scraper_b.py` | **Main scraper** — Playwright + XPath, handles 25+ domains |
| `scraper.py` | Original prototype scraper (reference only) |
| `results_b.json` | **Output** — Full scraped data (JSON, one record per URL) |
| `results_b.csv` | **Output** — Quick-review summary spreadsheet |
| `scraper_b.log` | Live log of every URL scraped |
| `requirements.txt` | Python dependencies |
| `inspect_page.py` | Helper to manually inspect a single page's structure |

---

## ⚡ Quick Start

```bash
# Install dependencies
pip3 install playwright
python3 -m playwright install chromium

# Scrape first 100 URLs (fast test)
python3 scraper_b.py --limit 100

# Scrape only FAILED rows (skip already-completed ones)
python3 scraper_b.py --skip-completed --workers 8

# Full run — all 7,500 URLs
python3 scraper_b.py --workers 8

# Watch live progress
tail -f scraper_b.log
```

### All CLI Options

```
--input    -i   Input CSV file          (default: publications_b.csv)
--output   -o   Output JSON file        (default: results_b.json)
--workers  -w   Parallel browser tabs   (default: 8)
--limit    -n   Only scrape first N URLs (0 = all)
--skip-completed  Skip rows where state=COMPLETED in CSV
```

---

## 🏗️ How the Scraper Works — Step by Step

```
publications_b.csv
       │
       ▼
① load_urls()           — reads CSV, extracts all rows with a URL
       │
       ▼
② group_urls_by_domain() — groups e.g. all 1,351 evergabe.de URLs together
       │
       ▼
③ For each domain group → scrape_domain_batch()
   (one persistent Playwright browser tab per domain = efficient)
       │
       ▼
④ scrape_single_url()    — the core function per URL:
   a. page.goto(url)          → navigate
   b. handle_cookie_consent() → dismiss GDPR banner if present
   c. wait_for_selector()     → wait for key content to load
   d. check expired_indicators → mark as "invalid" if page deleted
   e. extract_field()         → run XPath selectors for each field
   f. extract_all_key_value_pairs() → fallback: grab ALL label/value pairs
       │
       ▼
⑤ save_results()         — writes results_b.json + results_b.csv
⑥ print_summary()        — shows success rate per domain
```

---

## 🔑 Two Core Technologies

### Playwright — Browser Automation

Playwright drives a real Chromium browser in the background (invisible/headless). This is necessary because German procurement sites use **JavaScript** to render content — a plain `requests.get()` would return empty HTML.

```python
# Launch invisible Chrome
browser = await p.chromium.launch(headless=True)

# Open a URL like a real user would
response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)

# Dismiss cookie popup
await page.locator("xpath=//button[contains(text(),'Akzeptieren')]").click()
```

### XPath — GPS for Web Pages

XPath is a standard query language (W3C spec) for finding elements in HTML. Think of it as a precise address inside a web page.

```
//h1
    → Any <h1> tag anywhere on the page

//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]
    → The <dd> immediately after a <dt> that contains "Auftraggeber"
    → Example result: "Stadt München"

//*[contains(text(),'Frist')]/following-sibling::*[1]
    → Any element containing "Frist", then its next sibling element
    → Catches deadline dates
```

**Real-world example from a tender page:**
```html
<dt>Auftraggeber</dt>        ← XPath finds this label
<dd>Landratsamt Bautzen</dd> ← returns THIS value ✓
<dt>Angebotsfrist</dt>
<dd>15.04.2026 12:00 Uhr</dd>
```

---

## 📊 Input CSV Columns (`publications_b.csv`)

| Column | Meaning |
|--------|---------|
| `id` | Unique ID for this procurement record |
| `url` | **The URL we scrape** |
| `domain` | Domain extracted from URL (e.g. `vergabe.niedersachsen.de`) |
| `state` | Previous system result: `COMPLETED` / `FAILED` / `UNSUPPORTED` |
| `error` | Error message from the previous system (if FAILED) |

---

## 📤 Output Fields (per scraped URL)

| Field | What it captures |
|-------|-----------------|
| `status` | `success` / `error` / `timeout` / `invalid` |
| `title` | Tender name (from `<h1>`) |
| `contracting_authority` | Who is purchasing (Auftraggeber / Vergabestelle) |
| `deadline` | Submission deadline (Angebotsfrist) |
| `publication_date` | When the notice was published |
| `tender_type` | Procedure type (Verfahrensart) |
| `reference_number` | Internal tender reference (Vergabenummer) |
| `cpv_codes` | EU procurement category codes |
| `location` | Place of performance (Erfüllungsort) |
| `extra_fields` | All other label/value pairs found on the page |
| `scrape_time_ms` | How long this URL took (milliseconds) |
| `row_state` | Original `state` from input CSV |

---

## 🌐 Supported Domains (25+)

| Domain | Portal Name | URLs in CSV |
|--------|-------------|-------------|
| `www.evergabe.de` | eVergabe.de | 1,351 |
| `www.subreport.de` | Subreport | 1,333 |
| `vergabemarktplatz.brandenburg.de` | Vergabemarktplatz Brandenburg | 695 |
| `vergabe.niedersachsen.de` | Vergabe Niedersachsen | 599 |
| `bieterzugang.deutsche-evergabe.de` | Deutsche eVergabe | 416 |
| `www.evergabe.nrw.de` | eVergabe NRW | 383 |
| `www.vergabe-westfalen.de` | Vergabe Westfalen | 322 |
| `www.deutsches-ausschreibungsblatt.de` | Deutsches Ausschreibungsblatt | 305 |
| `www.had.de` | HAD | 283 |
| `www.vergabe.metropoleruhr.de` | Vergabe Metropole Ruhr | 276 |
| `fbhh-evergabe.web.hamburg.de` | eVergabe Hamburg | 156 |
| `bi-medien.de` | BI Medien | 154 |
| `www.tender24.de` | Tender24 | 131 |
| `vergabe.landbw.de` | Vergabe LandBW | 129 |
| `www.vergabe24.de` | Vergabe24 | 107 |
| `vergabekooperation.berlin` | Vergabekooperation Berlin | 100 |
| `www.evergabe.bayern.de` | eVergabe Bayern | 92 |
| `vergabeportal-bw.de` | Vergabeportal BW | 75 |
| `vergabe.fraunhofer.de` | Vergabe Fraunhofer | 72 |
| + 6 more smaller domains | — | ~300 |

All other domains fall back to the **Generic config** which still extracts `<h1>`, definition lists, and table data.

---

## ⚙️ Key Design Decisions

### Why group by domain first?
Creating a browser tab has overhead. Reusing **one tab per domain** means we navigate within the same context → faster, fewer resources, and cookies/sessions are preserved across URLs on the same site.

### Why multiple XPath fallbacks?
Every portal has different HTML structure. We try specific selectors first, then fall back to generic German-language patterns:
```python
# Tries these in order — first non-empty result wins
"//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]",
"//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]",
"//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
```

### Why `asyncio`?
Scraping 7,500 pages one-by-one ≈ 17 hours. With 8 parallel workers via `asyncio`, it finishes in ~2 hours. The `semaphore` ensures we never exceed 8 simultaneous open browser tabs.

### The `extra_fields` fallback
If none of the custom XPaths find a field, the code dumps **all** `<dt>/<dd>` and `<table>` label-value pairs into `extra_fields`. This is a safety net — even unknown page layouts still yield some data.

### `invalid` status (0ms)
Some evergabe.de URLs instantly return `invalid` with `0ms` — these were pre-filtered based on known error patterns detected from the CSV's `error` column (e.g., `IllegalStateException: Could not extract tender ID`). No HTTP request is made for those.

---

## 🚫 Compliance with "No LLMs" Rule

This scraper uses **zero AI inference**:
- **Playwright** — open-source browser automation library
- **XPath** — W3C standard query language (1999)
- **asyncio** — Python standard library concurrency
- Domain configs — hand-written by inspecting real HTML pages

No API calls to any AI service are made during scraping. ✅

---

## 📈 Performance Observed

From a test run (interrupted at ~2,500 URLs):
- ~250 URLs/minute with 8 workers
- ~3s per `evergabe.de` URL (fast)
- ~7s per `vergabemarktplatz.brandenburg.de` URL (heavier JS)
- Estimated full run: **~30 minutes** for 7,500 URLs

---

## 🐛 Common Errors & What They Mean

| Status | Cause |
|--------|-------|
| `success` | Data extracted (title and/or authority and/or extra fields found) |
| `invalid` | Page returned 404, or tender was deleted/expired |
| `timeout` | Page took >20s to load |
| `error` | Page loaded but no data could be extracted |
