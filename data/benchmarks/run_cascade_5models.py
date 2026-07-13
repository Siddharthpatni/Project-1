#!/usr/bin/env python3
"""
Full-cascade benchmark across 5 models.

Runs the WHOLE pipeline (EXISTING → DETERMINISTIC → ADAPTIVE → LLM_GENERATED →
LEARNED_ROUTE → CUA → MANUAL) once per model over the 20 benchmark domains,
using force_model to pin the LLM used by the LLM_GENERATED step.

Per-model isolation (only the 20 test domains are touched):
  * delete LLM-generated scrapers + clear learned_route/cua_hint for the 20
    domains, so a scraper one model generates doesn't make the next model
    "win" for free via the EXISTING strategy;
  * flush the per-domain Redis circuit-breaker (vcb:*) and rate-limiter (vrl:*)
    keys, so cross-job failures don't falsely trip a domain off for later runs.

Manual/delegate scrapers (source='manual') are left intact — they are a shared,
model-independent baseline.

Runs sequentially (one job to completion before the next) to avoid hammering the
same domains from five jobs at once. Writes cascade_5models_results.json.
"""
from __future__ import annotations
import json, subprocess, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = "http://localhost:8000"
DS = [json.loads(l) for l in (HERE / "bench_20_domains.jsonl").read_text().splitlines() if l.strip()]
URLS = [d["url"] for d in DS]
DOMAINS = [d["notes"] for d in DS]
URL_DOMAIN = {d["url"]: d["notes"] for d in DS}

MODELS = [
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4.1-nano",
    "deepseek/deepseek-chat-v3-0324",
    "openai/gpt-4o-mini",
    "meta-llama/llama-4-maverick",
]
OUT = HERE / "cascade_5models_results.json"


def _dc(*args) -> str:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT,
                          capture_output=True, text=True).stdout


def reset_state():
    """Per-model isolation: drop benchmark-generated LLM scrapers/routes + flush Redis breakers."""
    doms = ",".join("'" + d.replace("'", "''") + "'" for d in DOMAINS)
    sql = (
        f"DELETE FROM scraper_templates WHERE domain IN ({doms}) AND source='llm'; "
        f"UPDATE scraper_templates SET learned_route=NULL, cua_hint=NULL WHERE domain IN ({doms});"
    )
    _dc("exec", "-T", "postgres", "sh", "-c",
        f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "{sql}"')
    # flush per-domain circuit breaker + rate limiter keys (best-effort)
    _dc("exec", "-T", "redis", "sh", "-c",
        "redis-cli --scan --pattern 'vcb:*' | xargs -r redis-cli del >/dev/null 2>&1; "
        "redis-cli --scan --pattern 'vrl:*' | xargs -r redis-cli del >/dev/null 2>&1; "
        "redis-cli --scan --pattern 'vergabepilot:domain_llm_lock:*' | xargs -r redis-cli del >/dev/null 2>&1; true")


def submit(model: str) -> str:
    body = json.dumps({"urls": URLS, "force_model": model,
                       "submitted_by": f"FULL-CASCADE × {model.split('/')[-1]}"}).encode()
    req = urllib.request.Request(f"{API}/api/jobs", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=30))["id"]


def poll(job_id: str, timeout=5400) -> dict:
    start = time.time()
    while True:
        try:
            with urllib.request.urlopen(f"{API}/api/jobs/{job_id}", timeout=20) as r:
                j = json.load(r)
        except Exception:
            time.sleep(20); continue
        items = j.get("items", [])
        term = [i for i in items if i["status"] in ("success", "failed")]
        ok = sum(1 for i in items if i["status"] == "success")
        el = int(time.time() - start)
        print(f"    [{el:4d}s] {j['status']:<8} done={len(term)}/{len(items)} ok={ok}", flush=True)
        if items and len(term) == len(items):
            return j
        if el > timeout:
            print("    TIMEOUT", flush=True); return j
        time.sleep(45)


def main():
    results = {}
    for n, model in enumerate(MODELS, 1):
        print(f"\n===== [{n}/5] {model} =====", flush=True)
        print("  resetting per-domain state...", flush=True)
        reset_state()
        jid = submit(model)
        print(f"  job {jid} submitted; polling...", flush=True)
        j = poll(jid)
        items = j.get("items", [])
        per = []
        for it in items:
            per.append({
                "domain": it.get("domain"), "url": it.get("url"),
                "success": it.get("status") == "success",
                "strategy": it.get("strategy") if it.get("status") == "success" else None,
                "failure_category": it.get("failure_category"),
            })
        ok = sum(1 for p in per if p["success"])
        results[model] = {"job_id": jid, "status": j.get("status"),
                          "success": ok, "total": len(items), "items": per}
        OUT.write_text(json.dumps(results, indent=2))
        print(f"  >>> {model.split('/')[-1]}: {ok}/{len(items)} success", flush=True)

    print("\n===== SUMMARY =====", flush=True)
    for m in MODELS:
        r = results[m]
        print(f"  {m.split('/')[-1]:<26} {r['success']}/{r['total']}", flush=True)
    print(f"\nwrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
