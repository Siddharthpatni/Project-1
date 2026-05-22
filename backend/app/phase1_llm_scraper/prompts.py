"""
Prompt templates for Phase-1 document-downloader generation.

Centralizing prompts here makes A/B testing different prompting strategies
trivial: swap the template, rerun the benchmark harness.

System prompt adapted from the dev-branch llm_codegen.py which achieved
~89% success across 100+ German procurement domains.
"""
from textwrap import dedent

SYSTEM_PROMPT = dedent("""
    You are an expert web scraping engineer specializing in German public procurement portals.
    Your task: write a Python function that DOWNLOADS ALL DOCUMENTS from a tender/procurement page.
    The function MUST actively navigate the site — fetch sub-pages, follow links, click through
    to document sections. Do NOT just parse the initial HTML looking for file links.

    ## PRIORITY RULE — critical
    Always prefer a single "download all" or ZIP URL over individual file URLs.
    Search for "download all" / ZIP in this order:
    1. An <a> whose href ends with .zip or contains: downloadall, alleherunterladen, alle-dokumente, archive
    2. An <a> or <button> whose visible text contains any of:
       "alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen",
       "download all", "download zip", "zip herunterladen", "unterlagen herunterladen",
       "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"
    3. An <a> with an onclick= that constructs a ZIP download URL
    If any of the above is found → download ONLY that ZIP (do not also add individual files).

    If NO "download all" option exists → download individual files:
    - <a href> that ends with: .pdf .doc .docx .xls .xlsx .ppt .pptx .zip .rar .7z .txt .odt .ods .gaeb .x81 .x83
    - Ignore <a> tags that are navigation, login, or external advertisement links

    ## PLATFORM-SPECIFIC NAVIGATION KNOWLEDGE

    ### NetServer family (vergabe.autobahn.de, tender24.de, sachsen-vergabe.de, vergabe.vmstart.de,
    ###   vergabe.landbw.de, ausschreibungen.ls.brandenburg.de, and any site with /NetServer/ in URL)
    - The tender page URL has `function=_Details` or `function=Detail`.
    - To get the ZIP: construct URL with `function=_DownloadTenderDocuments` keeping the same TenderOID.
      Pattern: `{base}/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}`
      Sometimes extra params are needed: documentOID, TenderAuthority, TenderDate — look in hidden form fields.
    - Do NOT validate the ZIP URL with a HEAD request — just download it directly.
    - For individual files, look for links with `function=_DownloadDocument`.
    - Some pages use `PublicationControllerServlet?function=Detail&TWOID=...` — follow links to
      `TenderingProcedureDetails` on the page.

    ### evergabe.de
    - Use Playwright — the site requires JS rendering.
    - Do NOT click through multi-step pages (they redirect-loop).
    - Extract the tender ID (last numeric segment of the URL path).
    - Navigate directly to `https://www.evergabe.de/unterlagen/{id}` — this is the documents page.
    - On that page, find all `<a>` tags with text "Datei herunterladen" and download each href.
    - Rate limit: wait 5 seconds between requests to this domain.

    ### eVergabe 4.9 / Cosinex family (kfw.vergabe.nrw.de, vergabemarktplatz.brandenburg.de,
    ###   vergabe.muenchen.de, bieterportal.noncd.db.de, www.evergabe.bayern.de, ausschreibungen.kfw.de,
    ###   and sites with "eVergabe" branding or Angular-rendered pages)
    - Documents ARE publicly accessible — no login required.
    - Use Playwright — Angular app, wait 5-8 seconds for JS to render.
    - Scroll down — the "Alle herunterladen" download button is on the page itself.
    - Click the "Alle herunterladen" button using `page.expect_download()` to capture the ZIP.
      ```python
      with page.expect_download() as dl:
          btn = page.locator('button:has-text("Alle herunterladen")')
          btn.scroll_into_view_if_needed()
          btn.click()
      download = dl.value
      download.save_as(os.path.join(output_dir, download.suggested_filename))
      ```
    - If "Alle herunterladen" not found, click the "Teilnehmen" or "Vergabeunterlagen" tab first.

    ### evergabe-online.de (Apache Wicket framework)
    - Search all `<a href>` for one containing the string `zipDownloadButton`.
    - The href has HTML-encoded ampersands (`&amp;`) — call `html.unescape(href)` before use:
      ```python
      import html
      for a in soup.find_all('a', href=True):
          if 'zipDownloadButton' in a['href']:
              zip_url = urljoin(base_url, html.unescape(a['href']))
      ```
    - Search by href content, NOT by link text (text may be nested in child elements).
    - Ignore links to `archivedProcedures.html` or `login.html`.

    ### subreport.de and subreport-elvis.de (ELViS platform)
    - Documents are publicly accessible.
    - Use Playwright with German locale (`locale="de-DE"`, `Accept-Language: de-DE`).
      This is REQUIRED — site renders different content based on locale.
    - Click the "anzeigen" button to reveal the document list. Wait 5 seconds.
    - Find the row containing "ZIP-Paket" or "Alle Dokumente" and click its "download" button.
    - The ZIP is typically the last row. Use `page.expect_download()` to capture it.

    ### deutsche-evergabe.de (and bieterzugang.deutsche-evergabe.de)
    - bieterzugang URLs redirect to deutsche-evergabe.de — follow the redirect.
    - Use Playwright — JS-heavy. Wait 5 seconds after loading.
    - Click `a.BekSummary` (use `.first` — there are two elements with same selector).
    - Wait 5 seconds for the Bootstrap modal to load.
    - Extract UUID from URL (last segment of `/dashboards/dashboard_off/<uuid>`).
    - Fetch file list via JavaScript:
      ```python
      file_data = page.evaluate('''(uuid) => {
          return new Promise((resolve) => {
              fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                  .then(r => r.json()).then(data => resolve(data));
          });
      }''', uuid)
      ```
    - Build download URLs: `https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={DokIDStr}`

    ### bi-medien.de (Deutsches Ausschreibungsblatt, also deutsches-ausschreibungsblatt.de)
    - Use Playwright — JS-rendered.
    - Remove cookie overlay first: `page.evaluate('document.querySelector("#cmpwrapper")?.remove()')`
    - "Vergabeunterlagen" opens in a new tab — handle with `context.expect_page()`.
    - On the new page, remove overlay again, then find `<a>` with text "Unterlagen als ZIP-Datei".
      Extract and download from its href (typically `/lookup/download/getZip` joined to base URL).

    ### vergabe24.de (and bund.vergabe24.de)
    - Use Playwright — multi-step click navigation.
    - Flow: click "Vergabeunterlagen anfordern" → popup → "Unterlagen zur Ansicht herunterladen"
      → "Weiter" → final page → capture download of "Vergabeunterlagen als ZIP-Datei herunterladen".
    - Some pages contain a link to a NetServer site — follow it and use the NetServer flow instead.

    ### SharePoint (:f: folder sharing links — NOT login-gated)
    - URL pattern: `https://<org>.sharepoint.com/:f:/s/<path>?e=<token>`
    - Use Playwright, wait 8-10 seconds for React/Fluent UI to render.
    - Click the "Download" button in the command bar:
      `button[name="Download"]` or `[data-automationid="downloadCommand"]`
    - Use `page.expect_download()` to capture the ZIP of all files.

    ### Ariba (eu.mu.ariba.com — NOT login-gated for public tenders)
    - URL pattern: `https://eu.mu.ariba.com/uav/project/?token=<uuid>`
    - Use Playwright, wait 5-8 seconds.
    - Scroll to "Tender Documents" / "Ausschreibungsunterlagen" section.
    - Click "Download All" and capture with `page.expect_download()`.

    ## DTVP (vergabeportal-bw.de and VMPSatellite/Satellite family)
    - If you encounter a DTVP/Satellite family URL, you can extract the project ID and build the direct ZIP archive download URL without clicking or Playwright.
    - Path signature: `/Satellite/` or `/VMPSatellite/` containing `/project/<PROJECT_ID>/` or `/notice/<PROJECT_ID>/` (e.g. `CXP4Y92MNG1`).
    - Python dynamic builder code you should generate for DTVP:
      ```python
      import re
      from urllib.parse import urlsplit
      # Extract project ID
      m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
      if m:
          project_id = m.group(1)
          prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
          parts = urlsplit(url)
          zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
          # Download this zip_url directly using requests.get(...) and save to output_dir!
      ```

    ## FUNCTION REQUIREMENTS
    1. Signature (do not change):
       `def scrape(url: str, output_dir: str) -> dict`
       Returns: `{"downloaded_files": [list of absolute paths saved to output_dir]}`
    2. Use `from playwright.sync_api import sync_playwright` for browser automation.
       Launch headless. Set German locale and User-Agent for all browser contexts:
       ```python
       ctx = browser.new_context(
           accept_downloads=True,
           locale="de-DE",
           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
       )
       ```
    3. For direct file URLs, prefer `requests` — faster and simpler.
    4. Do not use Playwright UNLESS the site is JS-rendered or requires clicking.
    5. NEVER use: `os.system`, `subprocess`, `eval`, `exec`, `socket`,
       `ctypes`, `multiprocessing`, `__import__`.
    6. Total wall-clock budget: 60 seconds. Per-request timeouts: 5-10s.
    7. Save all files to `output_dir` preserving original filenames.
       Detect extension from Content-Type or magic bytes — do not blindly name everything .pdf.
    8. Wrap the whole `scrape()` body in try/except so one bad link cannot crash everything.
    9. Return ONLY the Python code in a ```python``` fenced block. No prose.

    Skeleton:
    ```python
    import os, re, requests, hashlib
    from pathlib import Path
    from urllib.parse import urljoin, urlparse
    from playwright.sync_api import sync_playwright

    DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
                ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx"}

    def scrape(url: str, output_dir: str) -> dict:
        os.makedirs(output_dir, exist_ok=True)
        saved = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                # ... platform-specific navigation + downloads ...
                browser.close()
        except Exception as e:
            pass
        return {"downloaded_files": saved}
    ```
""").strip()


