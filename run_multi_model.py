#!/usr/bin/env python3
"""
run_multi_model.py — Run the same prompt across multiple LLMs and compare.

For every enabled model in models.json x every URL in _first5_urls.json:
  1. python generator.py generate URL --hardened --model <id>  (iteration 1)
  2. python executor.py run scraper_<domain>.py URL --keep-downloads downloads/<model>/<url>/
  3. If 0 files were produced and --max-iter > 1:
       python generator.py regenerate URL --iteration N --hardened --model <id> ...
       python executor.py run ...
     up to max_iterations times.

Captures per (model, URL):
  - iterations           how many generate/regenerate calls until success or budget exhausted
  - generate_runtime_s   total seconds spent in generator subprocess(es)
  - execute_runtime_s    total seconds spent in executor subprocess(es)
  - downloaded_count     files in keep-downloads dir at the end
  - cost_usd             parsed from generator stdout ("Cost: $0.001234")
  - status               "success" if downloaded>0, else "fail"

Aggregates per model and writes:
  - results/comparison_run_<timestamp>.json
  - results/comparison_report.md  (the ranked comparison table)

Usage:
    python run_multi_model.py
    python run_multi_model.py --max-iter 1               # disable regenerate loop
    python run_multi_model.py --only "Gemini 2.5 Flash Lite,GPT-4o Mini"
    python run_multi_model.py --models models.json --urls _first5_urls.json
    python run_multi_model.py --truth ground_truth.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
GEN_PY = HERE / "generator.py"
EXE_PY = HERE / "executor.py"
RESULTS_DIR = HERE / "results"

PYTHON = sys.executable

COST_RE = re.compile(r"Cost:\s*\$([\d.]+)", re.IGNORECASE)


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class UrlResult:
    url: str
    iterations: int = 0
    generate_runtime_s: float = 0.0
    execute_runtime_s: float = 0.0
    downloaded_count: int = 0
    cost_usd: float = 0.0
    status: str = "fail"
    error: str = ""


@dataclass
class ModelResult:
    alias: str
    model_id: str
    per_url: list[UrlResult] = field(default_factory=list)
    enabled: bool = True

    # aggregates (filled by compute_aggregates)
    success_count: int = 0
    avg_recall: float = 0.0
    avg_iterations: float = 0.0
    total_runtime_s: float = 0.0
    total_cost_usd: float = 0.0


# ─── IO ──────────────────────────────────────────────────────────────────────

def load_models(path: Path) -> tuple[list[dict], dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    models = [m for m in raw.get("models", []) if m.get("enabled", True)]
    if not models:
        raise SystemExit(f"{path}: no enabled models")
    return models, raw.get("run", {})


def load_urls(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit(f"{path}: expected non-empty list of URLs")
    return [str(u).strip() for u in data if str(u).strip()]


def load_ground_truth(path: Path | None) -> dict[str, int]:
    if not path or not path.is_file():
        return {}
    truth: dict[str, int] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            try:
                truth[url] = int(row.get("expected_docs", 0))
            except ValueError:
                truth[url] = 0
    return truth


def domain_safe(url: str) -> str:
    return urlparse(url).netloc.replace(".", "_").replace(":", "_") or "scraper"


def model_safe(alias: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", alias)


def _parse_cost(stdout: str) -> float:
    """generator.py prints `Cost:   $0.001234`. Take the last match in stdout."""
    matches = COST_RE.findall(stdout or "")
    if not matches:
        return 0.0
    try:
        return float(matches[-1])
    except ValueError:
        return 0.0


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str, float]:
    """Run a subprocess with UTF-8 IO and a hard timeout; return (rc, out, err, elapsed)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(HERE), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace", env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or "", time.time() - t0
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + f"\nTIMEOUT after {timeout}s", time.time() - t0


# ─── Per-model evaluation ────────────────────────────────────────────────────

