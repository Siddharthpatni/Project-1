"""
browser_helper.py — Shared Playwright utilities for LLM-generated scrapers.

Provides a simple API for generated scraper functions that need browser
interaction (JS-rendered pages, clicking buttons, navigating multi-step flows).

Usage in generated scrapers:
    from browser_helper import BrowserSession

    with BrowserSession() as session:
        page = session.page
        page.goto(url)
        # click, wait, extract...
        html = page.content()
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from urllib.parse import urljoin


class BrowserSession:
    """
    Context manager that provides a Playwright page with sensible defaults.

    Usage:
        with BrowserSession() as session:
            session.goto("https://example.com")
            html = session.content()
            links = session.get_all_links()
    """

    def __init__(self, headless: bool = True, timeout: int = 20_000):
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

    # ---- convenience methods ------------------------------------------------

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """Navigate to URL and wait for page load."""
        self.page.goto(url, wait_until=wait_until, timeout=self._timeout)
        try:
            self.page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # best-effort
        self._dismiss_cookie_banners()

    def _dismiss_cookie_banners(self) -> None:
        """Remove common cookie consent overlays that block interaction."""
        try:
            # Usercentrics (used by evergabe.de and others)
            self.page.evaluate(
                'document.querySelector("#usercentrics-root")?.remove()'
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
        """Return current page HTML."""
        return self.page.content()

    def url(self) -> str:
        """Return current page URL."""
        return self.page.url

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        """Wait for a CSS selector to appear in the DOM."""
        self.page.wait_for_selector(selector, timeout=timeout or self._timeout)

    def click_and_wait(self, selector: str, wait_ms: int = 3000) -> bool:
        """
        Click an element and wait for navigation/network.
        Returns True if click succeeded, False otherwise.
        """
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
        """
        Click an element containing the given text.
        Returns True if click succeeded, False otherwise.
        """
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

    def get_all_links(self) -> list[dict]:
        """
        Return all <a> tags with href and text.
        Each item: {"href": "...", "text": "...", "abs_href": "..."}
        """
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

    def get_download_links(self) -> list[str]:
        """
        Return absolute URLs of all links that look like document downloads.
        Filters for known file extensions and download-related URL patterns.
        """
        file_exts = (
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".zip", ".rar", ".7z", ".txt", ".odt", ".ods", ".csv",
        )
        download_patterns = (
            "download", "Download", "DownloadDocument", "DownloadTenderDocuments",
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

        # Check href for .zip
        for link in links:
            if link["abs_href"].lower().endswith(".zip"):
                return link["abs_href"]
            href_lower = link["href"].lower()
            if any(kw in href_lower for kw in ["downloadall", "alleherunterladen", "alle-dokumente"]):
                return link["abs_href"]

        # Check link text
        for link in links:
            text_lower = link["text"].lower()
            if any(kw in text_lower for kw in zip_texts):
                return link["abs_href"]

        return None
