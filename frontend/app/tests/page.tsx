"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import {
  Play, CheckCircle2, XCircle, AlertTriangle, ArrowLeft,
  Loader2, FlaskConical, SkipForward, Clock, RefreshCcw,
  Terminal, ChevronDown, ChevronRight, BarChart2,
} from "lucide-react";

const SUITES = [
  { value: "all",      label: "All Tests",             desc: "Run the complete test suite" },
  { value: "phase1",   label: "Phase 1 — LLM",         desc: "Feedback loop, generator, prompts" },
  { value: "phase2",   label: "Phase 2 — CUA",          desc: "Computer-use agent actions" },
  { value: "phase3",   label: "Phase 3 — Pipeline",     desc: "Cascade logic, fallback, registry" },
  { value: "platform", label: "Platform Classifier",    desc: "URL / HTML fingerprinting" },
  { value: "document", label: "Document Validator",     desc: "File magic-byte detection" },
  { value: "route",    label: "Route & Deterministic",  desc: "Route learner + DTVP builder" },
];

const STATUS_STYLES: Record<string, string> = {
  passed:  "text-emerald-700 bg-emerald-50 border-emerald-200",
  failed:  "text-rose-700   bg-rose-50    border-rose-200",
  error:   "text-orange-700 bg-orange-50  border-orange-200",
  skipped: "text-slate-500  bg-slate-50   border-slate-200",
};
const STATUS_ICONS: Record<string, any> = {
  passed:  CheckCircle2,
  failed:  XCircle,
  error:   AlertTriangle,
  skipped: SkipForward,
};

