from pathlib import Path
import unittest

from tender_agent.browser import TenderBrowserCrawler


class BrowserCrawlerTests(unittest.TestCase):
    def test_follows_german_detail_pages(self) -> None:
        crawler = TenderBrowserCrawler(output_root=Path("."))

        self.assertTrue(
            crawler._should_follow_link(
                text="Bekanntmachung und Details",
                url="https://example.com/verfahren/12345",
                rel="",
                css_class="",
            )
        )

    def test_follows_german_document_sections(self) -> None:
        crawler = TenderBrowserCrawler(output_root=Path("."))

        self.assertTrue(
            crawler._should_follow_link(
                text="Vergabeunterlagen",
                url="https://example.com/tender",
                rel="",
                css_class="",
            )
        )


if __name__ == "__main__":
    unittest.main()
