import os
from pydantic import BaseModel, Field
from typing import List, Optional

# In a published library setup: pip install open-scraper-sdk
# And import like: from open_scraper_sdk import OpenScraperClient
from open_scraper_sdk import OpenScraperClient

# 1. Define the custom extraction schema.
# Consumers have complete control over what structures they want!
class ExampleWebSchema(BaseModel):
    title: str = Field(description="The main title or heading of the page")
    description: Optional[str] = Field(description="A brief description or overview text from the page")
    links: List[str] = Field(default_factory=list, description="All outbound links found in the main content section")


def run_demo():
    # 2. Configure the client using credentials
    # Read from environment or pass explicitly
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if not gemini_key:
        print("💡 GEMINI_API_KEY environment variable not set.")
        print("💡 To run this code locally, please set your GEMINI_API_KEY:")
        print("   export GEMINI_API_KEY=\"your_key_here\"")
        print("   python examples/demo.py\n")
        gemini_key = "YOUR_GEMINI_API_KEY"

    print("--- Initializing OpenScraperClient ---")
    client = OpenScraperClient(gemini_api_key=gemini_key)

    # 3. Perform advanced structured web scraping
    # This will fetch the page, generate scraping code, validate, run inside sandbox,
    # capture tracebacks, self-correct if required, and return type-safe results.
    target_url = "https://example.com"
    
    try:
        print(f"Scraping and structuring contents of: {target_url}...")
        result = client.scrape_and_extract(
            url=target_url,
            schema=ExampleWebSchema,
            additional_prompt="Identify the main header and any explanatory links.",
            max_iterations=3  # Sandbox self-correction retry budget
        )
        
        print("\n🎉 Structured Scrape and Validation Successful!")
        print(f"Extracted Class: {type(result).__name__}")
        print(f"Data:\n{result.model_dump_json(indent=2)}")
        
    except Exception as e:
        print(f"\n❌ Pipeline execution finished (expected if API key is invalid):")
        print(f"Details: {e}")


if __name__ == "__main__":
    # Add src/ to sys.path so we can import open_scraper_sdk during local testing
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    run_demo()
