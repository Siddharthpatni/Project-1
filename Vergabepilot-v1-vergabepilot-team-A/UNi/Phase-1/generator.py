#!/usr/bin/env python3
"""
Phase-1 : LLM Scraper Generator  (Standalone)
================================================

What does this script do?
-------------------------
It takes a URL of a public procurement / tender website and asks an LLM
(via OpenRouter) to write a Python scraper that does TWO things:
  1. Scrape structured data (tender titles, deadlines, descriptions, etc.)
  2. Download all attached documents (PDFs, DOCX, ZIPs, XML, etc.)

Think of it as:  URL  →  LLM  →  ready-to-run scraper code (.py file)

Two modes of operation
----------------------
1. `generate`   – Give it a URL, it fetches the page HTML, sends it to
                   the LLM along with our carefully crafted prompt, and
                   saves the resulting scraper code to a file.

2. `regenerate` – When the first attempt didn't work (the scraper
                   crashed, downloaded 0 files, etc.), someone from the
                   team feeds the error back in, and the LLM gets a
                   second (or third …) chance to fix its code.

Quick start
-----------
    # 1. Put your API key in a .env file next to this script:
    #    OPENROUTER_API_KEY=sk-or-...
    #
    # 2. Run:
    python generator.py generate "https://example.com/tenders"
    python generator.py generate "https://example.com/tenders" --model "openai/gpt-4o"

    # 3. The scraper code lands in ./generated_scrapers/scraper_<domain>.py

Needed
------
- Python 3.10+
- pip install httpx
- A valid OPENROUTER_API_KEY (free-tier models work too)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from urllib.parse import urlparse

import httpx  # The only external dependency — used for HTTP requests


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 0 :  Configuration
# ═══════════════════════════════════════════════════════════════════════════════
# We read settings from environment variables.  If a .env file exists in
# the same folder as this script (or in the current working directory),
# we load it automatically — no extra library required.
# ═══════════════════════════════════════════════════════════════════════════════

def _load_dotenv():
    """
    Dead-simple .env file reader.

    Looks for a file called `.env` next to this script or in the current
    working directory.  Each line should look like:

        OPENROUTER_API_KEY=sk-or-v1-abc123
        LLM_MODEL=openai/gpt-4o

    Lines starting with '#' are ignored (comments).
    We only set a variable if it isn't already set in the real environment,
    so real env vars always win.
    """
    possible_locations = [
        Path(__file__).parent / ".env",   # same folder as generator.py
        Path.cwd() / ".env",             # wherever you ran the command from
    ]
    for env_file in possible_locations:
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")  # remove surrounding quotes
                os.environ.setdefault(key, value)
            break  # stop after the first .env file found


# Load .env right away so the constants below can read from it
_load_dotenv()

# --- The three things you might want to change ---
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")        # required!
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL",           # almost never needs changing
                                "https://openrouter.ai/api/v1").rstrip("/")
LLM_MODEL           = os.getenv("LLM_MODEL",                     # which model to use
                                "google/gemini-2.5-flash-lite")
LOG_LEVEL           = os.getenv("LOG_LEVEL", "INFO").upper()

# Set up logging so we can see what's happening
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
log = logging.getLogger("phase1.generator")


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 1 :  Prompt Templates
# ═══════════════════════════════════════════════════════════════════════════════
# These are the instructions we send to the LLM.  Getting these right is
# the single most important thing in this file — they control the quality
# of the generated scrapers.
#
# There are three prompts:
#
#   SYSTEM_PROMPT             – "Who you are and what the rules are."
#                                Sent with every request.
#
#   GENERATION_USER_PROMPT    – "Here's the page, write the scraper."
#                                Used on the first attempt.
#
#   FEEDBACK_PROMPT           – "Your code failed, here's why. Fix it."
#                                Used on retries (2nd, 3rd, … attempt).
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = dedent("""\
    You are an expert Python web-scraping engineer specializing in public
    procurement / tender portals. Your job is to generate a single
    self-contained Python script that does TWO things:

    A) SCRAPE structured data from the page:
       - Tender title / subject
       - Contracting authority (who published it)
       - Publication date and submission deadline
       - Tender reference / ID number
       - Short description or summary
       - Category or CPV codes (if visible)
       - Direct URL to the tender detail page
       - Any other clearly visible metadata

    B) DOWNLOAD all attached documents:
       - PDFs, DOCX, ZIPs, XML, XLS/XLSX, or any other linked files
       - Save each file into `output_dir` with its original filename
       - If filenames are not available, use a meaningful name based on
         the tender ID or link text

    Hard requirements:
    1. The script must define:
       `def scrape(url: str, output_dir: str) -> dict`
       that returns a dictionary with two keys:
         - "tenders": a list of dicts, each containing the structured
           fields listed above (use None for fields not found on page)
         - "downloaded_files": a list of file paths successfully saved
       Example return value:
         {
           "tenders": [
             {"title": "Road construction project", "deadline": "2025-06-01", ...},
             ...
           ],
           "downloaded_files": ["/output/tender_123.pdf", ...]
         }
    2. Use `playwright.sync_api` for browser automation. Assume Chromium
       is installed. Run headless.
    3. Never call `os.system`, `subprocess`, `eval`, `exec`, or open
       network sockets directly. Only HTTP(S) traffic via Playwright
       or `requests`.
    4. Respect a 60-second total wall-clock budget.
    5. Do not write to any path outside `output_dir`.
    6. Save the scraped tender data as `tenders.json` inside `output_dir`.
    7. Return ONLY the Python code inside a ```python``` fenced block.
       No prose, no explanations — just the code.
