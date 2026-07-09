"""
Seed Script: Register V1 Manual Scraper in the Registry.

This script loads the v1_reference.py code into the ScraperTemplate table
for the supported domains.
"""

import os

# Import constants directly to avoid circular imports during seeding
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://vergabepilot:vergabepilot@localhost:5432/vergabepilot")

# Deliberately imported after DATABASE_URL is set (avoids circular imports
# during seeding) — hence the noqa.
from app.database import SessionLocal  # noqa: E402
from app.models import ScraperTemplate  # noqa: E402

DOMAINS = [
    "evergabe-online.de",
    "vergabe24.de",
    "tender24.de",
    "dtvp.de",
    "sachsen-vergabe.de",
    "vergabeportal-bw.de"
]

SCRAPER_PATH = os.path.join(os.path.dirname(__file__), "..", "phase0_manual", "v1_reference.py")

def seed():
    if not os.path.exists(SCRAPER_PATH):
        print(f"Error: Reference scraper not found at {SCRAPER_PATH}")
        return

    code = open(SCRAPER_PATH).read()
    db = SessionLocal()

    print(f"Seeding {len(DOMAINS)} domains with V1 manual scraper baseline...")

    for domain in DOMAINS:
        existing = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()
        if existing:
            print(f"  - Updating {domain}")
            existing.code = code
            existing.source = "manual"
        else:
            print(f"  - Creating {domain}")
            tpl = ScraperTemplate(
                domain=domain,
                code=code,
                source="manual",
                success_count=100, # Start with high confidence for the manual script
            )
            db.add(tpl)

    db.commit()
    db.close()
    print("Done!")

if __name__ == "__main__":
    seed()
