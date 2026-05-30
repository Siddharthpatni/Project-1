"use client";

import { useState, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import { postJSON, postMultipart } from "@/lib/api";
import { Upload, Link as LinkIcon, FileText, X } from "lucide-react";

export default function JobSubmitForm() {
  const router = useRouter();
  const [text, setText]           = useState("");
  const [busy, setBusy]           = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [mode, setMode]           = useState<"manual" | "file">("manual");
  const [file, setFile]           = useState<File | null>(null);
  const [forceStrategy, setForceStrategy] = useState("");
  const [forceModel, setForceModel]       = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const urlCount = useMemo(
    () => text.split(/\s+/).filter((u) => u.startsWith("http")).length,
    [text]
  );

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "manual") {
        const urls = text.split(/\s+/).map((u) => u.trim()).filter(Boolean);
        if (!urls.length) { setError("Paste at least one URL."); return; }
        const body: any = { urls };
        if (forceStrategy) body.force_strategy = forceStrategy;
        if (forceModel)    body.force_model    = forceModel;
        const job = await postJSON<{ id: string }>("/jobs", body);
        router.push(`/jobs/${job.id}`);
      } else {
        if (!file) { setError("Please select a file."); return; }
        const formData = new FormData();
        formData.append("file", file);
        const query = new URLSearchParams();
        if (forceStrategy) query.append("force_strategy", forceStrategy);
        if (forceModel)    query.append("force_model", forceModel);
        const url = `/jobs/upload${query.toString() ? `?${query}` : ""}`;
        const job = await postMultipart<{ id: string }>(url, formData);
        router.push(`/jobs/${job.id}`);
      }
    } catch (e: any) {
      setError(e?.message || "Submission failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">

      {/* Mode switcher */}
      <div className="flex p-1 bg-slate-100 rounded-xl gap-1">
        {(["manual", "file"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-sm font-semibold rounded-lg transition-all ${
              mode === m
                ? "bg-white shadow-sm text-indigo-700 border border-slate-200"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {m === "manual" ? <LinkIcon className="w-4 h-4" /> : <Upload className="w-4 h-4" />}
            {m === "manual" ? "Manual URLs" : "Excel / CSV"}
          </button>
        ))}
      </div>

      {/* Input area */}
      {mode === "manual" ? (
        <div className="relative">
          <textarea
            value={text}
            onChange={(e) => { setText(e.target.value); setError(null); }}
            rows={5}
            placeholder={"Paste one URL per line\nhttps://www.evergabe-online.de/tenderdetails.html?...\nhttps://www.dtvp.de/Satellite/notice/..."}
            className="form-input font-mono resize-none"
          />
          {urlCount > 0 && (
            <span className="absolute bottom-2.5 right-3 text-[10px] font-bold text-indigo-600 bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded-full pointer-events-none">
              {urlCount} URL{urlCount !== 1 ? "s" : ""} detected
            </span>
          )}
          <button
            onClick={() => setText("https://www.dtvp.de/Satellite/public/company/project/CXP9YJJYG29/de/documents\nhttps://www.evergabe-online.de/tenderdetails.html?id=858550\nhttps://www.subreport.de/E69184189")}
            className="text-xs text-indigo-600 hover:underline mt-1.5 block"
            type="button"
          >
            Load example URLs
          </button>
        </div>
      ) : (
        <div
          onClick={() => fileInputRef.current?.click()}
          className="border-2 border-dashed border-slate-200 rounded-xl p-8 flex flex-col items-center justify-center gap-3 cursor-pointer hover:border-indigo-300 hover:bg-indigo-50/30 transition-all group"
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={(e) => { setFile(e.target.files?.[0] || null); setError(null); }}
            className="hidden"
            accept=".csv,.xlsx,.xls"
          />
          <div className="p-3 bg-slate-100 rounded-full group-hover:bg-indigo-100 transition-all">
            <FileText className="w-6 h-6 text-slate-400 group-hover:text-indigo-600 transition-colors" />
          </div>
          <div className="text-center">
            <p className="text-sm font-semibold text-slate-800">
              {file ? file.name : "Click to select or drag and drop"}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">CSV or Excel (.xlsx, .xls) — URL column auto-detected</p>
          </div>
          {file && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="text-xs text-rose-600 flex items-center gap-1 hover:underline"
            >
              <X className="w-3 h-3" /> Remove
            </button>
          )}
        </div>
      )}

      {/* Options */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Strategy</label>
          <select
            value={forceStrategy}
            onChange={(e) => setForceStrategy(e.target.value)}
            className="form-select"
          >
            <option value="">Auto cascade (recommended)</option>
            <option value="manual_scraper">Manual scraper (Phase 0)</option>
            <option value="existing_scraper">Cached scraper (registry)</option>
            <option value="deterministic_template">Deterministic template</option>
            <option value="llm_generated_scraper">LLM generation (Phase 1)</option>
            <option value="computer_use_agent">CUA agent (Phase 2)</option>
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">LLM Model</label>
          <select
            value={forceModel}
            onChange={(e) => setForceModel(e.target.value)}
            className="form-select"
          >
            <option value="">Default (env config)</option>
            <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
            <option value="google/gemini-2.5-flash-lite">Gemini 2.5 Flash Lite</option>
            <option value="google/gemini-2.5-pro">Gemini 2.5 Pro</option>
            <option value="openai/gpt-4o">GPT-4o</option>
            <option value="openai/gpt-4o-mini">GPT-4o Mini</option>
            <option value="anthropic/claude-sonnet-4">Claude Sonnet 4</option>
            <option value="anthropic/claude-haiku-4.5">Claude Haiku 4.5</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 p-3 rounded-xl flex items-center gap-2">
          <span className="text-rose-500">⚠</span> {error}
        </div>
      )}

      {/* Footer actions */}
      <div className="flex justify-between items-center bg-slate-50 -mx-6 px-6 py-4 border-t border-slate-100 rounded-b-xl -mb-6">
        <span className="text-xs text-slate-400">
          {mode === "manual"
            ? urlCount > 0 ? `${urlCount} URL${urlCount !== 1 ? "s" : ""} ready to submit` : "No URLs detected yet"
            : file ? `${file.name} ready` : "No file selected"}
        </span>
        <button
          onClick={submit}
          disabled={busy || (mode === "manual" ? urlCount === 0 : !file)}
          className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? "Submitting…" : "Start Scraping"}
        </button>
      </div>
    </div>
  );
}
