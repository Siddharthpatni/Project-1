import os
from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use import Agent, Browser
from dotenv import load_dotenv

load_dotenv()
from config import OPENROUTER_API_KEY

llm = ChatOpenRouter(
    model="google/gemini-2.5-flash-lite",
)

browser = Browser(headless=False)

async def run_agent(url):
    task = f"""
    1. Open {url}
    2. Accept cookies if present
    3. Find section with documents (Vergabeunterlagen / Dokumente)
    4. Download any PDF or ZIP
    5. Finish after download starts
    """

    agent = Agent(task=task, llm=llm, browser=browser)

    try:
        result = await agent.run()
        return True
    except Exception as e:
        print(f"[AGENT FAIL] {url} → {e}")
        await browser.stop()
        return False