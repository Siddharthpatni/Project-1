"""
llm_codegen.py — Generate document-scraper functions via OpenRouter.

For platforms not in the registry, this module:
  1. Fetches the page HTML (urllib first, Playwright fallback for JS-heavy sites)
  2. Sends URL + truncated HTML to the LLM with a structured prompt
  3. Extracts the generated Python function
  4. Caches it per domain in llm_cache/<domain>.py
  5. Executes it and returns discovered document URLs

Security note: executes LLM-generated Python in the local process.
Only use in controlled test environments.

Usage:
    from llm_codegen import generate_and_run

    result = generate_and_run(
        url="https://some-procurement-site.com/tender/123/documents",
        api_key="sk-or-...",
        model="google/gemini-2.5-flash",
    )
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent.resolve()
CACHE_DIR = ROOT / "llm_cache"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Max HTML characters sent to LLM — enough to see structure, cheap on tokens
HTML_SNIPPET_CHARS = 24_000

_SYSTEM_PROMPT = """\
You are an expert web scraping engineer specializing in German public procurement portals.
Your task: write a Python function that discovers and returns document download URLs from a tender/procurement page.
The function MUST actively navigate the site — fetch sub-pages, follow links, click through to document sections.
Do NOT just parse the initial HTML looking for file links. You must understand the platform and find where documents actually live.

## PRIORITY RULE — critical
Always prefer a single "download all" or ZIP URL over individual file URLs.
Reason: a ZIP contains all files; downloading it once is better than many individual requests.

Search for "download all" / ZIP in this order:
1. An <a> whose href ends with .zip or contains words like: downloadall, alleherunterladen, alle-dokumente, archive
2. An <a> or <button> whose visible text (case-insensitive) contains any of:
   "alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen",
   "download all", "download zip", "zip herunterladen", "unterlagen herunterladen",
   "alle unterlagen", "gesamtpaket"
3. An <a> with an onclick= that constructs a ZIP download URL
If any of the above is found → return ONLY that single URL in the list (do not also add individual files).

If NO "download all" option exists → return individual file URLs:
- <a href> that ends with: .pdf .doc .docx .xls .xlsx .ppt .pptx .zip .rar .7z .txt .odt .ods
- Ignore <a> tags that are navigation, login, or external links

## PLATFORM-SPECIFIC NAVIGATION KNOWLEDGE
Use these hints to understand how each platform works. Adapt based on what you see in the HTML.

### NetServer family (vergabe.autobahn.de, tender24.de, sachsen-vergabe.de, vergabe.vmstart.de, vergabe.landbw.de, ausschreibungen.ls.brandenburg.de, and similar sites using "NetServer" in their URL path)
- These sites use query parameter `function=` to switch views.
- The tender page URL typically has `function=_Details` or `function=Detail`.
- **Navigation flow**: On the details page, look for a section called "Unterlagen zur Ansicht herunterladen" (download documents for viewing). Click/follow that link — it leads to a page with a download button.
- **To get the ZIP download**, construct a URL with `function=_DownloadTenderDocuments` keeping the same `TenderOID` parameter.
  Pattern: `{base}/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={same_oid}`
  Sometimes additional params are needed: `documentOID`, `TenderAuthority`, `TenderDate` — look for these in hidden form fields or links on the page.
- **Do NOT validate the ZIP URL** with a HEAD request or Content-Type check — just return the constructed URL. Some servers don't respond correctly to HEAD requests.
- If no direct ZIP is available, the documents are listed further down on the _Details page — parse the FULL page content, not just the top. You may need to scroll down to find the "Vergabeunterlagen" section with download buttons.
- Look for links with `function=_DownloadDocument` for individual file downloads.
- The page may also have a link to `function=_Documents` which lists all documents.
- **Important**: Some NetServer sites use `PublicationControllerServlet?function=Detail&TWOID=...` — these are publication overview pages. Look for links to `TenderingProcedureDetails` on the page and follow them to reach the actual tender with documents.

