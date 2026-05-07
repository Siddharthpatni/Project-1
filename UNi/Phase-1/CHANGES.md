# Phase-1 — Changes in this zip

## Fixed
**`generator.py` — `LLMClient.chat()`**
The X-Title header contained an en-dash (`–`, U+2013), which is not ASCII.
`httpx` rejects non-ASCII header values, causing:
```
UnicodeEncodeError: 'ascii' codec can't encode character '\u2013' ...
```
Two fixes applied together:
1. The en-dash was replaced with a regular hyphen.
2. Headers are now sanitized through `.encode("ascii","ignore").decode("ascii")`
   before being sent, so any future copy-paste of a non-ASCII char can never
   crash the request again.

## New: validator.py is its own module (matches ARCHITECTURE.md)

The architecture diagram lists `validator` alongside `generator`, `executor`,
and `evaluator` — but the AST safety check used to live inside `executor.py`.
That's been split out into a dedicated `validator.py`.

| Module          | Role                                                |
|-----------------|-----------------------------------------------------|
| `validator.py`  | AST-based static safety check                       |
| `executor.py`   | Subprocess sandbox + result capture                 |
| `generator.py`  | URL → LLM → scraper code                            |
| `docker_sandbox.py` | Hardened Docker sandbox                         |
| `evaluator.py`  | Compare results vs ground truth                     |

### Backward compatibility (nothing breaks)

- `executor.py` re-exports `validate`, `ValidationResult`, `FORBIDDEN_IMPORTS`,
  `FORBIDDEN_CALLS`, `REQUIRED_FUNCTION`, and `_resolve_call_name` from
  `validator`. Old imports like `from executor import validate` still work.
- `docker_sandbox.py` prefers `validator.py` and falls back to `executor.validate`,
  then to `compile()` if neither is importable.
- `test_validator.py` has been updated to import from `validator` (the
  architecturally-correct location). All 38 tests still pass.

### Standalone CLI

```bash
python validator.py scraper.py                   # one file
python validator.py scraper_a.py scraper_b.py    # multiple files
python validator.py *.py --quiet                 # only print failures
```
Exit code is `0` when every file is safe, `1` if any is unsafe — useful in CI.

## Cleaned
Removed from the zip (not needed for the pipeline):
- `__pycache__/`, `venv/`
- `scratch.py`, `scratch_html.txt`, `scratch_html_1.txt`, `screenshot.png`

## Files in this zip — and how they connect
```
URL ──> generator.py ──> scraper_<domain>.py
                              │
                              ▼
                         validator.py   (AST safety check; standalone module)
                              │ if safe
              ┌───────────────┼─────────────────────┐
              ▼                                     ▼
      executor.py                           docker_sandbox.py
   (subprocess sandbox)                     (Docker sandbox; auto-calls
                                             generator.py if missing or
                                             with --regenerate-on-fail)
              │                                     │
              └─────────► results.jsonl ◄───────────┘
                                  │
                                  ▼
                            evaluator.py ──► report
```
Every script also runs standalone — see each file's `--help`.

## Quick start

```bash
pip install -r requirements.txt
playwright install chromium       # optional but recommended for the host
echo "OPENROUTER_API_KEY=sk-or-..." > .env
python docker_sandbox.py build
python docker_sandbox.py run \
    generated_scrapers/scraper_www_evergabe-online_de.py \
    "https://www.evergabe-online.de/search.html"
```
