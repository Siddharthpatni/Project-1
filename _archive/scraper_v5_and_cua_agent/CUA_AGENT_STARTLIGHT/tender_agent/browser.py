from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from tender_agent.models import BrowserSession, DocumentCandidate
from tender_agent.utils import (
    DETAIL_PAGE_KEYWORDS,
    PAGINATION_KEYWORDS,
    SECTION_KEYWORDS,
    extract_extension,
    guess_name_from_url,
    is_probably_document_url,
    is_same_site,
    looks_like_detail_page_text,
    looks_like_document_text,
    normalize_url,
    normalize_whitespace,
    slugify,
)

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - handled at runtime
    PlaywrightTimeoutError = Exception
    async_playwright = None


class TenderBrowserCrawler:
    def __init__(
        self,
        output_root: Path,
        max_pages: int = 12,
        max_scrolls: int = 6,
        headless: bool = True,
        timeout_ms: int = 20000,
    ) -> None:
        self.output_root = output_root
        self.max_pages = max_pages
        self.max_scrolls = max_scrolls
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def discover_documents(
        self,
        start_url: str,
        screenshot_dir: Path | None = None,
    ) -> tuple[list[DocumentCandidate], list[Path], BrowserSession]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. Run `pip install -r requirements.txt` "
                "and `python -m playwright install chromium` first."
            )

        site_slug = slugify(start_url)
        screenshot_dir = screenshot_dir or (self.output_root / "screenshots" / site_slug)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        visited_pages: set[str] = set()
        queued_pages: set[str] = {normalize_url(start_url)}
        page_queue: deque[str] = deque([start_url])
        documents: list[DocumentCandidate] = []
        screenshots: list[Path] = []
        browser_session = BrowserSession()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context(accept_downloads=False)
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)

            while page_queue and len(visited_pages) < self.max_pages:
                current_url = page_queue.popleft()
                normalized_url = normalize_url(current_url)
                if normalized_url in visited_pages:
                    continue

                await self._load_page(page, current_url)
                await self._scroll_page(page)
                await self._expand_document_sections(page)

                screenshot_path = screenshot_dir / f"{len(visited_pages) + 1:02d}.png"
                captured_path = await self._capture_screenshot(page, screenshot_path)
                if captured_path is not None:
                    screenshots.append(captured_path)

                extracted_documents, next_pages = await self._extract_links(
                    page=page,
                    base_url=start_url,
                    source_page=current_url,
                )
                documents.extend(extracted_documents)
                visited_pages.add(normalized_url)

                for next_page in next_pages:
                    normalized_next_page = normalize_url(next_page)
                    if normalized_next_page in visited_pages or normalized_next_page in queued_pages:
                        continue
                    queued_pages.add(normalized_next_page)
                    page_queue.append(next_page)

            browser_session = await self._build_browser_session(context, page)
            await context.close()
            await browser.close()

        deduped_documents: list[DocumentCandidate] = []
        seen_document_urls: set[str] = set()
        for document in documents:
            canonical_url = normalize_url(document.url)
            if canonical_url in seen_document_urls:
                continue
            seen_document_urls.add(canonical_url)
            deduped_documents.append(document)

        return deduped_documents, screenshots, browser_session

    async def _load_page(self, page, url: str) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except PlaywrightTimeoutError:
            await page.goto(url, wait_until="load", timeout=self.timeout_ms)

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            return

    async def _build_browser_session(self, context, page) -> BrowserSession:
        try:
            cookies = await context.cookies()
        except Exception:
            cookies = []

        cookie_header = "; ".join(
            f"{item['name']}={item['value']}"
            for item in cookies
            if item.get("name") and item.get("value") is not None
        )

        try:
            user_agent = await page.evaluate("() => navigator.userAgent")
        except Exception:
            user_agent = ""

        return BrowserSession(
            user_agent=user_agent,
            cookie_header=cookie_header,
        )

    async def _capture_screenshot(self, page, screenshot_path: Path) -> Path | None:
        try:
            await page.screenshot(
                path=str(screenshot_path),
                full_page=True,
                animations="disabled",
                timeout=max(self.timeout_ms, 60000),
            )
            return screenshot_path
        except Exception:
            fallback_path = screenshot_path.with_name(
                f"{screenshot_path.stem}_viewport{screenshot_path.suffix}"
            )
            try:
                await page.screenshot(
                    path=str(fallback_path),
                    full_page=False,
                    animations="disabled",
                    timeout=10000,
                )
                return fallback_path
            except Exception:
                return None

    async def _scroll_page(self, page) -> None:
        for _ in range(self.max_scrolls):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(300)

    async def _expand_document_sections(self, page) -> None:
        locator = page.locator(
            "button, [role='tab'], [role='button'], [aria-controls], summary, "
            "a[role='tab'], a[href^='#'], a[data-toggle], a[data-bs-toggle]"
        )
        try:
            count = min(await locator.count(), 150)
        except Exception:
            return

        for index in range(count):
            element = locator.nth(index)
            try:
                text = normalize_whitespace(await element.inner_text(timeout=500)).lower()
            except Exception:
                continue

            if not text or len(text) > 80:
                continue

            if not any(keyword in text for keyword in SECTION_KEYWORDS | PAGINATION_KEYWORDS):
                continue

            try:
                await element.scroll_into_view_if_needed(timeout=1000)
                await element.click(timeout=1500)
                await page.wait_for_timeout(400)
            except Exception:
                continue

    async def _extract_links(
        self,
        page,
        base_url: str,
        source_page: str,
    ) -> tuple[list[DocumentCandidate], list[str]]:
        page_like_extensions = {".html", ".htm", ".php", ".aspx", ".jsp"}
        raw_links = await page.evaluate(
            r"""
            () => {
              const rows = [];
              const seen = new Set();
              const documentHint = new RegExp("(download|attachment|file=|docid=|documents?|dokumente?|unterlagen?|bekanntmachung|vergabeunterlagen|teilnahmeunterlagen|leistungsverzeichnis)", "i");
              const extensionHint = new RegExp("\\\\.(pdf|docx?|xlsx?|xlsm|csv|zip|rar|7z|dwg|dxf|odt|ods|rtf|txt|pptx?)($|[?#])", "i");

              const normalizeClassName = (el) => {
                if (!el) return "";
                if (typeof el.className === "string") return el.className;
                return el.getAttribute("class") || "";
              };

              const readText = (el) => {
                if (!el) return "";
                return (
                  el.innerText ||
                  el.textContent ||
                  el.getAttribute("aria-label") ||
                  el.getAttribute("title") ||
                  ""
                ).trim();
              };

              const absolutize = (value) => {
                if (!value) return "";
                try {
                  return new URL(value, document.baseURI).href;
                } catch {
                  return "";
                }
              };

              const normalizeCandidateUrl = (value) => {
                if (!value) return "";
                const trimmed = String(value).trim();
                if (!trimmed || trimmed === "#" || new RegExp("^javascript:", "i").test(trimmed)) return "";
                return absolutize(trimmed) || trimmed;
              };

              const extractUrlsFromScript = (value) => {
                const matches = new Set();
                if (!value) return [];

                const text = String(value);
                for (const match of text.matchAll(new RegExp("https?://[^\\\\s\"'`<>]+", "gi"))) {
                  if (match[0]) matches.add(match[0]);
                }

                for (const match of text.matchAll(new RegExp("['\"`]([^'\"`]+)['\"`]", "g"))) {
                  const candidate = (match[1] || "").trim();
                  if (!candidate) continue;
                  if (new RegExp("^(https?://|/|\\\\./|\\\\.\\\\./)", "i").test(candidate)) {
                    matches.add(candidate);
                    continue;
                  }
                  if (documentHint.test(candidate) || extensionHint.test(candidate)) {
                    matches.add(candidate);
                  }
                }

                return Array.from(matches);
              };

              const pushRow = (url, text, tag, rel, cssClass, sourceAttr) => {
                const normalizedUrl = normalizeCandidateUrl(url);
                if (!normalizedUrl) return;
                const key = `${normalizedUrl}||${tag || ""}||${sourceAttr || ""}`;
                if (seen.has(key)) return;
                seen.add(key);
                rows.push({
                  url: normalizedUrl,
                  text: (text || "").trim(),
                  tag: tag || "",
                  rel: rel || "",
                  cssClass: cssClass || "",
                  sourceAttr: sourceAttr || ""
                });
              };

              document.querySelectorAll("a[href]").forEach((el) => {
                pushRow(
                  el.href,
                  readText(el),
                  "a",
                  el.getAttribute("rel") || "",
                  normalizeClassName(el),
                  "href"
                );
              });

              document.querySelectorAll("iframe[src], embed[src], object[data]").forEach((el) => {
                pushRow(
                  el.src || el.data,
                  readText(el),
                  el.tagName.toLowerCase(),
                  "",
                  normalizeClassName(el),
                  el.tagName.toLowerCase() === "object" ? "data" : "src"
                );
              });

              const attributeSelectors = [
                "data-href",
                "data-url",
                "data-download",
                "data-download-url",
                "data-file",
                "data-file-url",
                "data-src",
                "formaction",
                "action"
              ];

              document
                .querySelectorAll(
                  "[data-href], [data-url], [data-download], [data-download-url], " +
                  "[data-file], [data-file-url], [data-src], button[formaction], " +
                  "input[formaction], form[action]"
                )
                .forEach((el) => {
                  attributeSelectors.forEach((attr) => {
                    const value = el.getAttribute(attr);
                    if (!value) return;
                    pushRow(
                      value,
                      readText(el),
                      el.tagName.toLowerCase(),
                      el.getAttribute("rel") || "",
                      normalizeClassName(el),
                      attr
                    );
                  });
                });

              document.querySelectorAll("[onclick]").forEach((el) => {
                extractUrlsFromScript(el.getAttribute("onclick")).forEach((url) => {
                  pushRow(
                    url,
                    readText(el),
                    el.tagName.toLowerCase(),
                    el.getAttribute("rel") || "",
                    normalizeClassName(el),
                    "onclick"
                  );
                });
              });

              return rows;
            }
            """
        )

        documents: list[DocumentCandidate] = []
        next_pages: list[str] = []

        for row in raw_links:
            url = normalize_url(row["url"])
            text = normalize_whitespace(row["text"])
            rel = normalize_whitespace(row["rel"]).lower()
            css_class = normalize_whitespace(row["cssClass"]).lower()
            source_attr = normalize_whitespace(row.get("sourceAttr", "")).lower()
            extension = extract_extension(url)
            name = text or guess_name_from_url(url)
            link_hint = f"{text} {url} {css_class} {source_attr}".lower()
            url_looks_like_download = any(
                token in url.lower()
                for token in (
                    "/download",
                    "download=",
                    "attachment",
                    "file=",
                    "docid=",
                    "unterlage",
                    "unterlagen",
                    "dokument",
                    "bekanntmachung",
                )
            )
            is_direct_document = is_probably_document_url(url) or (
                looks_like_document_text(text)
                and (
                    extension and extension not in page_like_extensions
                    or url_looks_like_download
                )
            )

            if is_direct_document:
                documents.append(
                    DocumentCandidate(
                        name=name,
                        url=url,
                        source_page=source_page,
                        link_text=text,
                        extension=extension,
                        discovered_via=row["tag"],
                    )
                )
                continue

            if not is_same_site(base_url, url):
                continue

            if self._should_follow_link(text=text, url=url, rel=rel, css_class=css_class):
                next_pages.append(url)
                continue

            if any(keyword in link_hint for keyword in SECTION_KEYWORDS | PAGINATION_KEYWORDS):
                next_pages.append(url)

        return documents, next_pages

    def _should_follow_link(
        self,
        text: str,
        url: str,
        rel: str,
        css_class: str,
    ) -> bool:
        lower_text = text.lower()
        lower_url = url.lower()

        if rel == "next" or "pagination" in css_class:
            return True

        if any(keyword in lower_text for keyword in PAGINATION_KEYWORDS):
            return True

        if any(keyword in lower_text for keyword in SECTION_KEYWORDS):
            return True

        if looks_like_detail_page_text(lower_text):
            return True

        if any(keyword in lower_url for keyword in SECTION_KEYWORDS):
            return True

        if any(keyword in lower_url for keyword in DETAIL_PAGE_KEYWORDS):
            return True

        return bool(re.search(r"[?&]page=\d+", lower_url))