""")

# This is what we send the FIRST time we ask the LLM to write a scraper.
# We include the actual HTML of the target page so the LLM can see what
# elements (links, buttons, tables, download links) it needs to interact with.
GENERATION_USER_PROMPT = dedent("""\
    Target URL: {url}
    Detected domain: {domain}

    Page structure (first 4000 chars of rendered HTML):
    ```html
    {html_snippet}
    ```

    Previously tried selectors that failed (if any):
    {failed_selectors}

    Your tasks:
    1. SCRAPE all visible tender information (titles, deadlines, descriptions,
       reference numbers, contracting authority, links, etc.) into structured
       dicts.
    2. DOWNLOAD every linked document (PDF, DOCX, ZIP, XML, XLS, etc.)
       into output_dir.
    3. Save the structured data as tenders.json in output_dir.
    4. Return the dict with "tenders" and "downloaded_files" keys.

    Generate the scraper now.
""")

# This is what we send on RETRIES when the previous scraper didn't work.
# We tell the LLM exactly what went wrong so it can fix its approach.
FEEDBACK_PROMPT = dedent("""\
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
    - Keep the `scrape(url, output_dir) -> dict` signature unchanged.
    - The return dict must have "tenders" (list of dicts with scraped data)
      and "downloaded_files" (list of saved file paths).
    - Make sure you are BOTH extracting structured tender data AND
      downloading attached documents.
    - If the site uses JavaScript to reveal content or download links,
      wait for network idle / relevant DOM selectors before extracting.
    - If downloads happen via POST, use `page.expect_download()` and
      save via `download.save_as()`.
    - Don't forget to save tenders.json inside output_dir.
    - Return ONLY the corrected Python code in a fenced block.
""")


def build_generation_prompt(
    url: str,
    domain: str,
    html_snippet: str,
    failed_selectors: list[str] | None = None,
) -> str:
    """
    Fill in the generation prompt template with real data.

    We cap the HTML snippet at 4000 chars to avoid blowing up the LLM's
    context window (and the bill).  For most tender pages, the first 4k
    chars contain enough structure (nav, table headers, first few links)
    for the LLM to figure out the page layout.
    """
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
    """
    Fill in the feedback prompt template with error diagnostics.

    The error message is capped at 2000 chars — long tracebacks waste
    tokens without adding useful information for the LLM.
    """
    return FEEDBACK_PROMPT.format(
        iteration=iteration,
        max_iterations=max_iterations,
        url=url,
        outcome=outcome,
        error=error[:2000],
        expected_docs=expected_docs,
        downloaded=downloaded,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 2 :  LLM Client
# ═══════════════════════════════════════════════════════════════════════════════
# Handles the actual HTTP calls to the OpenRouter API.
#
# OpenRouter is a unified gateway that lets us use models from OpenAI,
# Anthropic, Google, etc. through a single API key and endpoint.
# The request/response format follows the OpenAI chat-completions spec.
#
# We also do rough cost tracking so we know how much each generation costs.
# ═══════════════════════════════════════════════════════════════════════════════

# Approximate price per 1 million tokens, in USD.
# Format:  "model_name": (input_price, output_price)
# These are ballpark numbers for cost tracking — real billing comes from OpenRouter.
COST_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-4.5":  (3.0, 15.0),
    "anthropic/claude-haiku-4.5":   (1.0,  5.0),
    "openai/gpt-4o":                (2.5, 10.0),
    "openai/gpt-4o-mini":           (0.15, 0.6),
    "google/gemini-2.5-pro":        (1.25, 5.0),
    "google/gemini-2.5-flash-lite": (0.0,  0.0),   # free tier 🎉
}


@dataclass
class LLMResponse:
    """What we get back from the LLM after a chat call."""
    text: str                   # the actual response content
    model: str                  # which model answered
    input_tokens: int = 0       # how many tokens our prompt used
    output_tokens: int = 0      # how many tokens the response used
    cost_usd: float = 0.0       # estimated cost of this call


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Rough cost estimate based on token counts.
    Returns 0 if we don't have pricing info for the model.
    """
    if model not in COST_PER_MILLION_TOKENS:
        return 0.0
    input_price, output_price = COST_PER_MILLION_TOKENS[model]
    return (
        (input_tokens  / 1_000_000) * input_price +
        (output_tokens / 1_000_000) * output_price
    )


