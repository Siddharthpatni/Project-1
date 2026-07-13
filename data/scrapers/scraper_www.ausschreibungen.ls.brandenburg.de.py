"""
www.ausschreibungen.ls.brandenburg.de — delegates to the shared NetServer publication scraper.
Handles PublicationControllerServlet pages with public document downloads.
"""
from data.scrapers.scraper__netserver_pub_generic import scrape  # noqa: F401