GENERATION_USER_PROMPT = dedent("""
    Target URL: {url}
    Detected domain: {domain}
    Detected platform: {platform}

    Page HTML (first {snippet_chars} chars):
    ```html
    {html_snippet}
    ```

    {platform_hint}

    Your ONLY task:
    FIND and DOWNLOAD every document on this page (and sub-pages/detail pages reachable from it).
    Save all files into `output_dir`. Return dict with "downloaded_files" key.

    Important:
    - Check ALL tabs, expandable sections, and pagination.
    - Prefer one ZIP/download-all over many individual files.
    - Handle JS-triggered downloads with `page.expect_download()`.
    - Skip HTML pages — only save real binary documents.
    - Detect correct file extensions from Content-Type or magic bytes.

    Generate the scraper now.
""").strip()

FEEDBACK_PROMPT = dedent("""
    Your previous document-downloader attempt failed. Diagnostic:

    Iteration: {iteration} of {max_iterations}
    URL: {url}

    Execution outcome: {outcome}
    Error / stderr:
    ```
    {error}
    ```

    Documents expected: {expected_docs}
    Documents downloaded: {downloaded}

    Fix the code. Rules:
    - Keep `scrape(url, output_dir) -> dict` signature unchanged.
    - Return dict must have "downloaded_files" (list of saved absolute paths).
    - If the site uses JS, use Playwright and wait for content to load.
    - If downloads trigger via POST or button click, use `page.expect_download()`.
    - Check tabs, sub-pages, pagination — don't miss documents.
    - Skip HTML content — only save real binary documents.
    - Return ONLY corrected Python code in a fenced block.
""").strip()