### evergabe.de
- **Use `BrowserSession`** — the site requires JS rendering.
- **Navigation flow** — do NOT click through multi-step pages (they redirect-loop). Instead, go directly to the documents page:
  1. Extract the tender/procedure ID from the URL. The ID is the last numeric segment in the path (e.g., `3378700` from `.../3378700`).
  2. Navigate directly to `https://www.evergabe.de/unterlagen/{id}` — this is the documents download page.
  3. On the documents page, find all `<a>` tags with text "Datei herunterladen" — each one is a file download link. The href pattern is `/unterlagen/.../download/...?award_procedure_id=...`.
  4. Return all these download URLs.
- **Important**: Do NOT try the multi-step flow (clicking "Weiter zu den Vergabeunterlagen" → "Vergabeunterlagen ansehen") — it gets stuck in a redirect loop due to a delivery method selection page.

### eVergabe 4.9 / Cosinex family (used by: kfw.vergabe.nrw.de, vergabe.autobahn.de (non-NetServer), vergabemarktplatz.brandenburg.de, vergabe.muenchen.de, ehealth-evergabe.de, vergabeplattform.hamburg.de, healyhudson.biz, bieterportal.noncd.db.de, www.evergabe.bayern.de, ausschreibungen.kfw.de, and other sites with "eVergabe" branding or Angular-rendered tender pages or URLs containing "evergabe.bieter/api/supplier/external/deeplink")
- **These sites are NOT login-gated.** Documents are publicly accessible.
- **Navigation flow** (use `BrowserSession`, these are Angular apps):
  1. Load the page and wait for JS to render (wait 5-8 seconds).
  2. **Scroll down the page** — the **"Alle herunterladen"** (download all) button is visible on the page itself, you just need to scroll to it. It is NOT hidden behind a tab click.
  3. Find and click the **"Alle herunterladen"** button. This downloads a ZIP of all documents.
  4. These are `<button>` elements, NOT `<a>` links — standard link scraping will NOT find them.
- **To capture the download URL**: Use `session.page.expect_download()` context manager when clicking the download button:
  ```python
  with session.page.expect_download() as download_info:
      button = session.page.locator('button:has-text("Alle herunterladen")')
      button.scroll_into_view_if_needed()
      button.click()
  download = download_info.value
  download_url = download.url
  ```
- **Fallback**: If "Alle herunterladen" is not found after scrolling, try clicking a **"Teilnehmen"** or **"Vergabeunterlagen"** tab, then look for the button again.
- Do NOT rely on tab navigation as the primary approach — scroll first, tab-click only as fallback.

### evergabe-online.de (e-Vergabe) — Wicket-based framework
- Uses Apache Wicket with component-path URLs. Do NOT filter out download links just because they look unusual.
- **Navigation flow**: The tender page has a "Vergabeunterlagen" (tender documents) section.
- **ZIP download**: Search all `<a>` tags for one whose `href` contains the string `zipDownloadButton`. This is the ZIP download link.
  Example href: `./tenderdocuments.html?0--documentsTableContainer-zipDownloadButton&id=858550&cookieCheck`
  Do NOT search by link text — the text may be nested in child elements and won't match `string=` in BeautifulSoup. Search by **href content** only.
- **IMPORTANT**: When extracting href values from HTML, the `&` characters will be encoded as `&amp;`. You MUST decode HTML entities before returning the URL. Use `html.unescape()` on extracted URLs:
  ```python
  import html
  for a_tag in soup.find_all('a', href=True):
      if 'zipDownloadButton' in a_tag['href']:
          return [urljoin(base_url, html.unescape(a_tag['href']))]
  ```
- Also check for individual file download links in the documents table.
- WARNING: Links to `archivedProcedures.html` or `login.html` are NOT document downloads — ignore those.
- Do NOT assume documents require login. Check for the ZIP download link first.

### subreport.de and subreport-elvis.de (ELViS platform)
- Documents are publicly accessible — do NOT assume login is required.
- **MUST use `BrowserSession`** (not raw `sync_playwright`). BrowserSession sets locale to de-DE and German Accept-Language headers, which is REQUIRED — the site must render in German for the navigation buttons to appear.
- **Navigation flow**:
  1. On the tender page, wait for page to load (sleep 5 seconds for JS rendering).
  2. Find and click the **"anzeigen"** button to reveal the document list. Wait 5 seconds after clicking.
  3. After clicking, a "Liste der Dokumente" section appears with rows for each file.
