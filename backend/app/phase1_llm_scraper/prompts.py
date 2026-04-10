"""
Prompt templates for Phase-1 scraper generation.

Centralizing prompts here makes A/B testing different prompting strategies
trivial: swap the template, rerun the benchmark harness.
"""
from textwrap import dedent

SYSTEM_PROMPT = dedent("""
    You are an expert Python web-scraping engineer. Your job is to generate
    a single self-contained Python script that downloads all tender
    documents (PDFs, DOCX, ZIPs, XML attachments) linked from a public
    procurement website.

    Hard requirements:
    1. The script must define `def scrape(url: str, output_dir: str) -> list[str]`
       that returns the list of file paths it successfully downloaded.
    2. Use `playwright.sync_api` for browser automation. Assume Chromium is
       installed. Run headless.
    3. Never call `os.system`, `subprocess`, `eval`, `exec`, or open network
       sockets directly. Only HTTP(S) traffic via Playwright or `requests`.
    4. Respect a 60-second total wall-clock budget.
    5. Do not write to any path outside `output_dir`.
    6. Return ONLY the Python code inside a ```python``` fenced block. No prose.
""").strip()


GENERATION_USER_PROMPT = dedent("""
    Target URL: {url}
    Detected domain: {domain}

    Page structure (first 4000 chars of rendered HTML):
    ```html
    {html_snippet}
    ```

    Previously tried selectors that failed (if any):
    {failed_selectors}

    Generate the scraper now.
""").strip()


FEEDBACK_PROMPT = dedent("""
    Your previous scraper attempt failed. Here is the diagnostic information:

    Iteration: {iteration} of {max_iterations}
    URL: {url}

    Execution outcome: {outcome}
    Error message / stderr:
    ```
    {error}
    ```

    Documents expected (approx): {expected_docs}
    Documents actually downloaded: {downloaded}

    Fix the code. Key rules:
    - Keep the `scrape(url, output_dir)` signature unchanged.
    - If the site uses JavaScript to reveal document links, wait for the
      relevant network idle / DOM selector before extracting.
    - If downloads happen via POST, use `page.expect_download()` and save
      via `download.save_as()`.
    - Return ONLY the corrected Python code in a fenced block.
""").strip()


def build_generation_prompt(
    url: str,
    domain: str,
    html_snippet: str,
    failed_selectors: list[str] | None = None,
) -> str:
    return GENERATION_USER_PROMPT.format(
        url=url,
        domain=domain,
        html_snippet=html_snippet[:4000],
        failed_selectors=", ".join(failed_selectors or []) or "none",
    )


def build_feedback_prompt(
    iteration: int,
    max_iterations: int,
    url: str,
    outcome: str,
    error: str,
    expected_docs: int,
    downloaded: int,
) -> str:
    return FEEDBACK_PROMPT.format(
        iteration=iteration,
        max_iterations=max_iterations,
        url=url,
        outcome=outcome,
        error=error[:2000],
        expected_docs=expected_docs,
        downloaded=downloaded,
    )
