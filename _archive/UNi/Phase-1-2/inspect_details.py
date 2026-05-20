import httpx, asyncio, re

async def fetch():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(
            "https://www.evergabe-online.de/tenderdetails.html?id=846552",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}
        )
        text = r.text

    # Strip all tags and print the text content of the main body
    # to see what data is rendered
    body = text[text.find("<body"):]
    clean = re.sub(r"<script[^>]*>.*?</script>", " ", body, flags=re.DOTALL)
    clean = re.sub(r"<style[^>]*>.*?</style>", " ", clean, flags=re.DOTALL)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"&nbsp;", " ", clean)
    clean = re.sub(r"&amp;", "&", clean)
    clean = re.sub(r"&#[0-9]+;", "", clean)
    clean = re.sub(r"\s{2,}", "\n", clean).strip()

    # Print lines that contain actual content (not empty/noise)
    for line in clean.splitlines():
        line = line.strip()
        if len(line) > 5:
            print(line)

asyncio.run(fetch())