- **Page structure after clicking "anzeigen"**: The documents are listed as rows in a table. Each row has a document name and a "download" button. ALL download buttons have the same text: **"download"**. The last row is the ZIP package: "Alle Dokumente der Vergabeunterlagen als ZIP-Paket" with its own "download" button.
- **ZIP download strategy**: Since all buttons say "download", you cannot distinguish them by button text alone. Instead:
  1. Find the row/element containing the text "ZIP-Paket" or "Alle Dokumente".
  2. Find the "download" button within that same row/container.
  3. Click it using `session.page.expect_download()` to capture the URL.
  Example approach:
  ```python
  zip_row = session.page.locator('text=ZIP-Paket').locator('..').locator('button:has-text("download")')
  # or find all download buttons and click the last one (ZIP is always last)
  download_buttons = session.page.locator('button:has-text("download")').all()
  # The last "download" button in the document list is the ZIP
  ```
- If clicking "anzeigen" reveals nothing or errors out, the tender may have expired — return [].

### deutsche-evergabe.de (and bieterzugang.deutsche-evergabe.de)
- **bieterzugang.deutsche-evergabe.de** URLs redirect to **deutsche-evergabe.de** — follow the redirect and use the navigation flow below.
- **Multi-step navigation required** — use `BrowserSession` (Playwright), this site is heavily JS-rendered.
- The URL is a dashboard page (`/dashboards/dashboard_off/<uuid>`). The UUID identifies a **specific tender**.
- **Exact navigation steps:**
  1. `session.goto(url)` — load the dashboard page. Wait 5 seconds for JS to render the data grid.
  2. **Click the tender title**: The tender row contains multiple `<a class="BekSummary" data-button="<uuid>">` elements (the title link and an info icon). There are **two elements** with the same selector, so you MUST use `.first` to avoid Playwright strict mode errors. Click it with `session.page.locator('a.BekSummary').first.click()`. This opens a **Bootstrap modal** (`#BekSummaryModal`) via an AJAX call — NOT a new page.
  3. **Wait for modal**: Wait 5 seconds for the modal content to load.
  4. **Get the file list**: The modal loads document data from a JSON endpoint. Extract the UUID from the URL path (last segment of `/dashboards/dashboard_off/<uuid>`). Then fetch the JSON:
     ```python
     uuid = url.rstrip('/').rsplit('/', 1)[-1]
     file_data = session.page.evaluate('''(uuid) => {
         return new Promise((resolve) => {
             fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                 .then(r => r.json()).then(data => resolve(data));
         });
     }''', uuid)
     ```
  5. **Build download URLs**: Each file in the JSON has a `DokIDStr` (UUID). The download URL pattern is:
     `https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={DokIDStr}`
     Return a list of these URLs, one per file.
  6. If the JSON returns an empty list, check for **Pattern A — "bitte hier klicken"**: Click "Dokumente" tab in the modal (`session.click_text("Dokumente")`), then look for a link with text "bitte hier klicken" — its href is an external download URL. Return ONLY that URL.
- **Important**: Do NOT try to find `<a>` tags for downloads — the file tiles use JavaScript `onItemClick` handlers, not `<a>` hrefs. Use the JSON API approach above.
- Only return [] if the JSON is empty AND no "bitte hier klicken" link exists.

### meinauftrag.rib.de
- This platform typically requires login for document access.
- Check for any publicly accessible document links on the detail page.
- If everything requires authentication, return [].

### aumass (plattform.aumass.de)
- May have PDF converter URLs or direct document links.
- Look for links in the tender detail that point to actual documents.

### staatsanzeiger-eservices.de
- May have a generic download endpoint.
- Look for document links in the tender detail page.

### bi-medien.de (Deutsches Ausschreibungsblatt, also deutsches-ausschreibungsblatt.de)
- **Use `BrowserSession`** — the site is JS-rendered and requires clicking through multiple pages.
- **Cookie consent blocker**: The site has a `<div id="cmpwrapper">` overlay that intercepts all clicks. You MUST remove it before any interaction:
  ```python
  session.page.evaluate('document.querySelector("#cmpwrapper")?.remove()')
  ```
