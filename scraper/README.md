# Tender Document Agent

This project turns your prompt into a runnable Python agent that:

- opens tender pages in Chromium with Playwright
- captures screenshots while exploring the page
- discovers document links and document-related subpages
- supports direct URLs or a CSV file of URLs
- uses `gpt-4o-mini` for document selection when an API key is available
- downloads only high-value documents
- deletes duplicates and obviously irrelevant files after download
- writes cleaner per-run artifacts for discovery, downloads, and final results

## Files

- `system_prompt.py`: the prompt you supplied
- `main.py`: CLI entrypoint
- `tender_agent/config.py`: runtime settings and API key wiring
- `tender_agent/input_loader.py`: direct URL and CSV loading
- `tender_agent/browser.py`: page exploration, screenshots, link discovery
- `tender_agent/llm_selector.py`: OpenAI `gpt-4o-mini` document selection
- `tender_agent/filtering.py`: importance scoring and post-download validation
- `tender_agent/downloader.py`: selective downloads and cleanup
- `tender_agent/storage.py`: structured artifact layout for each run and site
- `tender_agent/runner.py`: orchestration and JSON output

## Install

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Configure Keys

You can set environment variables directly:

```powershell
$env:AGENT_API_KEY="sk-..."
$env:AGENT_BASE_URL=""
$env:OPENAI_MODEL="gpt-4o-mini"
```

Compatibility aliases also work if you want to keep your current naming:

```powershell
$env:PLAYWRIGHT_API_KEY="sk-..."
$env:PLAYWRIGHT_BASE_URL=""
```

Or copy `.env.example` into `.env` and load it in your shell before running.
If `.env` does not exist, the app also falls back to `.env.example`.

You can also set a default CSV path in `.env`:

```powershell
$env:TENDER_CSV_PATH="C:\data\tenders.csv"
```

## Run

```powershell
python main.py "https://example.com/tender"
```

Process the first 10 URLs from a CSV:

```powershell
python main.py --csv "C:\data\tenders.csv" --limit 10
```

Run with no command-line arguments after setting `TENDER_CSV_PATH` and `TENDER_LIMIT`:

```powershell
python main.py
```

Use a specific CSV column and explicit API keys:

```powershell
python main.py --csv "C:\data\tenders.csv" --csv-column tender_url --limit 10 --api-key "sk-..."
```

Use an OpenAI-compatible provider endpoint:

```powershell
python main.py --csv "C:\data\tenders.csv" --limit 10 --api-key "provider-key" --base-url "https://provider.example/api/v1"
```

Optional flags:

- `--csv C:\data\tenders.csv`
- `--csv-column tender_url`
- `--limit 10`
- `--output-dir artifacts`
- `--max-pages 12`
- `--max-scrolls 6`
- `--headful`
- `--show-prompt`
- `--model gpt-4o-mini`
- `--api-key ...`
- `--playwright-api-key ...`
- `--base-url https://provider.example/api/v1`

## Output

For each run, the agent writes:

- run summary under `artifacts/runs/<timestamp>/run.json`
- per-site metadata under `artifacts/runs/<timestamp>/sites/<index>_<host>_<hash>/site.json`
- screenshots under `.../discovery/screenshots/`
- candidate, selection, and download manifests under `.../results/`
- final kept files under `.../documents/kept/<bucket>/`
- final JSON under `.../results/final.json`

Download buckets are organized into folders such as `pdf`, `spreadsheets`, `text`, `archives`, `cad`, `presentations`, and `other`.

## Notes

- Playwright itself does not require an API key in this project. The single configured key is only for the `gpt-4o-mini` model call.
- The crawler follows same-site pages that look like document hubs, attachments, downloads, notices, or pagination.
- If the OpenAI call fails, the agent automatically falls back to the heuristic filter in `tender_agent/filtering.py`.
- Some tender sites hide files behind JavaScript flows or authentication. For those cases, run with `--headful` and extend the click logic in `tender_agent/browser.py`.
