import aiofiles
import os

async def save_file(content, path):
    async with aiofiles.open(path, "wb") as f:
        await f.write(content)