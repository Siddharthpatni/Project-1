# Phase 1 — LLM-based Scraper Generation

**Goal:** Automatically generate and evaluate scrapers using LLMs.

## Files

| File | Responsibility |
|---|---|
| `prompts.py` | System + user prompt templates (generation + feedback) |
| `generator.py` | Calls the LLM, strips code fences, returns `GeneratedScraper` |
| `validator.py` | Static AST check — rejects forbidden imports/calls, requires `scrape(url, output_dir)` |
| `executor.py` | Wraps generated code, runs it inside `core.sandbox`, returns downloaded files |
| `evaluator.py` | Computes success / recall / runtime against a `GroundTruth` row |
| `feedback_loop.py` | Loop: generate → validate → execute → evaluate → retry up to N times |

## Running an evaluation

```bash
curl -X POST http://localhost:8000/api/evaluation/run \
  -H "Content-Type: application/json" \
  -d '{
        "dataset_path": "/app/data/samples/eval_dataset.jsonl",
        "models": ["anthropic/claude-sonnet-4.5", "openai/gpt-4o", "google/gemini-2.5-pro"],
        "max_iterations": 5
      }'
```

Watch results stream in at `/evaluation` in the UI.

## Dataset format

JSONL, one row per URL:

```json
{"url": "https://www.evergabe-online.de/...", "expected_doc_count": 4, "expected_extensions": ["pdf", "docx"], "notes": "two attachments behind a login wall"}
```

See `data/samples/eval_dataset.jsonl` for a starting set you can extend during the
hackathon.

## Safety

Two layers of defense, both mandatory:

1. **Static**: `validator.py` rejects code containing `subprocess`, `eval`, `exec`,
   `os.system`, raw sockets, or anything that imports a forbidden module.
2. **Runtime**: `core.sandbox.run_script` runs the code in a subprocess with:
   - `RLIMIT_AS` capped to `SANDBOX_MEMORY_MB`
   - wall-clock timeout `SANDBOX_TIMEOUT_SECONDS`
   - stripped environment (only `PATH`, `PYTHONPATH`, `HOME`, `TMPDIR`, `LANG`)
   - new process group so we can kill the whole tree

For real production deployment, run the worker container itself under gVisor or
Firecracker — the in-process sandbox is the inner fence, not the only one.

## Metrics tracked per run

- `success` (bool, recall ≥ 0.5)
- `recall` (downloaded / expected, capped at 1.0)
- `iterations` until success
- `runtime_seconds`
- `cost_usd` (estimated from token usage)

These are aggregated per model in `GET /api/evaluation/summary` and rendered in the
benchmark page.
