"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { postJSON } from "@/lib/api";

export default function JobSubmitForm() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const urls = text
      .split(/\s+/)
      .map((u) => u.trim())
      .filter(Boolean);

    if (urls.length === 0) {
      setError("Paste at least one URL.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const job = await postJSON<{ id: string }>("/jobs", { urls });
      router.push(`/jobs/${job.id}`);
    } catch (e: any) {
      setError(e?.message || "submission failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={`Paste one URL per line\nhttps://www.evergabe-online.de/tenderdetails.html?...\nhttps://www.dtvp.de/Satellite/notice/...`}
        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
      />
      {error && <p className="text-sm text-rose-600">{error}</p>}
      <div className="flex justify-between items-center">
        <span className="text-xs text-slate-500">
          {text.split(/\s+/).filter(Boolean).length} URL(s)
        </span>
        <button onClick={submit} disabled={busy} className="btn-primary disabled:opacity-50">
          {busy ? "Submitting…" : "Start scraping"}
        </button>
      </div>
    </div>
  );
}
