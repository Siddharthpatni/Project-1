import re
from typing import Optional
import requests

class BaseScraper:
    """Abstract base class for scraping engines."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def fetch(self, url: str) -> str:
        raise NotImplementedError("Scrapers must implement the fetch method.")


class SimpleScraper(BaseScraper):
    """
    A simple web scraping implementation.
    
    Demonstrates how to use a standard HTTP client, but is easily configurable
    to route requests through premium scraping proxies (like ScraperAPI or ScrapingBee)
    or standard scraping pipelines if the user provides an API key.
    """
    
    def __init__(self, api_key: Optional[str] = None, provider: str = "simple"):
        super().__init__(api_key)
        self.provider = provider

    def fetch(self, url: str) -> str:
        # Scenario A: User configured a paid scraping proxy service
        if self.provider == "scraperapi" and self.api_key:
            proxy_url = f"http://api.scraperapi.com?api_key={self.api_key}&url={url}"
            response = requests.get(proxy_url, timeout=30)
            response.raise_for_status()
            return self._clean_html(response.text)
            
        elif self.provider == "firecrawl" and self.api_key:
            # Concept for Firecrawl: converts page directly to clean markdown
            firecrawl_url = "https://api.firecrawl.dev/v0/scrape"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload = {"url": url, "pageOptions": {"onlyMainContent": True}}
            response = requests.post(firecrawl_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get("data", {}).get("markdown", "")

        # Scenario B: Default fallback (direct HTTP requests)
        else:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return self._clean_html(response.text)

    def _clean_html(self, html: str) -> str:
        """
        Extract readable text from standard HTML content.
        Removes scripts, styles, and redundant tags to save token usage in LLMs.
        """
        # Remove script and style tags
        text = re.sub(r'<(script|style|header|footer|nav)[^>]*>([\s\S]*?)</\1>', ' ', html)
        # Strip other HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Condense multiple whitespaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text
