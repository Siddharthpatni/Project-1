"""
www.vergabe24.de — NetServer publication portal (vergabe24 platform).
Delegates to the shared generic NetServer publication scraper.
URL pattern: /NetServer/PublicationControllerServlet?function=Detail&TWOID=...
"""
from data.scrapers.scraper__netserver_pub_generic import scrape  # noqa: F401
