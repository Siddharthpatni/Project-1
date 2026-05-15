"""Driver: generate (hardened) + execute for the first 5 URLs in publications_updated.csv.
Writes per-URL results to ./results/_first5_summary.json.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
GEN = HERE / "generator.py"
EXE = HERE / "executor.py"
SCRAPERS_DIR = HERE / "generated_scrapers"
RESULTS_DIR = HERE / "results"
DOWNLOADS_ROOT = RESULTS_DIR / "downloads"
SUMMARY_PATH = RESULTS_DIR / "_first5_summary.json"
LOG_PATH = RESULTS_DIR / "_first5_log.txt"

CSV_PATH = Path(r"C:\Users\Victus\Downloads\publications_updated.csv")

PYTHON = sys.executable

GEN_TIMEOUT = 240   # seconds
RUN_TIMEOUT = 240   # seconds


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def domain_safe(url: str) -> str:
    return urlparse(url).netloc.replace(".", "_") or "scraper"


def run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    # Force UTF-8 in the child so Windows cp1252 doesn't choke on emoji
    # (e.g. the validator prints a checkmark).
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace", env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + f"\nTIMEOUT after {timeout}s"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    SCRAPERS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")  # reset

    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    urls = [r["url"] for r in rows[500:502]]

    summary = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "results": []}
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for i, url in enumerate(urls, 1):
        entry = {"index": i, "url": url, "phase": None,
                 "generate": None, "execute": None}
        log(f"=== URL {i}/{len(urls)}: {url}")

        # Step 1: generate (skip if a scraper already exists on disk; this
        # lets us re-run cheaply after fixing executor-side issues without
        # paying for another LLM call).
        entry["phase"] = "generate"
        scraper_path = SCRAPERS_DIR / f"scraper_{domain_safe(url)}.py"

        if scraper_path.exists():
            log(f"  generate: REUSED existing {scraper_path.name}")
            entry["generate"] = {
                "ok": True, "returncode": 0, "elapsed_s": 0.0,
                "scraper_path": str(scraper_path),
                "stdout_tail": "(reused existing scraper)", "stderr_tail": "",
                "reused": True,
            }
            gen_ok = True
        else:
            t0 = time.time()
            rc, out, err = run(
                [PYTHON, str(GEN), "generate", url, "--hardened"],
                cwd=HERE, timeout=GEN_TIMEOUT,
            )
            gen_elapsed = time.time() - t0
            gen_ok = (rc == 0) and scraper_path.is_file()
            entry["generate"] = {
                "ok": gen_ok,
                "returncode": rc,
                "elapsed_s": round(gen_elapsed, 1),
                "scraper_path": str(scraper_path) if scraper_path.is_file() else None,
                "stdout_tail": out[-2000:],
                "stderr_tail": err[-2000:],
            }
            log(f"  generate: rc={rc} ok={gen_ok} elapsed={gen_elapsed:.1f}s "
                f"file={scraper_path.name if gen_ok else 'MISSING'}")

        if not gen_ok:
            summary["results"].append(entry)
            SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            continue

        # Step 2: execute (use 'execute' to skip extra validation noise; the
        # validator already ran inside generate's syntax check, and 'run' adds
        # a second validate pass).
        entry["phase"] = "execute"
        per_url_dl = DOWNLOADS_ROOT / domain_safe(url)
        per_url_dl.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        rc2, out2, err2 = run(
            [PYTHON, str(EXE), "run", str(scraper_path), url,
             "--keep-downloads", str(per_url_dl)],
            cwd=HERE, timeout=RUN_TIMEOUT,
        )
        exec_elapsed = time.time() - t0
        metadata_files = sorted(
            p.name for p in per_url_dl.iterdir()
            if p.is_file() and p.name.startswith("tenders") and p.suffix == ".json"
        )
        files = sorted(
            p.name for p in per_url_dl.iterdir()
            if p.is_file() and p.name not in metadata_files
        )
        entry["execute"] = {
            "returncode": rc2,
            "elapsed_s": round(exec_elapsed, 1),
            "downloads_dir": str(per_url_dl),
            "files_kept": files,
            "metadata_files": metadata_files,
            "n_files": len(files),
            "stdout_tail": out2[-3000:],
            "stderr_tail": err2[-2000:],
        }
        log(f"  execute:  rc={rc2} elapsed={exec_elapsed:.1f}s files={len(files)}")

        summary["results"].append(entry)
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    summary["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log("ALL DONE")


if __name__ == "__main__":
    main()
