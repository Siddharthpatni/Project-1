import csv
import sys
from urllib.parse import urlparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Domains confirmed login-gated — skip
SKIP = {
    "www.ausschreibungen.ls.brandenburg.de",
    "www.vergabe.stadt-frankfurt.de",   # same NetServer portal, same login wall
    "bieterportal.noncd.db.de",
    "vergabeplattform.charite.de",
}

# Already benchmarked — prefer NEW domains
ALREADY = {
    "www.dtvp.de",
    "www.evergabe.de",
    "www.vergabe.metropoleruhr.de",
    "www.ausschreibungen.ls.brandenburg.de",
    "www.vergabe.stadt-frankfurt.de",
}

seen = {}
selected = []

with open(r"C:\Users\Victus\Downloads\publications_updated.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        url    = (row.get("url") or "").strip()
        state  = (row.get("state") or "").strip().upper()
        domain = urlparse(url).netloc
        if not url or not domain:
            continue
        if state == "UNSUPPORTED":
            continue
        if domain in SKIP:
            continue
        if domain in seen:
            continue
        seen[domain] = True
        tag = "[NEW]" if domain not in ALREADY else "[DUP]"
        selected.append({
            "id": row.get("id", ""),
            "url": url,
            "domain": domain,
            "state": state,
            "tag": tag,
        })
        if len(selected) >= 30:
            break

print(f"{'#':>3}  {'State':12} {'Tag':5}  {'Domain':<44}  URL")
print("-" * 120)
for i, r in enumerate(selected, 1):
    print(f"{i:>3}  {r['state']:12} {r['tag']:5}  {r['domain']:<44}  {r['url'][:70]}")

print(f"\nShowing {len(selected)} unique domains from CSV.")
print("\nTop 5 recommended (NEW domains only):")
new_only = [r for r in selected if r["tag"] == "[NEW]"][:5]
for r in new_only:
    print(f"  {r['url']}")