function TestCaseRow({ c }: { c: any }) {
  const [open, setOpen] = useState(false);
  const Icon = STATUS_ICONS[c.status] ?? AlertTriangle;
  const cls  = STATUS_STYLES[c.status] ?? STATUS_STYLES.skipped;
  const hasError = !!c.error;

  return (
    <div className="border-b border-slate-100 last:border-0">
      <div
        className={`flex items-center gap-3 px-5 py-3 hover:bg-slate-50/50 transition-colors ${hasError ? "cursor-pointer" : ""}`}
        onClick={() => hasError && setOpen(v => !v)}
      >
        <Icon className={`w-4 h-4 flex-shrink-0 ${cls.split(" ")[0]}`} />
        <code className="flex-1 text-xs font-mono text-slate-700 truncate min-w-0">{c.name}</code>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[10px] font-mono text-slate-400">{c.duration_ms}ms</span>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${cls}`}>{c.status}</span>
          {hasError && (
            <button className="text-slate-400">
              {open ? <ChevronDown className="w-3.5 h-3.5"/> : <ChevronRight className="w-3.5 h-3.5"/>}
            </button>
          )}
        </div>
      </div>
      {open && hasError && (
        <div className="mx-5 mb-3">
          <pre className="bg-slate-950 text-rose-300 text-[10px] font-mono p-3 rounded-xl overflow-x-auto whitespace-pre-wrap break-all max-h-48 custom-scrollbar">
            {typeof c.error === "string" ? c.error : JSON.stringify(c.error, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function TestsPage() {
  const [suite,   setSuite]   = useState("all");
  const [running, setRunning] = useState(false);
  const [result,  setResult]  = useState<any | null>(null);
  const [error,   setError]   = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [showRaw, setShowRaw] = useState(false);

  const run = async () => {
    setRunning(true); setResult(null); setError(null); setElapsed(0);

    // Tick elapsed timer
    const tick = setInterval(() => setElapsed(s => s + 1), 1000);

    try {
      const r = await fetch(api("/tests/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suite }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setResult(await r.json());
    } catch (e: any) {
      setError(e?.message ?? "Test run failed");
    } finally {
      clearInterval(tick);
      setRunning(false);
    }
  };

  const passRate = result ? Math.round((result.passed / Math.max(result.total, 1)) * 100) : 0;
  const selectedSuite = SUITES.find(s => s.value === suite);

  return (
    <div className="space-y-6">
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Dashboard
      </Link>

      <header className="border-b border-slate-100 pb-5">
        <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
          <FlaskConical className="w-7 h-7 text-indigo-600" /> Test Runner
        </h1>
        <p className="text-slate-500 mt-1 text-sm">
          Execute the backend pytest suite from the UI. Results include per-test status, duration, and full error output.
        </p>
      </header>

      {/* Suite picker + run button */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-5">
        <div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">Select Test Suite</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
            {SUITES.map(s => (
              <button
                key={s.value}
                onClick={() => setSuite(s.value)}
                disabled={running}
                className={`text-left p-3 rounded-xl border transition-all disabled:opacity-40 ${
                  suite === s.value
                    ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                    : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-300"
                }`}
              >
                <p className="text-xs font-bold">{s.label}</p>
                <p className="text-[10px] text-slate-400 mt-0.5">{s.desc}</p>
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-2 border-t border-slate-100">
          <button
            onClick={run}
            disabled={running}
            className="btn-primary gap-2 disabled:opacity-60"
          >
            {running
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Running…</>
              : <><Play className="w-4 h-4" /> Run {selectedSuite?.label}</>}
          </button>
          {result && (
            <button onClick={() => { setResult(null); setError(null); setElapsed(0); }} className="btn-secondary text-xs gap-1.5">
              <RefreshCcw className="w-3.5 h-3.5" /> Clear Results
            </button>
          )}
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <Clock className="w-3.5 h-3.5" />Timeout: 120s
          </span>
        </div>
      </div>

      {/* Running panel — live elapsed timer + status */}
      {running && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-2xl p-6 space-y-4">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-indigo-600 animate-spin flex-shrink-0" />
            <div>
              <p className="text-sm font-bold text-indigo-800">Running {selectedSuite?.label}…</p>
              <p className="text-xs text-indigo-600 mt-0.5">{selectedSuite?.desc} · Tests are running inside the container</p>
            </div>
            <span className="ml-auto font-mono text-lg font-bold text-indigo-700">{elapsed}s</span>
          </div>
          <div className="w-full bg-indigo-100 rounded-full h-1.5 overflow-hidden">
            <div
              className="h-1.5 rounded-full bg-indigo-500 transition-all duration-1000"
              style={{ width: `${Math.min((elapsed / 120) * 100, 95)}%` }}
            />
          </div>
          <div className="bg-slate-900 rounded-xl p-4 font-mono text-[10px] text-slate-400 space-y-1">
            <p className="text-emerald-400">$ pytest {_SUITE_PATHS[suite]} --tb=short -q --json-report</p>
            <div className="flex items-center gap-2 text-slate-500">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
              <span>Collecting and executing tests… ({elapsed}s elapsed)</span>
            </div>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 flex items-start gap-3">
          <XCircle className="w-5 h-5 text-rose-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-rose-800">Test runner error</p>
            <p className="text-xs text-rose-700 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* ── Results ── */}
      {result && (
        <div className="space-y-5">
          {/* Summary strip */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: "Total",   value: result.total,   color: "text-slate-700",   bg: "bg-slate-50" },
              { label: "Passed",  value: result.passed,  color: "text-emerald-600", bg: "bg-emerald-50" },
              { label: "Failed",  value: result.failed,  color: "text-rose-600",    bg: "bg-rose-50" },
              { label: "Errors",  value: result.errors,  color: "text-orange-600",  bg: "bg-orange-50" },
              { label: "Skipped", value: result.skipped, color: "text-slate-500",   bg: "bg-slate-50" },
            ].map(({ label, value, color, bg }) => (
              <div key={label} className={`${bg} border border-slate-200 rounded-xl p-4 text-center shadow-sm`}>
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-2xl font-extrabold ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Pass rate bar */}
          <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
            <div className="flex justify-between text-xs font-semibold text-slate-600 mb-2">
              <span className="flex items-center gap-1.5">
                <BarChart2 className="w-3.5 h-3.5 text-slate-400" />Pass Rate
              </span>
              <span className="flex items-center gap-2">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                {result.duration_seconds?.toFixed(2)}s
                <span className={`font-bold ml-1 ${passRate === 100 ? "text-emerald-600" : passRate >= 80 ? "text-amber-600" : "text-rose-600"}`}>
                  {passRate}%
                </span>
              </span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-3 overflow-hidden">
              <div
                className={`h-3 rounded-full transition-all duration-700 ${passRate === 100 ? "bg-emerald-500" : passRate >= 80 ? "bg-amber-500" : "bg-rose-500"}`}
                style={{ width: `${passRate}%` }}
              />
            </div>
          </div>

          {/* Per-test results */}
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <div className="px-6 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
              <p className="text-xs font-bold text-slate-600 flex items-center gap-1.5">
                <FlaskConical className="w-3.5 h-3.5 text-indigo-500" />
                {result.cases?.length > 0 ? `${result.cases.length} test cases` : "No per-case data (raw output below)"}
              </p>
              <div className="flex items-center gap-2">
                {result.failed > 0 && <span className="text-[10px] font-bold text-rose-600 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full">{result.failed} failed</span>}
                {result.passed > 0 && <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">{result.passed} passed</span>}
              </div>
            </div>

            {(result.cases?.length ?? 0) > 0 ? (
              <div className="divide-y divide-slate-100 max-h-[480px] overflow-y-auto custom-scrollbar">
                {result.cases.map((c: any, i: number) => <TestCaseRow key={i} c={c} />)}
              </div>
            ) : (
              <div className="px-6 py-4 text-xs text-slate-400 italic">
                No structured per-test data available — check the raw output below.
              </div>
            )}
          </div>

          {/* Raw pytest output */}
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <button
              className="w-full px-6 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between hover:bg-slate-100 transition-colors"
              onClick={() => setShowRaw(v => !v)}
            >
              <p className="text-xs font-bold text-slate-600 flex items-center gap-1.5">
                <Terminal className="w-3.5 h-3.5 text-slate-500" />Raw pytest output
              </p>
              {showRaw ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
            </button>
            {showRaw && (
              <pre className="bg-slate-950 text-slate-200 text-[10px] font-mono p-5 overflow-x-auto custom-scrollbar whitespace-pre-wrap max-h-96">
                {result.raw_output || "(no output captured)"}
              </pre>
            )}
            {!showRaw && (
              <div className="px-6 py-3 text-[10px] text-slate-400 font-mono truncate bg-slate-950">
                {(result.raw_output || "(no output)").split("\n")[0]}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Idle state — no result yet, not running */}
      {!running && !result && !error && (
        <div className="bg-white border border-dashed border-slate-200 rounded-2xl p-10 text-center space-y-3">
          <FlaskConical className="w-10 h-10 text-slate-300 mx-auto" />
          <p className="text-slate-500 font-semibold text-sm">Select a suite and click Run</p>
          <p className="text-slate-400 text-xs max-w-md mx-auto">
            Tests run inside the Docker container via pytest. Results include pass/fail per test case,
            duration, error traces, and the full raw output log.
          </p>
        </div>
      )}
    </div>
  );
}

// Helper for the running panel display only
const _SUITE_PATHS: Record<string, string> = {
  all:      "tests/",
  phase1:   "tests/test_phase1.py",
  phase2:   "tests/test_phase2.py",
  phase3:   "tests/test_phase3.py",
  platform: "tests/test_platform_classifier.py",
  document: "tests/test_document_validator.py",
  route:    "tests/test_route_and_deterministic.py",
};
