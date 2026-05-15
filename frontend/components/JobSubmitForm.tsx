import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { postJSON, postMultipart } from "@/lib/api";
import { Upload, Link as LinkIcon, FileText } from "lucide-react";

export default function JobSubmitForm() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"manual" | "file">("manual");
  const [file, setFile] = useState<File | null>(null);
  const [forceStrategy, setForceStrategy] = useState<string>("");
  const [forceModel, setForceModel] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "manual") {
        const urls = text
          .split(/\s+/)
          .map((u) => u.trim())
          .filter(Boolean);

        if (urls.length === 0) {
          setError("Paste at least one URL.");
          setBusy(false);
          return;
        }

        const body: any = { urls };
        if (forceStrategy) body.force_strategy = forceStrategy;
        if (forceModel) body.force_model = forceModel;
        const job = await postJSON<{ id: string }>("/jobs", body);
        router.push(`/jobs/${job.id}`);
      } else {
        if (!file) {
          setError("Please select a file.");
          setBusy(false);
          return;
        }
        const formData = new FormData();
        formData.append("file", file);
        let url = "/jobs/upload";
        const query = new URLSearchParams();
        if (forceStrategy) query.append("force_strategy", forceStrategy);
        if (forceModel) query.append("force_model", forceModel);
        if (query.toString()) url += `?${query.toString()}`;
        const job = await postMultipart<{ id: string }>(url, formData);
        router.push(`/jobs/${job.id}`);
      }
    } catch (e: any) {
      setError(e?.message || "submission failed");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Tab Switcher */}
      <div className="flex p-1 bg-slate-100 rounded-lg">
        <button
          onClick={() => setMode("manual")}
          className={`flex-1 flex items-center justify-center gap-2 py-2 text-sm font-medium rounded-md transition-all ${
            mode === "manual" ? "bg-white shadow-sm text-brand-700" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          <LinkIcon className="w-4 h-4" />
          Manual URLs
        </button>
        <button
          onClick={() => setMode("file")}
          className={`flex-1 flex items-center justify-center gap-2 py-2 text-sm font-medium rounded-md transition-all ${
            mode === "file" ? "bg-white shadow-sm text-brand-700" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          <Upload className="w-4 h-4" />
          Excel / CSV
        </button>
      </div>

      {mode === "manual" ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          placeholder={`Paste one URL per line\nhttps://www.evergabe-online.de/tenderdetails.html?...\nhttps://www.dtvp.de/Satellite/notice/...`}
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all"
        />
      ) : (
        <div 
          onClick={() => fileInputRef.current?.click()}
          className="border-2 border-dashed border-slate-300 rounded-lg p-8 flex flex-col items-center justify-center gap-3 cursor-pointer hover:border-brand-500 hover:bg-brand-50 transition-all group"
        >
          <input 
            type="file" 
            ref={fileInputRef} 
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="hidden" 
            accept=".csv,.xlsx,.xls"
          />
          <div className="p-3 bg-slate-100 rounded-full group-hover:bg-brand-100 transition-all">
            <FileText className="w-6 h-6 text-slate-500 group-hover:text-brand-600" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-slate-900">
              {file ? file.name : "Click to select or drag and drop"}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Supports CSV, Excel (.xlsx, .xls)
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-slate-700">Strategy (optional)</label>
          <select 
            value={forceStrategy} 
            onChange={(e) => setForceStrategy(e.target.value)}
            className="px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
          >
            <option value="">Auto (Cascaded pipeline)</option>
            <option value="manual_scraper">Phase 0: Manual Scraper</option>
            <option value="existing_scraper">Phase 3: Existing Scraper</option>
            <option value="deterministic_template">Phase 3: Deterministic Template</option>
            <option value="llm_generated_scraper">Phase 1: Generate New LLM Scraper</option>
            <option value="computer_use_agent">Phase 2: Computer-Use Agent</option>
          </select>
          <p className="text-xs text-slate-500">Auto cascade: Manual → Existing → Deterministic → LLM → CUA.</p>
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-slate-700">LLM Model (optional)</label>
          <select 
            value={forceModel} 
            onChange={(e) => setForceModel(e.target.value)}
            className="px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
          >
            <option value="">Default (From Environment)</option>
            <option value="anthropic/claude-sonnet-4.5">Claude 3.5 Sonnet</option>
            <option value="anthropic/claude-haiku-4.5">Claude 3.5 Haiku</option>
            <option value="openai/gpt-4o">GPT-4o</option>
            <option value="openai/gpt-4o-mini">GPT-4o Mini</option>
            <option value="google/gemini-2.5-pro">Gemini 2.5 Pro</option>
            <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
            <option value="google/gemini-2.5-flash-lite">Gemini 2.5 Flash Lite</option>
          </select>
          <p className="text-xs text-slate-500">Select which LLM to use if the pipeline reaches Phase 1 or Phase 2.</p>
        </div>
      </div>

      {error && <p className="text-sm text-rose-600 bg-rose-50 p-2 rounded border border-rose-100">{error}</p>}
      
      <div className="flex justify-between items-center bg-slate-50 -mx-6 -mb-6 px-6 py-4 rounded-b-xl border-t border-slate-100">
        <span className="text-xs text-slate-500">
          {mode === "manual" 
            ? `${text.split(/\s+/).filter(Boolean).length} URL(s) detected`
            : file ? "Ready to upload" : "No file selected"
          }
        </span>
        <button onClick={submit} disabled={busy} className="btn-primary px-6 disabled:opacity-50">
          {busy ? "Submitting…" : "Start scraping"}
        </button>
      </div>
    </div>
  );
}
