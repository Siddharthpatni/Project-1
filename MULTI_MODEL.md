# Multi-LLM Comparison

Run the same Phase-1 scraping prompt across multiple LLMs and compare
success rate, recall, runtime, cost, and iterations.

## Files involved

| File | Purpose |
|---|---|
| [models.json](models.json) | Fleet definition. One row per LLM with `alias`, `model_id`, prices, and `enabled` flag. |
| [_first5_urls.json](_first5_urls.json) | Eval dataset - the 5 real German tender URLs every model is run against. |
| [ground_truth.csv](ground_truth.csv) | Expected document counts per URL. Used for recall computation. |
| [run_multi_model.py](run_multi_model.py) | The driver: loops models x URLs, runs generator + executor with a feedback loop, writes JSON + Markdown reports. |
| [results/comparison_report.md](results/) | The ranked comparison table (regenerated every run). |
| [results/comparison_run_<ts>.json](results/) | Raw per-run record - one file per invocation. |

## Quick start

```bash
# Run every enabled model on every URL with the default 3-iteration feedback loop:
python run_multi_model.py

# Subset of models:
python run_multi_model.py --only "Gemini 2.5 Flash Lite,GPT-4o Mini"

# Disable the feedback loop (one shot per URL per model):
python run_multi_model.py --max-iter 1

# Custom dataset:
python run_multi_model.py --urls my_urls.json --truth my_truth.csv
```

You will need `OPENROUTER_API_KEY` in `.env` (the same key the rest of Phase-1
uses). Without a key, every call falls through to the LLMClient stub and the
report will show 0 files / 0 cost for every cell.

## How a single (model, URL) is evaluated

```
iteration 1:
    python generator.py generate URL --hardened --model <id> -o <workdir>
    python executor.py run scraper_<domain>.py URL --keep-downloads <dl>
    if files > 0: SUCCESS, stop.

iteration 2..N:                              # only if iteration 1 returned 0 files
    python generator.py regenerate URL --hardened --model <id> \
        --iteration N --max-iter N --outcome execution_failed \
        --error "<tail of last stderr>" \
        --previous-code <workdir>/scraper_*.py
    python executor.py run ...
    if files > 0: SUCCESS, stop.
```

`max_iterations` defaults to **3** (from `models.json -> run.max_iterations`).
Override with `--max-iter`.

## What gets measured

Per (model, URL):

| Metric | Definition |
|---|---|
| `iterations` | Number of `generate` + `regenerate` calls before the executor produced >= 1 file, capped at `max_iterations`. |
| `generate_runtime_s` | Total wall-clock spent in the generator subprocess across all iterations. |
| `execute_runtime_s` | Total wall-clock spent in the executor subprocess. |
| `downloaded_count` | Files in the keep-downloads directory at the end. |
| `cost_usd` | Parsed from generator stdout (`Cost: $0.001234`). Sum across iterations. |
| `status` | `success` if any iteration produced >= 1 file, else `fail`. |

Per model (aggregated):

| Metric | Definition |
|---|---|
| `success_count` | URLs where status == success. |
| `avg_recall` | Mean of `min(downloaded / expected, 1.0)` across URLs (uses `ground_truth.csv`). |
| `avg_iterations` | Mean iterations across URLs. **This is the "iterations needed per model" answer.** |
| `total_runtime_s` | Sum of all generate+execute time. |
| `total_cost_usd` | Sum of per-URL cost. |

## How the report ranks models

Composite score per model:

```
score = 0.5 * (success_count / n_urls) + 0.5 * avg_recall
```

Models are sorted by `score` descending, ties broken by `total_cost_usd`
ascending. The output lives in `results/comparison_report.md` with four
sections:

1. **Ranking** - the headline table.
2. **Iterations per (model, URL)** - a model x URL grid showing how many
   iterations each cell needed (and OK/x).
3. **Per-URL breakdown** - per-model expansion with status, files, expected,
   recall, runtime, cost.
4. **Iteration notes** - one bullet per model summarising
   "avg iterations N.NN, K/n URLs succeeded on iteration 1, M/n overall."

Partial JSON is flushed after every model finishes, so long runs are
recoverable if you Ctrl-C.

## Adding a new model

Edit [models.json](models.json):

```json
{
  "alias":        "My Model",
  "model_id":     "vendor/model-slug",
  "in_per_mtok":  1.00,
  "out_per_mtok": 4.00,
  "enabled":      true
}
```

Pricing is informational - real billing comes from OpenRouter. Make sure
the `model_id` is an exact OpenRouter slug; otherwise the row will fail
with an HTTP 404 from `generator.py`.

## Sample comparison report (schematic)

```
# Multi-LLM Comparison Report

| Rank | Model | model_id | Success | Avg Recall | Avg Iter | Runtime (s) | Cost (USD) |
|:--:|:--|:--|:--:|:--:|:--:|:--:|:--:|
| 1 | Gemini 2.5 Flash Lite | google/gemini-2.5-flash-lite | 5/5 (100%) | 21.0% | 1.20 | 132.4 | $0.0140 |
| 2 | GPT-4o Mini           | openai/gpt-4o-mini           | 5/5 (100%) | 21.0% | 1.40 | 158.0 | $0.0210 |
| 3 | Claude Haiku 4.5      | anthropic/claude-haiku-4.5   | 4/5  (80%) | 19.5% | 1.60 | 201.2 | $0.0530 |
...
```

The actual numbers depend entirely on what each model produces on the day -
expect them to drift as providers update their models.
