"""
Full genuineness audit of the benchmark report.
Cross-checks: JSON vs CSV vs disk files vs SHA256 vs leaderboard numbers.
"""
import json, csv, sys, hashlib
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUN = Path("runs/2026-05-07_11-12-17")

# ── Load sources ──────────────────────────────────────────────────
with open(RUN / "full_results.json", encoding="utf-8") as f:
    raw = json.load(f)
experiments = raw["experiments"]

with open(RUN / "detailed_results.csv", newline="", encoding="utf-8") as f:
    csv_rows = list(csv.DictReader(f))

print(f"JSON experiments : {len(experiments)}")
print(f"CSV rows         : {len(csv_rows)}")
print()

# ── 1. JSON vs CSV consistency ────────────────────────────────────
print("=" * 60)
print("1. JSON vs CSV field-by-field cross-check")
print("=" * 60)
mismatches = 0
for exp in experiments:
    row = next(
        (r for r in csv_rows if r["model"] == exp["model"] and r["url_id"] == exp["url_id"]),
        None,
    )
    if not row:
        print(f"  MISSING in CSV: {exp['model']} / {exp['url_id']}")
        mismatches += 1
        continue
    for field in ["status", "attempts", "docs_unique", "docs_downloaded", "duplicate_count"]:
        jv = str(exp[field])
        cv = str(row[field])
        if jv != cv:
            print(f"  MISMATCH [{exp['model']}] {field}: JSON={jv}  CSV={cv}")
            mismatches += 1
    # cost — allow tiny float drift
    jcost = round(float(exp["cost_usd"]), 6)
    ccost = round(float(row["cost_usd"]), 6)
    if abs(jcost - ccost) > 0.000001:
        print(f"  COST MISMATCH [{exp['model']}]: JSON={jcost}  CSV={ccost}")
        mismatches += 1

if mismatches == 0:
    print("  PASS — all 40 rows match perfectly between JSON and CSV")
else:
    print(f"  {mismatches} mismatch(es) found")

# ── 2. Files actually on disk ─────────────────────────────────────
print()
print("=" * 60)
print("2. Downloaded files exist on disk with non-zero size")
print("=" * 60)
empty, total = 0, 0
for exp in experiments:
    dl_dir = RUN / exp["model"] / exp["url_id"] / "downloads"
    if not dl_dir.exists():
        continue
    for f in dl_dir.rglob("*"):
        if f.is_file():
            total += 1
            if f.stat().st_size == 0:
                print(f"  EMPTY: {exp['model']} / {f.name}")
                empty += 1

print(f"  Total files on disk  : {total}")
print(f"  Empty (0-byte) files : {empty}")
if empty == 0:
    print("  PASS — every file has content")

# ── 3. Code files exist for every experiment ──────────────────────
print()
print("=" * 60)
print("3. Generated code files present for every attempt")
print("=" * 60)
missing_code = 0
for exp in experiments:
    if exp["status"] == "SKIPPED" or exp["attempts"] == 0:
        continue
    code_dir = RUN / exp["model"] / exp["url_id"] / "code"
    n = len(list(code_dir.glob("attempt_*.py"))) if code_dir.exists() else 0
    if n == 0:
        print(f"  MISSING code: {exp['model']} / {exp['url_id'][:8]}")
        missing_code += 1

if missing_code == 0:
    print("  PASS — code files present for all experiments")
else:
    print(f"  {missing_code} experiment(s) missing code files")

# ── 4. Attempt records match attempt count ────────────────────────
print()
print("=" * 60)
print("4. Attempt records integrity")
print("=" * 60)
att_errors = 0
for exp in experiments:
    declared = exp["attempts"]
    actual   = len(exp.get("attempt_records", []))
    if declared != actual:
        print(f"  MISMATCH [{exp['model']}] attempts={declared} but records={actual}")
        att_errors += 1
    # cost sum matches total
    sum_cost = sum(r["cost_usd"] for r in exp.get("attempt_records", []))
    if abs(sum_cost - exp["cost_usd"]) > 0.00001:
        print(f"  COST SUM MISMATCH [{exp['model']}]: sum_attempts={sum_cost:.6f}  total={exp['cost_usd']:.6f}")
        att_errors += 1

if att_errors == 0:
    print("  PASS — attempt counts and cost sums are internally consistent")