def evaluate_model_on_url(
    model: dict,
    url: str,
    workdir: Path,
    downloads_dir: Path,
    max_iter: int,
    gen_timeout: int,
    exe_timeout: int,
    expected_docs: int,
) -> UrlResult:
    """Run generate -> execute, with feedback regenerate up to max_iter times."""
    res = UrlResult(url=url)

    downloads_dir.mkdir(parents=True, exist_ok=True)
    scraper_path = workdir / f"scraper_{domain_safe(url)}.py"
    last_error = ""

    for it in range(1, max_iter + 1):
        res.iterations = it

        if it == 1:
            cmd_gen = [
                PYTHON, str(GEN_PY), "generate", url,
                "--hardened",
                "--model", model["model_id"],
                "-o", str(workdir),
            ]
        else:
            cmd_gen = [
                PYTHON, str(GEN_PY), "regenerate", url,
                "--hardened",
                "--model", model["model_id"],
                "--iteration", str(it),
                "--max-iter", str(max_iter),
                "--outcome", "execution_failed",
                "--error", last_error[-2000:],
                "--expected-docs", str(expected_docs or 0),
                "--downloaded", str(res.downloaded_count),
                "--previous-code", str(scraper_path) if scraper_path.is_file() else "",
                "-o", str(workdir),
            ]

        rc, out, err, elapsed = _run(cmd_gen, gen_timeout)
        res.generate_runtime_s += elapsed
        res.cost_usd += _parse_cost(out)

        if rc != 0 or not scraper_path.is_file():
            res.error = f"generator failed (rc={rc}): {(err or out)[-300:]}"
            last_error = res.error
            continue

        cmd_exe = [
            PYTHON, str(EXE_PY), "run", str(scraper_path), url,
            "--keep-downloads", str(downloads_dir),
        ]
        rc2, out2, err2, elapsed2 = _run(cmd_exe, exe_timeout)
        res.execute_runtime_s += elapsed2

        files = [p for p in downloads_dir.iterdir() if p.is_file()] if downloads_dir.is_dir() else []
        res.downloaded_count = len(files)

        if res.downloaded_count > 0:
            res.status = "success"
            res.error = ""
            return res

        last_error = (out2 + "\n" + err2)[-2000:] or "scraper returned 0 files"
        res.error = last_error[-300:]

    return res


# ─── Aggregation + report ────────────────────────────────────────────────────

def compute_aggregates(model_results: list[ModelResult], truth: dict[str, int]) -> None:
    for m in model_results:
        recalls: list[float] = []
        m.success_count = 0
        m.total_runtime_s = 0.0
        m.total_cost_usd = 0.0
        for r in m.per_url:
            m.total_runtime_s += r.generate_runtime_s + r.execute_runtime_s
            m.total_cost_usd += r.cost_usd
            if r.status == "success":
                m.success_count += 1
            expected = truth.get(r.url, 0)
            if expected > 0:
                recalls.append(min(r.downloaded_count / expected, 1.0))
            elif r.downloaded_count > 0:
                recalls.append(1.0)
            else:
                recalls.append(0.0)
        m.avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
        m.avg_iterations = (
            sum(r.iterations for r in m.per_url) / len(m.per_url)
            if m.per_url else 0.0
        )


