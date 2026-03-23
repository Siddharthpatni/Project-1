"""
XPath Inspector - Quick DOM analysis for new procurement domains.
Run this on a sample URL to discover the page structure and find XPath selectors.

Usage:
  python inspect_page.py <url>
  python inspect_page.py https://www.evergabe-online.de/tenderdetails.html?id=xxx
"""

import asyncio
import sys
import json
from playwright.async_api import async_playwright


async def inspect_url(url: str):
    """Analyze a procurement page and suggest XPath selectors."""
    print(f"\n{'='*70}")
    print(f"  INSPECTING: {url}")
    print(f"{'='*70}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="de-DE",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[ERROR] Could not load page: {e}")
            await browser.close()
            return

        # 1. Page title
        title = await page.title()
        print(f"[Page Title] {title}\n")

        # 2. All headings
        print("[Headings]")
        for tag in ["h1", "h2", "h3"]:
            elements = await page.locator(tag).all()
            for el in elements[:3]:
                text = (await el.inner_text()).strip()
                if text:
                    print(f"  <{tag}> {text[:100]}")
        print()

        # 3. Key-value pairs from tables
        print("[Table Key-Value Pairs]")
        rows = await page.locator("tr").all()
        for row in rows[:30]:
            cells = await row.locator("td, th").all()
            if len(cells) >= 2:
                label = (await cells[0].inner_text()).strip()
                value = (await cells[1].inner_text()).strip()
                if label and value and len(label) < 80:
                    print(f"  {label:40s} → {value[:80]}")
        print()

        # 4. Definition lists (dt/dd)
        print("[Definition Lists (dt/dd)]")
        dts = await page.locator("dt").all()
        for dt in dts[:20]:
            label = (await dt.inner_text()).strip()
            dd_text = await dt.evaluate(
                "el => el.nextElementSibling?.textContent?.trim() || ''"
            )
            if label:
                print(f"  {label:40s} → {dd_text[:80]}")
        print()

        # 5. Label/value div patterns
        print("[Labeled Divs - common patterns]")
        # Look for spans/divs with label-like classes
        label_patterns = await page.evaluate("""
            () => {
                const results = [];
                const labels = document.querySelectorAll(
                    '.label, .field-label, [class*="label"], [class*="key"], [class*="header"]'
                );
                labels.forEach(el => {
                    const text = el.textContent.trim();
                    const next = el.nextElementSibling?.textContent?.trim() || '';
                    if (text && text.length < 80) {
                        results.push({ label: text.substring(0, 60), value: next.substring(0, 80) });
                    }
                });
                return results.slice(0, 20);
            }
        """)
        for item in label_patterns:
            print(f"  {item['label']:40s} → {item['value']}")
        print()

        # 6. German procurement keywords found on page
        print("[German Procurement Keywords Found]")
        keywords = [
            "Auftraggeber", "Vergabestelle", "Vergabenummer", "Aktenzeichen",
            "Verfahrensart", "Angebotsfrist", "Teilnahmefrist", "Veröffentlichung",
            "Bekanntmachung", "CPV", "Erfüllungsort", "Beschreibung",
            "Leistung", "Kontakt", "Frist", "Datum", "Vergabeart",
            "Auftragsgegenstand", "Losvergabe", "NUTS",
        ]
        body_text = await page.inner_text("body")
        found = [kw for kw in keywords if kw.lower() in body_text.lower()]
        print(f"  Found: {', '.join(found)}")
        print()

        # 7. Suggest XPaths for found keywords
        print("[Suggested XPaths]")
        for kw in found:
            # Find elements containing this keyword
            results = await page.evaluate(f"""
                (keyword) => {{
                    const results = [];
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_ELEMENT
                    );
                    while (walker.nextNode()) {{
                        const el = walker.currentNode;
                        if (el.childNodes.length <= 3 && 
                            el.textContent.trim().includes(keyword) &&
                            el.textContent.trim().length < 100) {{
                            const tag = el.tagName.toLowerCase();
                            const cls = el.className ? '.' + el.className.split(' ')[0] : '';
                            const next = el.nextElementSibling;
                            const nextText = next?.textContent?.trim()?.substring(0, 60) || '';
                            results.push({{
                                tag: tag,
                                cls: cls,
                                text: el.textContent.trim().substring(0, 60),
                                nextTag: next?.tagName?.toLowerCase() || '',
                                nextText: nextText,
                            }});
                        }}
                    }}
                    return results.slice(0, 3);
                }}
            """, kw)
            for r in results:
                print(f"  [{kw}]")
                print(f"    Element: <{r['tag']}{r['cls']}> \"{r['text']}\"")
                if r["nextText"]:
                    print(f"    Next sibling: <{r['nextTag']}> \"{r['nextText']}\"")
                    print(f"    XPath: //*[contains(text(),'{kw}')]/following-sibling::*[1]")
        print()

        # 8. Full page structure overview
        print("[Page Structure (top-level containers)]")
        structure = await page.evaluate("""
            () => {
                const results = [];
                const main = document.querySelector('main, #content, .content, #main, .main, article');
                const target = main || document.body;
                for (const child of target.children) {
                    const tag = child.tagName.toLowerCase();
                    const id = child.id ? `#${child.id}` : '';
                    const cls = child.className ? `.${child.className.split(' ').slice(0,2).join('.')}` : '';
                    const childCount = child.children.length;
                    results.push(`<${tag}${id}${cls}> (${childCount} children)`);
                }
                return results.slice(0, 15);
            }
        """)
        for s in structure:
            print(f"  {s}")

        await browser.close()

    print(f"\n{'='*70}")
    print("  Use these findings to update DOMAIN_CONFIGS in scraper.py")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_page.py <url>")
        sys.exit(1)
    asyncio.run(inspect_url(sys.argv[1]))