class LLMClient:
    """
    Talks to the OpenRouter API (or any OpenAI-compatible endpoint).

    Usage:
        client = LLMClient()
        response = await client.chat(
            system="You are a helpful assistant.",
            user="Write me a Python function that adds two numbers.",
        )
        print(response.text)
    """

    def __init__(
        self,
        api_key: str = OPENROUTER_API_KEY,
        base_url: str = OPENROUTER_BASE_URL,
        default_model: str = LLM_MODEL,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = default_model

        # We keep one HTTP client alive for the lifetime of this object
        # so we can reuse connections (faster for multiple calls).
        self._http = httpx.AsyncClient(timeout=120)

    async def chat(
        self,
        system: str,
        user: str,
        model: str | None = None,
    ) -> LLMResponse:
        """
        Send a system + user message to the LLM and get a response.

        Args:
            system: The system prompt (sets the LLM's behavior/role).
            user:   The user message (the actual task/question).
            model:  Override the default model for this call.

        Returns:
            LLMResponse with the generated text, token counts, and cost.
        """
        model = model or self.default_model

        # Build the payload in OpenAI chat-completions format
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }
        return await self._call(payload, model)

    async def _call(self, payload: dict, model: str) -> LLMResponse:
        """
        Internal: actually send the HTTP request to the API.

        If no API key is set, we return a harmless stub so the script
        doesn't crash during development/testing.
        """
        # --- Safety net for missing API key ---
        if not self.api_key:
            log.warning("No OPENROUTER_API_KEY set — returning stub response. "
                        "Add your key to .env to get real results.")
            return LLMResponse(
                text=(
                    "```python\n"
                    "# stub: no API key configured\n"
                    "def scrape(url, output_dir):\n"
                    "    return []\n"
                    "```"
                ),
                model=model,
            )

        # --- Build and send the request ---
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer":  "https://vergabepilot.ai",       # identifies our app to OpenRouter
            "X-Title":       "Vergabepilot.AI - Phase1",      # shows up in your OpenRouter dashboard
            "Content-Type":  "application/json",
        }

        try:
            response = await self._http.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as e:
            log.error("LLM API call failed: %s", e)
            raise

        # --- Parse the response ---
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Some models return content as a list of parts instead of a string
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        # --- Track token usage and cost ---
        usage = data.get("usage", {})
        input_tokens  = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = _estimate_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            text=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 3 :  Scraper Generator
# ═══════════════════════════════════════════════════════════════════════════════
# This is the core piece — it ties together the prompts and the LLM client.
#
# Flow for a first-time generation:
#   1. Fetch the target page's HTML (so the LLM can see the page structure)
#   2. Build the prompt with the URL + HTML snippet
#   3. Send it to the LLM
#   4. Extract the Python code from the ```python``` block in the response
#   5. Return the code (someone else validates and runs it)
#
# Flow for a retry (regeneration):
#   1. Build a feedback prompt with the error details
#   2. Send it to the LLM
#   3. Extract and return the corrected code
# ═══════════════════════════════════════════════════════════════════════════════

# Regex to pull code out of a ```python ... ``` fenced block
_CODE_FENCE_PATTERN = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


@dataclass
class GeneratedScraper:
    """The output of a generation or regeneration call."""
    code: str             # the Python scraper code (ready to save to a .py file)
    model: str            # which LLM model wrote it
    cost_usd: float       # how much this generation cost (approx)
    raw_response: str     # the full response from the LLM (for debugging)