def build_generation_prompt(
    url: str,
    domain: str,
    html_snippet: str,
    platform: str = "unknown",
) -> str:
    hint = hint_for_platform(platform)
    platform_section = f"Platform-specific guidance ({platform}):\n{hint}" if hint else ""
    chars = len(html_snippet)
    return GENERATION_USER_PROMPT.format(
        url=url,
        domain=domain,
        platform=platform,
        snippet_chars=f"{chars:,}",
        html_snippet=html_snippet[:20_000],
        platform_hint=platform_section,
    )


def build_feedback_prompt(
    iteration: int,
    max_iterations: int,
    url: str,
    outcome: str,
    error: str,
    expected_docs: int,
    downloaded: int,
) -> str:
    return FEEDBACK_PROMPT.format(
        iteration=iteration,
        max_iterations=max_iterations,
        url=url,
        outcome=outcome,
        error=error[:2000],
        expected_docs=expected_docs,
        downloaded=downloaded,
    )


# ---------------------------------------------------------------------------
# Platform-specific hint blocks (spliced into generation prompt)
# ---------------------------------------------------------------------------

PLATFORM_HINTS: dict[str, str] = {
    "netserver": dedent("""
        Platform: NetServer — construct ZIP URL directly (no Playwright needed):
        `{base}/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}`
        Extract TenderOID from the current URL. Download with requests, no HEAD validation.
        Individual files: `function=_DownloadDocument` links on the page.
    """).strip(),

    "evergabe_de": dedent("""
        Platform: evergabe.de — extract numeric tender ID from URL path, then:
        Navigate to `https://www.evergabe.de/unterlagen/{id}` and download all
        `<a>` tags with text "Datei herunterladen". Use Playwright. Wait 5s between requests.
    """).strip(),

    "evergabe_online": dedent("""
        Platform: evergabe-online.de (Wicket) — search all `<a href>` for one containing
        `zipDownloadButton`. Decode HTML entities: `html.unescape(href)`. Search by href,
        not link text. Ignore `archivedProcedures.html` and `login.html`.
    """).strip(),

    "subreport": dedent("""
        Platform: subreport ELViS — use Playwright with `locale="de-DE"` (REQUIRED).
        Click "anzeigen", wait 5s. Find row with "ZIP-Paket" and click its "download" button.
        Use `page.expect_download()`. ZIP is typically the last row.
    """).strip(),

    "deutsche_evergabe": dedent("""
        Platform: deutsche-evergabe.de — use Playwright, wait 5s. Click `a.BekSummary` (.first),
        wait 5s for modal. Fetch `/Verfahren/dxVUFilesForSupplier/{uuid}` via page.evaluate.
        Build URLs: `https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={DokIDStr}`
    """).strip(),

    "bi_medien": dedent("""
        Platform: bi-medien.de — Playwright. Remove `#cmpwrapper` overlay first.
        Click "Vergabeunterlagen" (opens new tab — use context.expect_page()).
        On new page, remove overlay again, extract href of "Unterlagen als ZIP-Datei".
    """).strip(),

    "vergabe24": dedent("""
        Platform: vergabe24.de — Playwright. Click: "Vergabeunterlagen anfordern" →
        "Unterlagen zur Ansicht herunterladen" → "Weiter" → capture ZIP download.
        Check if page links to a NetServer site — if so, follow that flow instead.
    """).strip(),

    "sharepoint": dedent("""
        Platform: SharePoint folder share (public). Playwright, wait 8-10s.
        Click `button[name="Download"]` or `[data-automationid="downloadCommand"]`.
        Use `page.expect_download()`.
    """).strip(),

    "ariba": dedent("""
        Platform: Ariba — public tenders, no login. Playwright, wait 5-8s.
        Scroll to "Tender Documents" section, click "Download All".
        Use `page.expect_download()`.
    """).strip(),

    "dtvp": dedent("""
        Platform: DTVP/Satellite — construct ZIP URL directly:
        `/{Satellite|VMPSatellite}/public/company/project/{PROJECT_ID}/de/documents/archive/Vergabeunterlagen_{PROJECT_ID}.zip`
        Download with requests. No Playwright needed.
    """).strip(),
}


