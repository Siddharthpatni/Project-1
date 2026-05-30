"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import {
  Play, CheckCircle2, XCircle, AlertTriangle, ArrowLeft,
  Loader2, FlaskConical, SkipForward, Clock, RefreshCcw,
} from "lucide-react";

const SUITES = [
  { value: "all",      label: "All Tests",        desc: "Run the complete test suite" },
  { value: "phase1",   label: "Phase 1 — LLM",    desc: "Feedback loop, generator, prompts" },
  { value: "phase2",   label: "Phase 2 — CUA",    desc: "Computer-use agent actions" },
  { value: "phase3",   label: "Phase 3 — Pipeline", desc: "Cascade logic, fallback, registry" },
  { value: "platform", label: "Platform Classifier", desc: "URL / HTML fingerprinting" },
  { value: "document", label: "Document Validator",  desc: "File magic-byte detection" },
  { value: "route",    label: "Route & Deterministic", desc: "Route learner + DTVP builder" },
];

const STATUS_STYLES: Record<string, string> = {
  passed:  "text-emerald-700 bg-emerald-50 border-emerald-200",
  failed:  "text-rose-700 bg-rose-50 border-rose-200",
  error:   "text-orange-700 bg-orange-50 border-orange-200",
  skipped: "text-slate-500 bg-slate-50 border-slate-200",
};
const STATUS_ICONS: Record<string, any> = {
  passed:  CheckCircle2,
  failed:  XCircle,
  error:   AlertTriangle,
  skipped: SkipForward,
};

export default function TestsPage() {
  const [suite,   setSuite]   = useState("all");
  const [running, setRunning] = useState(false);
  const [result,  setResult]  = useState<any | null>(null);
  const [error,   setError]   = useState<string | null>(null);

  const run = async () => {
    setRunning(true); setResult(null); setError(null);
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
      setRunning(false);
    }
  };

  const passRate = result ? Math.round((result.passed / Math.max(result.total, 1)) * 100) : 0;

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Dashboard
      </Link>

      <header className="border-b border-slate-100 pb-5">
        <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
          <FlaskConical className="w-7 h-7 text-indigo-600" /> Test Runner
        </h1>
        <p className="text-slate-500 mt-1 text-sm">
          Execute the backend pytest suite from the UI. Results include per-test status, duration, and error output.
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
                className={`text-left p-3 rounded-xl border transition-all ${
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
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Running tests…</>
              : <><Play className="w-4 h-4" /> Run {SUITES.find(s=>s.value===suite)?.label}</>}
          </button>
          {result && (
            <button onClick={() => { setResult(null); setError(null); }} className="btn-secondary text-xs gap-1.5">
              <RefreshCcw className="w-3.5 h-3.5" /> Clear
            </button>
          )}
          <span className="text-xs text-slate-400">Timeout: 120s</span>
        </div>
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 text-sm text-rose-700">
          <p className="font-bold mb-1">Test runner error</p>
          <p>{error}</p>
        </div>
      )}

      {result && (
        <>
          {/* Summary bar */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: "Total",   value: result.total,   color: "text-slate-700" },
              { label: "Passed",  value: result.passed,  color: "text-emerald-600" },
              { label: "Failed",  value: result.failed,  color: "text-rose-600" },
              { label: "Errors",  value: result.errors,  color: "text-orange-600" },
              { label: "Skipped", value: result.skipped, color: "text-slate-500" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-2xl font-extrabold ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Pass rate bar */}
          <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
            <div className="flex justify-between text-xs font-semibold text-slate-600 mb-2">
              <span>Pass Rate</span>
              <span className="flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                {result.duration_seconds.toFixed(2)}s
                <span className={`ml-2 ${passRate === 100 ? "text-emerald-600" : passRate >= 80 ? "text-amber-600" : "text-rose-600"}`}>
                  {passRate}%
                </span>
              </span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-3 overflow-hidden">
              <div
                className={`h-3 rounded-full transition-all duration-500 ${passRate === 100 ? "bg-emerald-500" : passRate >= 80 ? "bg-amber-500" : "bg-rose-500"}`}
                style={{ width: `${passRate}%` }}
              />
            </div>
          </div>

          {/* Per-test results */}
          {result.cases?.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
              <div className="px-6 py-3.5 border-b border-slate-100 bg-slate-50">
                <p className="text-xs font-bold text-slate-600">{result.cases.length} test cases</p>
              </div>
              <div className="divide-y divide-slate-100 max-h-96 overflow-y-auto custom-scrollbar">
                {result.cases.map((c: any, i: number) => {
                  const Icon = STATUS_ICONS[c.status] ?? AlertTriangle;
                  const cls  = STATUS_STYLES[c.status] ?? STATUS_STYLES.skipped;
                  return (
                    <div key={i} className="px-5 py-3 space-y-1.5">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <Icon className={`w-4 h-4 flex-shrink-0 ${cls.split(" ")[0]}`} />
                          <code className="text-xs font-mono text-slate-700 truncate">{c.name}</code>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className="text-[10px] font-mono text-slate-400">{c.duration_ms}ms</span>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${cls}`}>{c.status}</span>
                        </div>
                      </div>
                      {c.error && (
                        <pre className="bg-slate-950 text-rose-300 text-[10px] font-mono p-2.5 rounded-lg overflow-x-auto custom-scrollbar whitespace-pre-wrap break-all max-h-24">
                          {typeof c.error === "string" ? c.error : JSON.stringify(c.error, null, 2)}
                        </pre>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Raw output */}
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <div className="px-6 py-3.5 border-b border-slate-100 bg-slate-50">
              <p className="text-xs font-bold text-slate-600">Raw pytest output</p>
            </div>
            <pre className="bg-slate-950 text-slate-200 text-[10px] font-mono p-5 overflow-x-auto custom-scrollbar whitespace-pre-wrap max-h-72">
              {result.raw_output || "(no output)"}
            </pre>
          </div>
        </>
      )}
    </div>
  );
}
