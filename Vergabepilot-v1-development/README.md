# TenderScraper

Automated document discovery pipeline for German public procurement (Vergabe) portals. Given a CSV of tender URLs, TenderScraper identifies the procurement platform, finds document download links (preferring "download all" ZIP archives), and optionally downloads the files.

Current success rate: ~89% across 100+ procurement domains.


## How it works

The pipeline has three layers:

1. **Platform classification** (`classifier.py`) -- Identifies which procurement software a URL belongs to (DTVP, NetServer, eVergabe, etc.) using URL patterns and HTML content analysis. For DTVP-family sites, it constructs download URLs deterministically from templates, without any HTTP requests or LLM calls.

2. **LLM-powered scraper generation** (`llm_codegen.py`) -- For platforms that cannot be handled deterministically, the page HTML is sent to an LLM (Gemini 2.5 Flash via OpenRouter). The LLM generates a Python `fetch_documents()` function tailored to that specific platform. Generated scrapers are cached per domain in `llm_cache/`, so the LLM is only called once per new platform.

3. **Pipeline orchestrator** (`pipeline.py`) -- Reads the input CSV, classifies each URL, runs the appropriate scraper (deterministic template or LLM-generated), validates discovered URLs with HEAD requests, optionally downloads files, and writes structured results.

Additionally, `browser_helper.py` provides a `BrowserSession` wrapper around Playwright for sites that require JavaScript rendering.


## Requirements

- Python 3.10+
- [Playwright](https://playwright.dev/python/) (for JS-heavy sites)
- An [OpenRouter](https://openrouter.ai/) API key (for LLM-generated scrapers)

Install dependencies:

```
pip install playwright python-dotenv requests beautifulsoup4
playwright install chromium
```


## Setup

Create a `.env` file in the project root with your OpenRouter API key:

```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```


## Usage

### Basic run

Process all URLs from a CSV file:

```
python pipeline.py publications_updated.csv
```

The pipeline auto-detects the URL column in the CSV. Results are written to `results/`.

### Common options

```
# Process only the first 20 URLs
python pipeline.py publications_updated.csv --limit 20

# Discover document URLs without downloading files
python pipeline.py publications_updated.csv --no-download

# Use 8 parallel workers (default: 4)
python pipeline.py publications_updated.csv --workers 8

# Force the LLM to regenerate all cached scrapers
python pipeline.py publications_updated.csv --force-regen

# Specify a different LLM model
python pipeline.py publications_updated.csv --model google/gemini-2.5-flash

# Export successful URLs as seed list (for use with webArchive/Browsertrix)
python pipeline.py publications_updated.csv --export-seeds seeds.canonical.txt

# Specify which CSV column contains the URLs
python pipeline.py publications_updated.csv --url-column "tender_url"
```

### All options

| Option | Default | Description |
|--------|---------|-------------|
| `--api-key KEY` | `OPENROUTER_API_KEY` env var | OpenRouter API key |
| `--model MODEL` | `google/gemini-2.5-flash` | LLM model for scraper generation |
| `--limit N` | all | Process only the first N URLs |
| `--url-column NAME` | auto-detect | CSV column containing URLs |
| `--no-download` | off | Skip file downloads, only discover URLs |
| `--output DIR` | `./results` | Output directory for results |
| `--workers N` | 4 | Number of parallel worker threads |
| `--force-regen` | off | Regenerate LLM scrapers (ignore cache) |
| `--export-seeds FILE` | off | Append successful URLs to a seeds file |


## Output

Each pipeline run produces two files in the `results/` directory:

- `run_YYYYMMDD_HHMMSS.jsonl` -- One JSON object per processed URL, containing the platform classification, discovered document URLs, download status, and timing.
- `run_YYYYMMDD_HHMMSS_summary.json` -- Aggregated statistics: success rate, counts by platform and status, LLM call counts.

When `--no-download` is not set, downloaded files are saved to `results/<domain>/<project_id>/`.


## Project structure

```
TenderScraper/
    pipeline.py              Main entry point and orchestrator
    classifier.py            Platform detection via URL patterns and HTML
    llm_codegen.py           LLM prompt, code generation, and execution
    browser_helper.py        Playwright wrapper for JS-heavy sites
    publications_updated.csv Input dataset (~14,800 tender URLs)
    llm_cache/               Cached LLM-generated scrapers (one .py per domain)
    results/                 Pipeline run outputs and downloaded files
    .env                     API key (not committed)
```


## Supported platforms

Deterministic (no LLM needed):
- DTVP family (Satellite/VMPSatellite) -- ZIP download URL constructed from template

LLM-generated scrapers (cached after first run):
- NetServer family (vergabe.autobahn.de, tender24.de, sachsen-vergabe.de, and others)
- evergabe.de, evergabe-online.de, evergabe.bayern.de
- deutsche-evergabe.de, deutsches-ausschreibungsblatt.de
- bi-medien.de, subreport.de, meinauftrag.rib.de
- vergabe24.de, bund.vergabe24.de
- plattform.aumass.de, staatsanzeiger-eservices.de
- And 80+ other German procurement portals


## Rate limiting

Some platforms (notably evergabe.de) enforce aggressive rate limiting. The pipeline serializes requests per domain and applies configurable delays for sensitive domains. The rate limit configuration is in `pipeline.py` under `_DOMAIN_RATE_LIMITS`.


## Notes

- The pipeline always prefers "download all" ZIP archives over individual file links.
- LLM-generated scrapers are executed locally via `exec()`. Only run this in controlled environments.
- The `.env` file contains your API key and must not be committed.