- **Navigation flow**:
  1. Load the tender detail page and wait for JS to render (sleep 5 seconds). Remove the cookie overlay.
  2. The "Vergabeunterlagen" element is a **link (`<a>`)** with `target="_blank"`. Because it opens in a new tab, you must handle the popup:
     ```python
     with session.page.context.expect_page() as new_page_info:
         session.page.locator('a:has-text("Vergabeunterlagen")').first.click()
     new_page = new_page_info.value
     new_page.wait_for_load_state('networkidle')
     ```
  3. On the new page, remove the cookie overlay again (`new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()')`).
  4. Find the **"Unterlagen als ZIP-Datei"** link (`<a>` tag). Do NOT click it — just extract the `href` attribute and return the absolute URL. The href is `/lookup/download/getZip` — join it with the page base URL.
- If no "Vergabeunterlagen" link or ZIP download is found, the documents may be behind a paywall — return [].

### vergabe24.de (bund.vergabe24.de and similar)
- The URL typically contains a hash parameter: `?hash=<hex>`.
- **Use `BrowserSession`** — this site requires clicking through multiple pages.
- **Navigation flow**:
  1. Load the tender detail page and wait for JS to render.
  2. Find and click **"Vergabeunterlagen anfordern"** (request tender documents). This opens an in-window popup/dialog.
  3. In the popup, find and click **"Unterlagen zur Ansicht herunterladen"** (download documents for viewing). This redirects to a new page.
  4. On the new page, click the **"Weiter"** (continue) button. Another page opens.
  5. On the final page, find and click **"Vergabeunterlagen als ZIP-Datei herunterladen"** (download tender documents as ZIP). Use `session.page.expect_download()` to capture the download URL.
- **Alternative pattern — Redirect to NetServer**: Some vergabe24.de pages contain a link to another platform (e.g., `saarvpsl.vmstart.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID=...`). If the page has such a link, follow it and use the NetServer navigation flow described above.
- **Important**: Always check the page content/description for external links to other procurement platforms — these may be the actual source of documents.

### SharePoint (eliagroup.sharepoint.com and similar `:f:` folder sharing links)
- **These are NOT login-gated.** They are public file-sharing links (like Dropbox), not internal SharePoint sites.
- The URL pattern is: `https://<org>.sharepoint.com/:f:/s/<path>?e=<token>`
- **Use `BrowserSession`** — the page is JS-rendered (React/Fluent UI).
- **Navigation flow**:
  1. Load the page and wait for JS to render (wait 8-10 seconds). The page shows a file/folder listing.
  2. In the top toolbar, there is a **"Download"** button (may also appear as "Descărcați" or other localized text, with a download arrow icon). It downloads all files in the folder as a ZIP.
  3. Click that download button using `session.page.expect_download()` to capture the URL.
  4. Look for the button by its command name attribute: `button[name="Download"]` or a button with a download icon in the command bar area at the top.
  5. If the download button is not found by name, look for `[data-automationid="downloadCommand"]` or similar automation IDs.
- **Fallback**: If no download-all button, parse the file list DOM for individual file links. Each row has a file name that links to the document.
- Do NOT assume login is required. These are public sharing links.

### Ariba (eu.mu.ariba.com)
- **These are NOT login-gated** for public tender documents.
- The URL pattern is: `https://eu.mu.ariba.com/uav/project/?token=<uuid>`
- **Use `BrowserSession`** — the page is JS-rendered.
- **Navigation flow**:
  1. Load the page and wait for JS to render (wait 5-8 seconds).
  2. **Scroll down** to find the section with the header **"Tender Documents"** (or "Ausschreibungsunterlagen").
  3. In that section, find and click the **"Download All"** button — this downloads a ZIP of all documents.
  4. Use `session.page.expect_download()` to capture the download URL.
- If no "Download All" button exists, look for individual file download links in the Tender Documents section.

## GENERAL NAVIGATION STRATEGY
1. First, analyze the HTML to identify which platform/software the site uses.
2. Fetch the initial page and look for document sections, tabs, or navigation links.
3. If the current page is an overview/notice page, actively navigate to the documents section:
   - Follow links labeled "Dokumente", "Unterlagen", "Vergabeunterlagen", "Documents"
   - Try query parameter variations: `function=_Documents`, `function=_DownloadTenderDocuments`
   - Try path variations: append `/documents`, `/unterlagen`
4. On the documents page, look for "download all" ZIP first, then individual files.
5. **Validate URLs**: Do NOT return URLs that clearly point to login pages, HTML pages, or navigation endpoints.
   A document URL should either end with a known file extension OR be a download endpoint (containing "download", "DownloadDocument", etc.).

