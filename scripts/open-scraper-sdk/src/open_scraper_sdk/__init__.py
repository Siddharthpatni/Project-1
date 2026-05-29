"""
Open Scraper SDK
A reusable, extensible library for web scraping and LLM-based structured data extraction.
"""

from open_scraper_sdk.client import OpenScraperClient
from open_scraper_sdk.scraper import BaseScraper, SimpleScraper
from open_scraper_sdk.llm import LLMProcessor

__all__ = ["OpenScraperClient", "BaseScraper", "SimpleScraper", "LLMProcessor"]