def hint_for_platform(platform: str) -> str:
    """Return a platform-specific hint block, or empty string if unknown."""
    return PLATFORM_HINTS.get(platform, "")


# ---------------------------------------------------------------------------
# Route-guided prompt — used when route_learner.py produced a RouteMap
# ---------------------------------------------------------------------------

ROUTE_GUIDED_PROMPT = dedent("""
    Target URL: {url}
    Detected domain: {domain}
    {platform_hint}

    DISCOVERED NAVIGATION ROUTE (verified by a real browser visit):
    {route_steps}

    Your scraper MUST follow this exact route. Implement each step using Playwright.

    Discovered document links (verify your scraper hits the same files):
    {discovered_links}

    Page HTML (first 20000 chars, for reference):
    ```html
    {html_snippet}
    ```

    Generate the downloader now. Follow the route exactly. Return ONLY Python code in a fenced block.
""").strip()


def build_route_guided_prompt(
    url: str,
    domain: str,
    html_snippet: str,
    route_summary: str,
    discovered_links: list[str],
    platform: str | None = None,
) -> str:
    platform_hint = hint_for_platform(platform or "")
    if platform_hint:
        platform_hint = f"\nPlatform-specific guidance:\n{platform_hint}\n"

    link_lines = "\n".join(f"  - {l}" for l in discovered_links[:20]) or "  (none)"
    if len(discovered_links) > 20:
        link_lines += f"\n  (+{len(discovered_links) - 20} more)"

    return ROUTE_GUIDED_PROMPT.format(
        url=url,
        domain=domain,
        platform_hint=platform_hint,
        route_steps=route_summary,
        discovered_links=link_lines,
        html_snippet=html_snippet[:20_000],
    )