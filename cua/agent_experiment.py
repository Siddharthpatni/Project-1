import os
import asyncio
import logging
from dotenv import load_dotenv
from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use import Agent, Browser

load_dotenv()

# Set up simple logging to see what the agent is thinking
logging.basicConfig(level=logging.INFO)

# Load environment variables (like OPENROUTER_API_KEY)
load_dotenv()

# We configure OpenRouter to use entirely FREE models for the Computer Use Agent.
# Good free options on OpenRouter include:
# - google/gemini-2.5-flash-lite
# - meta-llama/llama-3-8b-instruct:free
# - qwen/qwen-2.5-72b-instruct
llm = ChatOpenRouter(
    model="google/gemini-2.5-flash-lite", 
)

# Configure the browser to be fully visible (headless=False)
# This allows you to visually watch the Agent move the mouse, click buttons, and read the page!
downloads_path = os.path.join(os.getcwd(), "downloads")
os.makedirs(downloads_path, exist_ok=True)
browser = Browser(headless=False, downloads_path=downloads_path)

async def main():
    # Example target tender URL (ensure this is currently active or pick one from your CSV)
    # This is a sample evergabe.de link; replace with a fresh one when testing.
    target_url = "https://www.evergabe.de/unterlagen/54321-Tender-19cdd4f196f-55ed433e45a54a4a" 
    
    task_instructions = f"""
    1. Navigate to the procurement portal at: {target_url}
    2. If a cookie consent banner appears, click the button to Accept or Agree to cookies.
    3. Look for the section on the page containing "Vergabeunterlagen" or "Dokumente" (Tender Documents).
    4. Click the appropriate buttons or links to download the ZIP or PDF files available on that page.
    5. Once the download initiates, you have completed the task.
    """
    
    agent = Agent(
        task=task_instructions,
        llm=llm,
        browser=browser
    )
    
    print("=======================================================================")
    print("🤖 Starting the Browser-Use Computer Agent with a FREE Model...")
    print("=======================================================================")
    
    # The agent will now autonomously reason, plan, and execute browser actions!
    result = await agent.run()
    
    print("=======================================================================")
    print("✅ Agent Execution Finished!")
    print("Final Result Memory:")
    print(result)
    await browser.stop()

if __name__ == "__main__":
    # Ensure OPENROUTER_API_KEY is present in the environment before running
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: Please 'export OPENROUTER_API_KEY=\"your_key\"' in the terminal first.")
        exit(1)
        
    asyncio.run(main())