class ScraperGenerator:
    """
    Uses an LLM to write scraper code for a given URL.

    This class handles two scenarios:
    - generate()    →  first attempt, no prior context
    - regenerate()  →  retry with feedback from a failed attempt

    It does NOT validate or execute the code — that's handled by the
    validator and executor modules (maintained by other team members).
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    # ── First attempt ─────────────────────────────────────────────────

    async def generate(self, url: str, model: str | None = None) -> GeneratedScraper:
        """
        Generate a scraper for the given URL from scratch.

        Steps:
          1. Fetch the page HTML (best-effort — it's okay if this fails)
          2. Build the prompt with URL + HTML snippet
          3. Send to LLM
          4. Extract code from the response
        """
        # Step 1: Get the page HTML so the LLM knows what it's working with
        html_snippet = await self._fetch_page_html(url)

        # Step 2: Extract the domain (e.g. "www.example.com") for the prompt
        domain = urlparse(url).netloc

        # Step 3: Build the full prompt
        user_message = build_generation_prompt(
            url=url,
            domain=domain,
            html_snippet=html_snippet,
        )

        # Step 4: Ask the LLM to write the scraper
        llm_response = await self.llm.chat(
            system=SYSTEM_PROMPT,
            user=user_message,
            model=model,
        )

        # Step 5: Extract the Python code from the response
        return self._extract_code(llm_response)

    # ── Retry with feedback ───────────────────────────────────────────

    async def regenerate(
        self,
        url: str,
        iteration: int,
        max_iterations: int,
        outcome: str,
        error: str,
        expected_docs: int,
        downloaded: int,
        model: str | None = None,
    ) -> GeneratedScraper:
        """
        Ask the LLM to fix its previous scraper attempt.

        This is called by the feedback loop (managed externally) when
        the previous scraper failed or didn't download enough files.

        Args:
            url:             The target URL (same as before)
            iteration:       Which attempt this is (2, 3, 4, ...)
            max_iterations:  Total allowed attempts
            outcome:         What went wrong ("execution_failed" or "insufficient_recall")
            error:           The error message or traceback from the failed run
            expected_docs:   How many documents we expected to find
            downloaded:      How many documents were actually downloaded
            model:           LLM model override (optional)
        """
        # Build a prompt that tells the LLM exactly what went wrong
        user_message = build_feedback_prompt(
            iteration=iteration,
            max_iterations=max_iterations,
            url=url,
            outcome=outcome,
            error=error,
            expected_docs=expected_docs,
            downloaded=downloaded,
        )

        # Ask the LLM to fix its code
        llm_response = await self.llm.chat(
            system=SYSTEM_PROMPT,
            user=user_message,
            model=model,
        )

        return self._extract_code(llm_response)

    # ── Helper: fetch the target page ─────────────────────────────────

    async def _fetch_page_html(self, url: str) -> str:
        """
        Download the raw HTML of the target page.

        This gives the LLM something concrete to work with — it can see
        the actual links, table structures, and button labels on the page.

        If fetching fails (timeout, SSL error, etc.), we return a
        placeholder comment.  The LLM can still try to generate a
        scraper based on the URL alone — it just won't be as accurate.
        """
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "VergabepilotBot/0.1"},
                )
                return response.text
        except Exception as e:
            log.warning("Could not fetch page HTML for %s — %s", url, e)
            return "<!-- could not fetch page -->"

    # ── Helper: extract code from LLM response ───────────────────────

    def _extract_code(self, response: LLMResponse) -> GeneratedScraper:
        """
        Pull the Python code out of the LLM's response.

        The LLM is instructed to wrap its code in a ```python``` block.
        We regex-match that block and extract the code inside.

        If there's no fenced block (the LLM didn't follow instructions),
        we fall back to using the entire response as code — sometimes
        that works, sometimes it doesn't, but it's better than nothing.
        """
        match = _CODE_FENCE_PATTERN.search(response.text)

        if match:
            code = match.group(1).strip()
        else:
            log.warning("LLM response didn't contain a ```python``` block — "
                        "using raw response as code")
            code = response.text.strip()

        return GeneratedScraper(
            code=code,
            model=response.model,
            cost_usd=response.cost_usd,
            raw_response=response.text,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 4 :  CLI  (Command-Line Interface)
# ═══════════════════════════════════════════════════════════════════════════════
# So you can run this script directly from the terminal.
#
#   python generator.py generate "https://example.com/tenders"
#   python generator.py regenerate "https://example.com/tenders" --iteration 2 ...
#
# Generated scraper code is saved to ./generated_scrapers/ by default.
# ═══════════════════════════════════════════════════════════════════════════════

def _save_scraper_to_file(code: str, url: str, output_dir: Path) -> Path:
    """
    Save the generated scraper code to a .py file.
    The filename is based on the domain, e.g. scraper_www_example_com.py
    """
    # Turn "www.example.com" into "www_example_com"
    domain_safe = urlparse(url).netloc.replace(".", "_")
    file_path = output_dir / f"scraper_{domain_safe}.py"
    file_path.write_text(code)
    return file_path


async def cmd_generate(args: argparse.Namespace):
    """
    Handle the 'generate' command:
    Fetch page → ask LLM → save scraper code.
    """
    llm = LLMClient()
    generator = ScraperGenerator(llm)

    log.info("Generating scraper for: %s", args.url)
    scraper = await generator.generate(args.url, model=args.model)

    # Decide where to save
    output_dir = Path(args.output) if args.output else Path.cwd() / "generated_scrapers"
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_path = _save_scraper_to_file(scraper.code, args.url, output_dir)

    # Print a summary
    print(f"\n{'='*60}")
    print(f"  Model:  {scraper.model}")
    print(f"  Cost:   ${scraper.cost_usd:.6f}")
    print(f"  Saved:  {saved_path}")
    print(f"{'='*60}\n")
    # print(scraper.code)  # Commented out to prevent printing the entire code to the terminal


async def cmd_regenerate(args: argparse.Namespace):
    """
    Handle the 'regenerate' command:
    Take error feedback → ask LLM to fix the code → save updated scraper.
    """
    llm = LLMClient()
    generator = ScraperGenerator(llm)

    log.info("Regenerating scraper for: %s  (attempt %d/%d)",
             args.url, args.iteration, args.max_iter)

    scraper = await generator.regenerate(
        url=args.url,
        iteration=args.iteration,
        max_iterations=args.max_iter,
        outcome=args.outcome,
        error=args.error,
        expected_docs=args.expected_docs,
        downloaded=args.downloaded,
        model=args.model,
    )

    # Save the fixed code
    output_dir = Path(args.output) if args.output else Path.cwd() / "generated_scrapers"
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_path = _save_scraper_to_file(scraper.code, args.url, output_dir)

    # Print a summary
    print(f"\n{'='*60}")
    print(f"  Model:  {scraper.model}")
    print(f"  Cost:   ${scraper.cost_usd:.6f}")
    print(f"  Saved:  {saved_path}")
    print(f"{'='*60}\n")
    # print(scraper.code)  # Commented out to prevent printing the entire code to the terminal


def main():
    """Parse command-line arguments and run the appropriate command."""

    parser = argparse.ArgumentParser(
        description="Phase-1 LLM Scraper Generator — Standalone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:

              # Generate a scraper for a tender page:
              python generator.py generate "https://example.com/tenders"

              # Use a different model:
              python generator.py generate "https://example.com/tenders" --model "openai/gpt-4o"

              # Regenerate after a failure (called by the feedback loop):
              python generator.py regenerate "https://example.com/tenders" \\
                  --iteration 2 --max-iter 5 \\
                  --outcome "execution_failed" \\
                  --error "TimeoutError: page did not load"
        """),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    # ── "generate" subcommand ─────────────────────────────────────────
    p_gen = subcommands.add_parser(
        "generate",
        help="Generate a scraper for a URL (first attempt)",
    )
    p_gen.add_argument("url",
                       help="The tender page URL to build a scraper for")
    p_gen.add_argument("--model", default=None,
                       help=f"LLM model to use (default: {LLM_MODEL})")
    p_gen.add_argument("--output", "-o", default=None,
                       help="Directory to save the scraper file (default: ./generated_scrapers)")

    # ── "regenerate" subcommand ───────────────────────────────────────
    p_regen = subcommands.add_parser(
        "regenerate",
        help="Fix a failed scraper using error feedback",
    )
    p_regen.add_argument("url",
                         help="The tender page URL (same as the original)")
    p_regen.add_argument("--model", default=None,
                         help=f"LLM model to use (default: {LLM_MODEL})")
    p_regen.add_argument("--iteration", type=int, required=True,
                         help="Which attempt number this is (2, 3, ...)")
    p_regen.add_argument("--max-iter", type=int, default=5,
                         help="Total allowed attempts (default: 5)")
    p_regen.add_argument("--outcome", required=True,
                         help="What went wrong: 'execution_failed' or 'insufficient_recall'")
    p_regen.add_argument("--error", default="",
                         help="The error message or traceback from the last run")
    p_regen.add_argument("--expected-docs", type=int, default=0,
                         help="How many documents we expect to find on the page")
    p_regen.add_argument("--downloaded", type=int, default=0,
                         help="How many documents the last attempt actually got")
    p_regen.add_argument("--output", "-o", default=None,
                         help="Directory to save the scraper file (default: ./generated_scrapers)")

    # ── Run the command ───────────────────────────────────────────────
    args = parser.parse_args()

    commands = {
        "generate":   cmd_generate,
        "regenerate": cmd_regenerate,
    }
    asyncio.run(commands[args.command](args))


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