## Function requirements
- Signature (do not change): def fetch_documents(url: str) -> list[str]:
- You MAY import inside the function: requests, re, urllib.parse, bs4.BeautifulSoup
- You MAY use Playwright via the pre-imported `BrowserSession` context manager (already available, do NOT import it).
  **NEVER `import BrowserSession`** — it is already injected into the module scope. Writing `from BrowserSession import BrowserSession` or `import BrowserSession` will cause a ModuleNotFoundError. Just use `with BrowserSession() as session:` directly.
  **NEVER use raw `sync_playwright()` or `async_playwright()`.** Always use `BrowserSession` — it sets locale to de-DE, German Accept-Language headers, and a realistic User-Agent. Many German procurement sites render different content based on locale.
  Usage:
  ```
  with BrowserSession() as session:
      session.goto(url)
      html = session.content()                    # get rendered HTML
      session.click_text("Weiter zu den ...")     # click a button/link by text
      zip_url = session.find_zip_or_download_all()  # find ZIP/download-all link
      links = session.get_download_links()          # get all document download links
      all_links = session.get_all_links()           # get all <a> with href, text, abs_href
  ```
- **When to use Playwright vs requests:**
  - Use `requests` for simple sites where documents are in the initial HTML (e.g., NetServer with known URL patterns).
  - Use `BrowserSession` (Playwright) when the site is JS-heavy, requires clicking buttons, or has multi-step navigation
    (e.g., evergabe.de "Weiter zu den Vergabeunterlagen" flow, deutsche-evergabe.de popup navigation).
  - If the HTML snippet you receive looks mostly empty, has JavaScript framework markers (React, Angular, Vue),
    or has placeholder/loading content — use `BrowserSession`.
- The function MUST actively fetch sub-pages when needed.
- Follow redirects (requests does this by default, Playwright handles this automatically).
- All returned URLs must be absolute (use urllib.parse.urljoin if using requests)
- Return [] on any error — never raise exceptions
- Max 150 lines

## CRITICAL output rules
- Respond with ONLY a valid JSON object, no markdown, no explanation
- The function_code value must be a SINGLE LINE string with literal \\n for newlines
- Do NOT use actual newlines inside the JSON string value
- Escape all backslashes properly: use \\\\ for literal backslash, \\n for newline, \\t for tab
- Example of correct function_code: "def fetch_documents(url):\\n    import requests\\n    return []"
{
  "platform_guess": "<short platform name>",
  "has_download_all": true or false,
  "function_code": "<complete Python function as a single-line string>"
}
"""


def _fetch_html(url: str, timeout: int = 15) -> str:
    """Fetch URL: try urllib first, fall back to Playwright for JS-heavy sites."""
    html = _fetch_html_urllib(url, timeout=timeout)
    if html:
        return html
    return _fetch_html_playwright(url, timeout=timeout)


def _fetch_html_urllib(url: str, timeout: int = 15) -> str:
    """Fetch URL with urllib. Returns HTML or empty string."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(512_000)
            charset = "utf-8"
            ct = resp.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w-]+)", ct)
            if m:
                charset = m.group(1)
            return raw.decode(charset, errors="replace")
    except Exception:
        return ""