def render_report(
    model_results: list[ModelResult],
    truth: dict[str, int],
    urls: list[str],
    max_iter: int,
) -> str:
    n = len(urls)
    total_expected = sum(truth.get(u, 0) for u in urls)

    def composite(m: ModelResult) -> tuple[float, float]:
        score = (m.success_count / n if n else 0) * 0.5 + m.avg_recall * 0.5
        return (-score, m.total_cost_usd)  # higher score first, cheaper breaks ties

    ranked = sorted(model_results, key=composite)

    lines: list[str] = []
    lines.append("# Multi-LLM Comparison Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"- Models compared: **{len(model_results)}**")
    lines.append(f"- URLs evaluated:  **{n}**")
    lines.append(f"- Ground-truth total expected docs: **{total_expected}**")
    lines.append(f"- Max iterations per (model, URL): **{max_iter}**")
    lines.append("")
    lines.append("## 1. Ranking")
    lines.append("")
    lines.append("| Rank | Model | model_id | Success | Avg Recall | Avg Iter | Runtime (s) | Cost (USD) |")
    lines.append("|:--:|:--|:--|:--:|:--:|:--:|:--:|:--:|")
    for i, m in enumerate(ranked, 1):
        sr = (m.success_count / n * 100) if n else 0
        lines.append(
            f"| {i} | **{m.alias}** | `{m.model_id}` | "
            f"{m.success_count}/{n} ({sr:.0f}%) | "
            f"{m.avg_recall*100:.1f}% | "
            f"{m.avg_iterations:.2f} | "
            f"{m.total_runtime_s:.1f} | "
            f"${m.total_cost_usd:.4f} |"
        )

    lines.append("")
    lines.append("## 2. Iterations per (model, URL)")
    lines.append("")
    header = "| Model |" + "".join(f" {urlparse(u).netloc[:18]} |" for u in urls) + " Avg |"
    sep = "|:--|" + ":--:|" * (n + 1)
    lines.append(header)
    lines.append(sep)
    for m in ranked:
        cells = []
        for u in urls:
            r = next((x for x in m.per_url if x.url == u), None)
            if r is None:
                cells.append("-")
            else:
                mark = "OK" if r.status == "success" else "x"
                cells.append(f"{r.iterations} ({mark})")
        lines.append("| " + m.alias + " | " + " | ".join(cells) + f" | {m.avg_iterations:.2f} |")

    lines.append("")
    lines.append("## 3. Per-URL breakdown")
    lines.append("")
    for m in ranked:
        lines.append(f"### {m.alias}  -  `{m.model_id}`")
        lines.append("")
        lines.append("| URL | Status | Iters | Downloaded | Expected | Recall | Gen (s) | Exec (s) | Cost ($) |")
        lines.append("|:--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|")
        for r in m.per_url:
            expected = truth.get(r.url, 0)
            recall = (min(r.downloaded_count / expected, 1.0) * 100) if expected else (100.0 if r.downloaded_count else 0.0)
            lines.append(
                f"| `{r.url[:70]}{'...' if len(r.url) > 70 else ''}` | "
                f"{'OK' if r.status == 'success' else 'FAIL'} | "
                f"{r.iterations} | {r.downloaded_count} | {expected or 'N/A'} | "
                f"{recall:.0f}% | {r.generate_runtime_s:.1f} | {r.execute_runtime_s:.1f} | "
                f"{r.cost_usd:.4f} |"
            )
        lines.append("")

    # Iteration-need notes
    lines.append("## 4. Notes - iterations needed per model")
    lines.append("")
    lines.append(
        "Iterations = number of `generate` + `regenerate` calls made before the executor "
        "produced at least one downloaded file, capped at `max_iterations`. A model that "
        "scores 1.00 average iterations got every URL right on the first attempt; higher "
        "averages indicate the feedback loop was needed."
    )
    lines.append("")
    for m in ranked:
        ok = sum(1 for r in m.per_url if r.status == "success")
        first_try = sum(1 for r in m.per_url if r.status == "success" and r.iterations == 1)
        lines.append(
            f"- **{m.alias}**: avg iterations {m.avg_iterations:.2f}, "
            f"{first_try}/{n} URLs succeeded on iteration 1, {ok}/{n} succeeded overall."
        )

    return "\n".join(lines) + "\n"


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=str(HERE / "models.json"))
    p.add_argument("--urls",   default=str(HERE / "_first5_urls.json"))
    p.add_argument("--truth",  default=str(HERE / "ground_truth.csv"))
    p.add_argument("--max-iter", type=int, default=None,
                   help="Override max_iterations from models.json")
    p.add_argument("--only", default=None,
                   help="Comma-separated list of model aliases to run (others skipped)")
    p.add_argument("--output", "-o", default=None,
                   help="Output directory (default: ./results)")
    args = p.parse_args()

    models_cfg, run_cfg = load_models(Path(args.models))
    urls = load_urls(Path(args.urls))
    truth = load_ground_truth(Path(args.truth))

    max_iter = args.max_iter if args.max_iter is not None else int(run_cfg.get("max_iterations", 3))
    gen_timeout = int(run_cfg.get("generate_timeout_s", 240))
    exe_timeout = int(run_cfg.get("per_url_timeout_s", 90))

    only = {s.strip() for s in args.only.split(",")} if args.only else None

    out_dir = Path(args.output) if args.output else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    workdir_root = out_dir / f"multi_model_{ts}"
    workdir_root.mkdir(parents=True, exist_ok=True)
    downloads_root = workdir_root / "downloads"

    print(f"\n=== Multi-LLM Comparison ===")
    print(f"  Models: {[m['alias'] for m in models_cfg if not only or m['alias'] in only]}")
    print(f"  URLs:   {len(urls)}")
    print(f"  Max iterations: {max_iter}")
    print(f"  Output: {workdir_root}\n")

    results: list[ModelResult] = []

    for m_cfg in models_cfg:
        if only and m_cfg["alias"] not in only:
            continue
        mr = ModelResult(alias=m_cfg["alias"], model_id=m_cfg["model_id"])
        print(f"--- {mr.alias} ({mr.model_id}) ---")
        model_workdir = workdir_root / model_safe(mr.alias)
        model_workdir.mkdir(parents=True, exist_ok=True)
        for url in urls:
            print(f"  [{mr.alias}] {url[:80]}")
            dl_dir = downloads_root / model_safe(mr.alias) / domain_safe(url)
            r = evaluate_model_on_url(
                model=m_cfg,
                url=url,
                workdir=model_workdir,
                downloads_dir=dl_dir,
                max_iter=max_iter,
                gen_timeout=gen_timeout,
                exe_timeout=exe_timeout,
                expected_docs=truth.get(url, 0),
            )
            mr.per_url.append(r)
            print(f"    -> iters={r.iterations}  files={r.downloaded_count}  "
                  f"gen={r.generate_runtime_s:.1f}s exec={r.execute_runtime_s:.1f}s "
                  f"cost=${r.cost_usd:.4f}  status={r.status}")
        results.append(mr)

        # Flush partial JSON after each model so a long run is recoverable.
        compute_aggregates(results, truth)
        partial = {
            "timestamp": ts,
            "max_iterations": max_iter,
            "models": [
                {
                    "alias": mr.alias,
                    "model_id": mr.model_id,
                    "success_count": mr.success_count,
                    "avg_recall": mr.avg_recall,
                    "avg_iterations": mr.avg_iterations,
                    "total_runtime_s": mr.total_runtime_s,
                    "total_cost_usd": mr.total_cost_usd,
                    "per_url": [r.__dict__ for r in mr.per_url],
                }
                for mr in results
            ],
        }
        (workdir_root / "partial.json").write_text(json.dumps(partial, indent=2), encoding="utf-8")

    compute_aggregates(results, truth)
    final = {
        "timestamp": ts,
        "max_iterations": max_iter,
        "models": [
            {
                "alias": mr.alias,
                "model_id": mr.model_id,
                "success_count": mr.success_count,
                "avg_recall": mr.avg_recall,
                "avg_iterations": mr.avg_iterations,
                "total_runtime_s": mr.total_runtime_s,
                "total_cost_usd": mr.total_cost_usd,
                "per_url": [r.__dict__ for r in mr.per_url],
            }
            for mr in results
        ],
    }

    json_path = out_dir / f"comparison_run_{ts}.json"
    json_path.write_text(json.dumps(final, indent=2), encoding="utf-8")

    report = render_report(results, truth, urls, max_iter)
    report_path = out_dir / "comparison_report.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\nWrote {json_path}")
    print(f"Wrote {report_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
