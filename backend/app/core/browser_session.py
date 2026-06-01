"""
Shared Playwright session for German procurement portals.

This is the proven browser-automation helper from the development branch,
moved here so that:

  * the Phase 1 route_learner can use it to trace navigation paths,
  * Phase 2 CUA agents can reuse the same defaults (locale, headers,
    cookie-banner removal), and
  * LLM-generated scrapers can be optionally executed with it injected.

Why a wrapper and not raw Playwright:
  * German procurement sites require `Accept-Language: de-DE` to render
    the right buttons (subreport.de is the textbook case).
  * Most sites overlay a cookie consent dialog that intercepts clicks
    — `_dismiss_cookie_banners` handles the common ones in one call.
  * `find_zip_or_download_all` and `get_download_links` encode hard-won
    heuristics about what counts as a download on these portals.
"""
from __future__ import annotations

from urllib.parse import urljoin


class BrowserSession:
    """
    Context manager that provides a Playwright page with sensible defaults
    for German procurement portals.

    Usage:
        with BrowserSession() as session:
            session.goto("https://example.com")
            html = session.content()
            links = session.get_all_links()
    """

    def __init__(self, headless: bool = True, timeout: int = 12_000):  # was 20_000
        self._headless = headless
        self._timeout = timeout
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="de-DE",
            extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.7"},
            accept_downloads=True,
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(self._timeout)
        return self

    def __exit__(self, *exc):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        return False

    # ---- navigation --------------------------------------------------------

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """Navigate to URL and wait for page load."""
        self.page.goto(url, wait_until=wait_until, timeout=self._timeout)
        # networkidle wait removed — it adds up to 10s per page load in the
        # route learner and is not needed for link/button extraction.
        self._dismiss_cookie_banners()

    def _dismiss_cookie_banners(self) -> None:
        """Remove common cookie consent overlays that block interaction."""
        try:
            # Usercentrics (evergabe.de family)
            self.page.evaluate(
                'document.querySelector("#usercentrics-root")?.remove()'
            )
            # CMP wrapper (bi-medien.de family)
            self.page.evaluate(
                'document.querySelector("#cmpwrapper")?.remove()'
            )
            # Generic cookie banner patterns
            self.page.evaluate("""
                for (const sel of [
                    '.cookie-banner', '.cookie-consent', '.cc-banner',
                    '#cookie-banner', '#cookie-consent', '#onetrust-banner-sdk',
                    '.gdpr-banner', '#gdpr-banner'
                ]) {
                    const el = document.querySelector(sel);
                    if (el) el.remove();
                }
            """)
        except Exception:
            pass

    def content(self) -> str:
        return self.page.content()

    def url(self) -> str:
        return self.page.url

    # ---- interaction -------------------------------------------------------

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        self.page.wait_for_selector(selector, timeout=timeout or self._timeout)

    def click_and_wait(self, selector: str, wait_ms: int = 3000) -> bool:
        """Click a CSS selector; return True if click succeeded."""
        try:
            self.page.click(selector, timeout=5000)
            self.page.wait_for_timeout(wait_ms)
            try:
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def click_text(self, text: str, wait_ms: int = 3000) -> bool:
        """Click an element containing the given text; return True on success."""
        try:
            locator = self.page.get_by_text(text, exact=False).first
            locator.click(timeout=5000)
            self.page.wait_for_timeout(wait_ms)
            try:
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return True
        except Exception:
            return False

    # ---- extraction --------------------------------------------------------

    def get_all_links(self) -> list[dict]:
        """All <a> tags as {href, text, abs_href}."""
        base = self.page.url
        links = self.page.eval_on_selector_all(
            "a[href]",
            """els => els.map(el => ({
                href: el.getAttribute('href'),
                text: (el.textContent || '').trim()
            }))""",
        )
        for link in links:
            link["abs_href"] = urljoin(base, link["href"])
        return links

    def get_buttons(self) -> list[dict]:
        """All <button> elements as {text, name, aria_label}."""
        return self.page.eval_on_selector_all(
            "button",
            """els => els.map(el => ({
                text: (el.textContent || '').trim(),
                name: el.getAttribute('name') || '',
                aria_label: el.getAttribute('aria-label') || '',
            }))""",
        )

    def get_download_links(self) -> list[str]:
        """
        Absolute URLs of all links that look like document downloads.
        Filters for known file extensions and download-related URL patterns.
        """
        file_exts = (
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".zip", ".rar", ".7z", ".txt", ".odt", ".ods", ".csv", ".xml",
        )
        download_patterns = (
            "download", "Download", "DownloadDocument",
            "DownloadTenderDocuments", "zipDownloadButton",
        )
        links = self.get_all_links()
        results = []
        for link in links:
            href = link["abs_href"]
            href_lower = href.lower()
            if any(href_lower.endswith(ext) for ext in file_exts):
                results.append(href)
            elif any(pat in href for pat in download_patterns):
                results.append(href)
        return list(dict.fromkeys(results))  # dedupe preserving order

    def find_zip_or_download_all(self) -> str | None:
        """
        Look for a 'download all' / ZIP link on the current page.
        Returns the URL if found, None otherwise.
        """
        zip_texts = [
            "alle herunterladen", "alle dokumente", "alle als zip",
            "alles herunterladen", "download all", "download zip",
            "zip herunterladen", "unterlagen herunterladen",
            "alle unterlagen", "gesamtpaket",
        ]
        links = self.get_all_links()

        # Check href for .zip or download-all keywords
        for link in links:
            if link["abs_href"].lower().endswith(".zip"):
                return link["abs_href"]
            href_lower = link["href"].lower()
            if any(kw in href_lower for kw in
                   ["downloadall", "alleherunterladen", "alle-dokumente", "zipdownloadbutton"]):
                return link["abs_href"]

        # Check link text
        for link in links:
            text_lower = link["text"].lower()
            if any(kw in text_lower for kw in zip_texts):
                return link["abs_href"]

        return None
