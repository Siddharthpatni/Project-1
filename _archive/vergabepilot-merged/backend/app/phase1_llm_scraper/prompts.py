"""
Prompt templates for Phase-1 document-downloader generation.

Centralizing prompts here makes A/B testing different prompting strategies
trivial: swap the template, rerun the benchmark harness.
"""
from textwrap import dedent

SYSTEM_PROMPT = dedent("""
    You are an expert Python web-scraping engineer specializing in public
    procurement / tender portals. Your SOLE JOB is to generate a single
    self-contained Python script that DOWNLOADS ALL DOCUMENTS from a
    given webpage.

    What counts as a "document":
       - PDFs, DOCX, DOC, ZIPs, XML, XLS, XLSX, CSV, ODS, RTF, PPT,
         PPTX, JPG, PNG, or any other downloadable file attachment.
       - Anything behind a "Download" / "Herunterladen" / "Unterlagen" /
         "Dokument" link/button.
       - Files linked inside detail/sub-pages reachable from the main URL.
       - Files served via JavaScript click handlers, POST requests, or
         iframe-based viewers.

    How to find ALL documents:
       1. Look at the current page for every `<a href>` pointing to a
          downloadable file (common extensions or Content-Disposition).
       2. If the page is a listing (table of tenders), navigate into
          EACH detail page and download documents from there too.
       3. If documents are behind buttons that trigger JS downloads, use
          Playwright's `page.expect_download()` to capture them.
       4. Handle pagination — if there's a "Next" / "Weiter" button,
          follow it to get ALL pages.
       5. Deduplicate by filename to avoid downloading the same file twice.

    Hard requirements:
    1. The script must define:
       `def scrape(url: str, output_dir: str) -> dict`
       that returns a dictionary with ONE key:
         - "downloaded_files": a list of absolute file paths successfully
           saved to `output_dir`
       Example return value:
         {"downloaded_files": ["/output/tender_123.pdf", "/output/specs.docx"]}
    2. Use `playwright.sync_api` for browser automation. The required
       import is `from playwright.sync_api import sync_playwright`.
       Do NOT use `playwright.async_api`. Run headless.
    3. For direct file URLs, you may use `requests` or Playwright — pick
       whichever is more reliable for the site.
    4. Never call `os.system`, `subprocess`, `eval`, `exec`,
       `__import__`. Never `import subprocess`, `import socket`,
       `import ctypes`, or `import multiprocessing`.
    5. Respect a 60-second total wall-clock budget. Set short
       per-request timeouts (5-10s) and cap retries at 1.
    6. Do not write to any path outside `output_dir`.
    7. Preserve original filenames. If a filename is unknown, derive one
       from the URL path or a counter (e.g. `doc_001.pdf`).
    8. Detect the correct file extension from Content-Type headers or
       magic bytes — do NOT blindly name everything `.pdf`.
    9. Wrap the whole `scrape()` body in a try/except so a single
       failing link can't crash the whole run; collect what you can.
    10. Return ONLY the Python code inside a ```python``` fenced block.
       No prose, no explanations — just the code.

    Skeleton you should follow:
    ```python
    import os
    from urllib.parse import urljoin, urlparse
    import requests
    from playwright.sync_api import sync_playwright

    DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
                ".csv", ".ods", ".rtf", ".ppt", ".pptx"}

    def scrape(url: str, output_dir: str) -> dict:
        os.makedirs(output_dir, exist_ok=True)
        saved = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # ... discover links / click buttons / handle pagination ...
            browser.close()
        return {"downloaded_files": saved}
    ```
""").strip()


GENERATION_USER_PROMPT = dedent("""
    Target URL: {url}
    Detected domain: {domain}

    Page structure (first 6000 chars of rendered HTML):
    ```html
    {html_snippet}
    ```

    Previously tried selectors that failed (if any):
    {failed_selectors}

    Your ONLY task:
    FIND and DOWNLOAD **every single document** linked on this page
    (and on any sub-pages / detail pages reachable from it).
    Save all files into `output_dir`.

    Important:
    - Check ALL tabs, expandable sections, and pagination.
    - Follow links to detail/sub-pages and download documents from there.
    - Handle JS-triggered downloads with `page.expect_download()`.
    - Deduplicate by filename.
    - Detect correct file extensions (don't assume everything is PDF).
    - Return dict with "downloaded_files" key only.

    Generate the downloader now.
""").strip()


FEEDBACK_PROMPT = dedent("""
    Your previous document-downloader attempt failed. Here is the diagnostic:

    Iteration: {iteration} of {max_iterations}
    URL: {url}

    Execution outcome: {outcome}
    Error message / stderr:
    ```
    {error}
    ```

    Documents expected (approx): {expected_docs}
    Documents actually downloaded: {downloaded}

    Fix the code. Key rules:
    - Keep the `scrape(url, output_dir) -> dict` signature unchanged.
    - Return dict must have "downloaded_files" (list of saved file paths).
    - Focus ONLY on finding and downloading ALL documents.
    - If the site uses JavaScript to reveal content or download links,
      wait for network idle / relevant DOM selectors before extracting.
    - If downloads happen via POST, use `page.expect_download()` and
      save via `download.save_as()`.
    - Check for pagination, tabs, sub-pages — don't miss any documents.
    - Detect correct file extensions from Content-Type or magic bytes.
    - Return ONLY the corrected Python code in a fenced block.
""").strip()


