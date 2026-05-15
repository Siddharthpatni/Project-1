import httpx, asyncio, re

async def fetch():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(
            "https://www.evergabe-online.de/tenderdocuments.html?id=846552",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}
        )
        text = r.text
        base = "https://www.evergabe-online.de/"

        # ZIP download link
        zip_match = re.search(r'href="(./tenderdocuments\.html\?[^"]*zipDownloadButton[^"]*)"', text)
        if zip_match:
            print("ZIP URL:", base + zip_match.group(1).replace("./", ""))

        # Individual download links
        doc_links = re.findall(
            r'href="(./tenderdocuments\.html\?[^"]*cookieCheck[^"]*)"[^>]*title="[^"]*herunterladen"',
            text
        )
        print(f"Individual download links found: {len(doc_links)}")
        for link in doc_links[:5]:
            print("  ", base + link.replace("./", ""))

        # Filenames
        filenames = re.findall(r'title="([^"]+\.(pdf|docx|zip|xlsx|xls|xml))"', text, re.IGNORECASE)
        print(f"Filenames: {[f[0] for f in filenames[:10]]}")

asyncio.run(fetch())
