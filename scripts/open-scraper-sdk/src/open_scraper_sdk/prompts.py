"""
Prompt templates for generic Python scraper generation.
"""
from textwrap import dedent

SYSTEM_PROMPT = dedent("""
    You are an expert web scraping and software engineering assistant.
    Your task: write a Python function `scrape(url: str, output_dir: str) -> dict` that scrapes data from a webpage.
    The function MUST actively navigate, click, or paginate if necessary using Playwright, or directly fetch using requests.
    
    ## SCAPE FUNCTION SIGNATURE
    - Signature: `def scrape(url: str, output_dir: str) -> dict`
    - Returns a JSON-serializable dictionary. This dictionary should contain:
      * Extracted structured keys matching the target fields requested by the user.
      * Or if assets are downloaded, a `"downloaded_files"` list containing the saved absolute paths.

    ## TECHNICAL CONSTRAINTS
    1. Use `from playwright.sync_api import sync_playwright` for JavaScript/SPAs.
       Always run Playwright headless and with standard desktop context:
       ```python
       ctx = browser.new_context(
           accept_downloads=True,
           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
       )
       ```
    2. For static pages, prefer standard `requests` and `BeautifulSoup` (bs4) for speed and simplicity.
    3. Do NOT import or use forbidden functions/packages:
       * NEVER use: `os.system`, `subprocess`, `eval`, `exec`, `socket`, `ctypes`, `multiprocessing`, `__import__`.
    4. Save any files or downloads inside the `output_dir` directory. Detect extensions correctly.
    5. Handle network errors and wrap the main execution body in try/except blocks so minor site failures do not crash the script.
    6. Return ONLY the code in a ```python``` fenced block. Do not write introductory or concluding explanations.
""").strip()

GENERATION_USER_PROMPT = dedent("""
    Target URL: {url}
    Detected Domain: {domain}
    
    Target Extraction Schema (JSON Schema):
    ```json
    {schema_json}
    ```
    
    Page HTML Snippet (for structural guidance):
    ```html
    {html_snippet}
    ```
    
    Extraction Guidelines / Prompt:
    {additional_prompt}

    Your task:
    Write the Python scraper to extract data matching the Target Extraction Schema. 
    If Playwright is needed to render JavaScript, click buttons, or open tabs, do so.
    Return the result dict containing the extracted keys conforming to the target schema.
    
    Generate the `scraper.py` script now.
""").strip()

FEEDBACK_PROMPT = dedent("""
    Your previous scraper script execution failed or produced incorrect data.
    Please fix the script based on the following execution diagnostic:

    URL: {url}
    Iteration: {iteration} of {max_iterations}

    Execution Outcome: {outcome}
    Error / Traceback:
    ```
    {error}
    ```

    Previous Extracted Data / Downloads Count: {downloaded}

    Correct the code. Rules:
    - Maintain the function signature `scrape(url: str, output_dir: str) -> dict`.
    - Fix the exceptions, missing elements, or runtime errors shown in the trace.
    - Return ONLY corrected Python code in a ```python``` fenced block.
""").strip()


def build_generation_prompt(
    url: str,
    domain: str,
    schema_json: str,
    html_snippet: str,
    additional_prompt: str = ""
) -> str:
    return GENERATION_USER_PROMPT.format(
        url=url,
        domain=domain,
        schema_json=schema_json,
        html_snippet=html_snippet[:15_000],
        additional_prompt=additional_prompt or "Extract all requested fields clearly."
    )


def build_feedback_prompt(
    iteration: int,
    max_iterations: int,
    url: str,
    outcome: str,
    error: str,
    downloaded: int,
) -> str:
    return FEEDBACK_PROMPT.format(
        iteration=iteration,
        max_iterations=max_iterations,
        url=url,
        outcome=outcome,
        error=error[:2000],
        downloaded=downloaded,
    )