def build_generation_prompt(
    url: str,
    domain: str,
    html_snippet: str,
    failed_selectors: list[str] | None = None,
) -> str:
    return GENERATION_USER_PROMPT.format(
        url=url,
        domain=domain,
        html_snippet=html_snippet[:6000],
        failed_selectors=", ".join(failed_selectors or []) or "none",
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
# Platform-specific knowledge (from the development branch's proven prompts)
# ---------------------------------------------------------------------------
#
# When the platform classifier identifies a known German procurement portal,
# we splice the relevant hints into the user prompt. These are the
# hard-won navigation patterns from the dev branch's 89%-success runs.

PLATFORM_HINTS: dict[str, str] = {
    "netserver": dedent("""
        Platform: NetServer family (vergabe.autobahn.de, tender24.de, etc.)
        - The tender details page URL uses `function=_Details` or `function=Detail`.
        - To get the ZIP of all documents, construct a URL with
          `function=_DownloadTenderDocuments` keeping the same `TenderOID`.
          Pattern:
          `{base}/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}`
        - Some sites need extra params (documentOID, TenderAuthority, TenderDate)
          which are visible in hidden form fields or links on the page.
        - Do NOT validate the ZIP URL with a HEAD request — just construct
          and download it. Some servers don't respond correctly to HEAD.
    """).strip(),

    "evergabe_de": dedent("""
        Platform: evergabe.de
        - Use Playwright — the site requires JS rendering.
        - Do NOT click through multi-step pages (they redirect-loop).
        - Extract the tender ID (last numeric segment of the URL path),
          then navigate directly to `https://www.evergabe.de/unterlagen/{id}`.
        - On that page, find all `<a>` tags with text "Datei herunterladen" —
          each href is a download link.
        - Rate limit: insert a 5-second delay between requests to this domain.
    """).strip(),

    "evergabe_online": dedent("""
        Platform: evergabe-online.de (Apache Wicket framework)
        - Search all `<a href>` for one containing the string `zipDownloadButton`.
          That is the ZIP download link.
        - The href has HTML-encoded ampersands (`&amp;`) — call
          `html.unescape(href)` before using the URL.
        - Search by href content, NOT by link text (text may be nested in
          child elements).
        - Ignore links to `archivedProcedures.html` or `login.html`.
    """).strip(),

    "subreport": dedent("""
        Platform: subreport.de / subreport-elvis.de (ELViS)
        - Documents are publicly accessible — do NOT assume login is required.
        - The site MUST be loaded with `Accept-Language: de-DE` and
          `locale="de-DE"` in the Playwright context — German rendering is
          required for the navigation buttons to appear.
        - Click the "anzeigen" button to reveal the document list. Wait
          5 seconds after clicking.
        - Then look for a row containing "ZIP-Paket" or "Alle Dokumente"
          and click its "download" button. The ZIP is typically the last
          row in the document table.
        - Use `page.expect_download()` to capture the download.
    """).strip(),

    "deutsche_evergabe": dedent("""
        Platform: deutsche-evergabe.de
        - The dashboard URL ends with a tender UUID.
        - Wait 5 seconds for JS, click `a.BekSummary` (use `.first` —
          there are duplicates), wait 5 seconds for the modal.
        - Fetch the file list via:
          `fetch("/Verfahren/dxVUFilesForSupplier/{uuid}")`
        - Each file in the JSON has a `DokIDStr`. Build download URLs:
          `https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={DokIDStr}`
    """).strip(),

    "bi_medien": dedent("""
        Platform: bi-medien.de / deutsches-ausschreibungsblatt.de
        - Use Playwright — JS-rendered.
        - Remove the cookie overlay first:
          `page.evaluate('document.querySelector("#cmpwrapper")?.remove()')`
        - Click "Vergabeunterlagen" (opens in a new tab — handle the popup
          via `context.expect_page()`).
        - On the new page, look for an `<a>` with text "Unterlagen als
          ZIP-Datei". Take its href (typically `/lookup/download/getZip`)
          and download it.
    """).strip(),

    "vergabe24": dedent("""
        Platform: vergabe24.de (and bund.vergabe24.de)
        - Use Playwright — multi-step click navigation required.
        - Sequence: "Vergabeunterlagen anfordern" → in popup
          "Unterlagen zur Ansicht herunterladen" → "Weiter" → final page
          → "Vergabeunterlagen als ZIP-Datei herunterladen".
        - Capture downloads via `page.expect_download()`.
        - Some pages redirect to NetServer — if you see a NetServer link
          on the page, follow it and apply the NetServer flow instead.
    """).strip(),

    "sharepoint": dedent("""
        Platform: SharePoint `:f:` folder share (NOT login-gated)
        - Wait 8-10 seconds for the React/Fluent UI shell to render.
        - Click the "Download" button in the top command bar — selector
          `button[name="Download"]` or `[data-automationid="downloadCommand"]`.
        - Use `page.expect_download()` to capture the ZIP.
    """).strip(),

    "ariba": dedent("""
        Platform: Ariba (eu.mu.ariba.com) — NOT login-gated for public tenders
        - Wait 5-8 seconds for JS to render.
        - Scroll to the "Tender Documents" / "Ausschreibungsunterlagen"
          section and click "Download All".
        - Capture via `page.expect_download()`.
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

    Your scraper MUST follow this exact route. The route has been verified
    to lead to documents — do not deviate from it. Implement each step in
    order, using Playwright. Use the selectors and text shown above to
    locate elements.

    Discovered document links (use these to verify your scraper hits the
    same files):
    {discovered_links}

    Page structure (first 6000 chars of rendered HTML, for reference):
    ```html
    {html_snippet}
    ```

    Generate the downloader now. Follow the route exactly. Return ONLY the
    Python code in a fenced block.
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
        html_snippet=html_snippet[:6000],
    )