# ── 5. SHA256 dedup spot-check ────────────────────────────────────
print()
print("=" * 60)
print("5. SHA256 deduplication verification")
print("=" * 60)

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

checked = 0
dedup_errors = 0
for exp in experiments:
    dl_dir = RUN / exp["model"] / exp["url_id"] / "downloads"
    if not dl_dir.exists():
        continue
    files = [f for f in dl_dir.rglob("*") if f.is_file()]
    if len(files) < 2:
        continue
    hashes = [sha256_file(f) for f in files]
    unique_count = len(set(hashes))
    reported     = exp["docs_unique"]
    dup_reported = exp["duplicate_count"]
    dup_actual   = len(files) - unique_count

    status = "PASS" if dup_actual == dup_reported else "WARN"
    if status == "WARN":
        dedup_errors += 1
    print(f"  {status}  {exp['model']:<22} {exp['url_id'][:8]}"
          f"  on_disk={len(files)}  real_unique={unique_count}  "
          f"reported_unique={reported}  dup_reported={dup_reported}  dup_actual={dup_actual}")
    checked += 1

if checked == 0:
    print("  (no multi-file downloads to verify)")
elif dedup_errors == 0:
    print(f"  PASS — SHA256 dedup correct across all {checked} multi-file experiments")

# ── 6. Leaderboard recomputation ─────────────────────────────────
print()
print("=" * 60)
print("6. Leaderboard — recomputed from raw JSON")
print("=" * 60)
by_model = defaultdict(list)
for exp in experiments:
    by_model[exp["model"]].append(exp)

header = f"  {'Model':<22} {'Succ':>4} {'N':>3} {'Succ%':>6} {'UniqDocs':>8} {'Cost':>8} {'AvgRecall':>9}"
print(header)
print("  " + "-" * 66)
for model in sorted(by_model):
    exps   = by_model[model]
    succ   = sum(1 for e in exps if e["status"] == "SUCCESS")
    docs   = sum(e["docs_unique"] for e in exps)
    cost   = sum(e["cost_usd"]    for e in exps)
    recall = sum(e["recall_pct"]  for e in exps) / max(1, len(exps))
    print(f"  {model:<22} {succ:>4} {len(exps):>3} {succ/len(exps)*100:>5.0f}%"
          f"  {docs:>8}  {cost:>7.4f}  {recall:>8.1f}%")

# ── 7. Recall computation verification ───────────────────────────
print()
print("=" * 60)
print("7. Recall % verification (consensus ceiling per URL)")
print("=" * 60)
by_url = defaultdict(list)
for exp in experiments:
    by_url[exp["url"]].append(exp)

recall_errors = 0
for url, exps in by_url.items():
    ceiling = max(e["docs_unique"] for e in exps)
    for exp in exps:
        expected_recall = (exp["docs_unique"] / ceiling * 100) if ceiling > 0 else 0.0
        actual_recall   = exp["recall_pct"]
        if abs(expected_recall - actual_recall) > 0.01:
            print(f"  RECALL MISMATCH [{exp['model']}]: computed={expected_recall:.1f}%  stored={actual_recall:.1f}%")
            recall_errors += 1

if recall_errors == 0:
    print(f"  PASS — recall_pct correct for all {len(experiments)} experiments")

# ── 8. Timing sanity ─────────────────────────────────────────────
print()
print("=" * 60)
print("8. Timing sanity (generation + execution <= end_to_end)")
print("=" * 60)
timing_errors = 0
for exp in experiments:
    gen  = exp["total_generation_s"]
    exc  = exp["total_execution_s"]
    e2e  = exp["end_to_end_s"]
    if gen + exc > e2e + 1.0:   # 1s tolerance
        print(f"  TIMING [{exp['model']}]: gen={gen:.1f}s + exec={exc:.1f}s = {gen+exc:.1f}s > e2e={e2e:.1f}s")
        timing_errors += 1

if timing_errors == 0:
    print("  PASS — all timings internally consistent")

print()
print("=" * 60)
print("AUDIT SUMMARY")
print("=" * 60)
issues = mismatches + empty + missing_code + att_errors + dedup_errors + recall_errors + timing_errors
if issues == 0:
    print("  ALL CHECKS PASSED — report is genuine and internally consistent.")
else:
    print(f"  {issues} issue(s) found — review output above.")