def _fetch_html_playwright(url: str, timeout: int = 20) -> str:
    """Fetch URL with Playwright (headless Chromium). Handles JS-rendered pages."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                html = page.content()
            finally:
                ctx.close()
                browser.close()
            return html
    except Exception:
        return ""


def _call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 90,
) -> str:
    """Call OpenRouter chat completions. Returns the assistant message text."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
    }).encode()

    req = Request(
        OPENROUTER_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/tender-scraper",
            "X-Title": "tender-scraper",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response, with robust error recovery."""
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

    # Find the JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object found in LLM response:\n{text[:500]}")

    raw = m.group(0)

    # Try parsing as-is first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Recovery: extract function_code separately since it's the problematic field
    # Look for the code between "function_code": " and the closing "
    code_match = re.search(
        r'"function_code"\s*:\s*"(.*)"(?:\s*[,}])',
        raw,
        re.DOTALL,
    )
    platform_match = re.search(r'"platform_guess"\s*:\s*"([^"]*)"', raw)
    download_match = re.search(r'"has_download_all"\s*:\s*(true|false)', raw, re.IGNORECASE)

    if code_match:
        # Fix common escape issues in the code string
        code_raw = code_match.group(1)
        # Decode JSON-style escape sequences to real characters
        code_fixed = code_raw.replace('\\n', '\n').replace('\\t', '\t')
        code_fixed = code_fixed.replace('\\"', '"').replace('\\\\', '\\')
        code_fixed = code_fixed.replace('\r', '')

        return {
            "platform_guess": platform_match.group(1) if platform_match else "unknown",
            "has_download_all": (download_match.group(1).lower() == "true") if download_match else False,
            "function_code": code_fixed,
        }

    raise ValueError(f"Could not parse LLM JSON response:\n{raw[:500]}")


def _domain(url: str) -> str:
    return re.sub(r"^www\.", "", urlsplit(url).netloc)


def _cache_path(domain: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", domain)
    return CACHE_DIR / f"{safe}.py"


def _load_cached_function(domain: str) -> str | None:
    p = _cache_path(domain)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _save_cached_function(domain: str, code: str, platform_guess: str) -> None:
    p = _cache_path(domain)
    header = f"# platform_guess: {platform_guess}\n# domain: {domain}\n\n"
    p.write_text(header + code, encoding="utf-8")


def _run_function(code: str, url: str) -> list[str]:
    """
    Execute the generated fetch_documents function in an isolated namespace
    and return the result. Returns [] on any error.

    BrowserSession from browser_helper is injected into the namespace so
    generated scrapers can use Playwright without importing it.
    """
    from browser_helper import BrowserSession

    namespace: dict = {"BrowserSession": BrowserSession}
    try:
        exec(compile(code, "<llm_generated>", "exec"), namespace)  # noqa: S102
        fetch_fn = namespace.get("fetch_documents")
        if not callable(fetch_fn):
            return []
        result = fetch_fn(url)
        if isinstance(result, list):
            return [str(u) for u in result if u]
        return []
    except Exception:
        return []


def generate_and_run(
    url: str,
    api_key: str,
    model: str = "google/gemini-2.5-flash",
    force_regenerate: bool = False,
    html: str | None = None,
) -> dict:
    """
    High-level entry point.

    Returns:
    {
        "urls": [...],           # discovered document URLs
        "platform_guess": "...",
        "cached": True/False,    # whether we used a cached function
        "error": None or str,
        "has_download_all": ...,
    }
    """
    domain = _domain(url)

    # 1. Try cache first
    cached_code = None if force_regenerate else _load_cached_function(domain)
    if cached_code:
        urls = _run_function(cached_code, url)
        m = re.search(r"# platform_guess: (.+)", cached_code)
        platform_guess = m.group(1).strip() if m else "unknown"
        return {"urls": urls, "platform_guess": platform_guess, "cached": True,
                "error": None, "has_download_all": None}

    # 2. Fetch HTML if not provided
    if html is None:
        html = _fetch_html(url)
        if not html:
            return {"urls": [], "platform_guess": "unknown", "cached": False,
                    "error": "failed_to_fetch_html", "has_download_all": False}

    snippet = html[:HTML_SNIPPET_CHARS]

    user_prompt = (
        f"URL: {url}\n\n"
        f"HTML snippet (first {HTML_SNIPPET_CHARS} chars):\n"
        f"```html\n{snippet}\n```\n\n"
        "Write the fetch_documents function for this site."
    )

    # 3. Call LLM (with one retry on parse failure)
    last_error = None
    for attempt in range(2):
        try:
            raw_response = _call_openrouter(user_prompt, api_key=api_key, model=model)
            parsed = _extract_json(raw_response)
            code = parsed["function_code"]
            platform_guess = parsed.get("platform_guess", "unknown")
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                continue
            return {"urls": [], "platform_guess": "unknown", "cached": False,
                    "error": f"llm_error:{last_error}", "has_download_all": False}

    # 4. Run the generated code
    urls = _run_function(code, url)

    # 5. Cache it
    has_download_all = bool(parsed.get("has_download_all", False))
    _save_cached_function(domain, code, platform_guess)

    return {"urls": urls, "platform_guess": platform_guess, "cached": False,
            "error": None, "has_download_all": has_download_all}
