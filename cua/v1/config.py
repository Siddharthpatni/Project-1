import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MAX_CONCURRENT_TASKS = 20
DOWNLOAD_DIR = "downloads"
TIMEOUT = 15000