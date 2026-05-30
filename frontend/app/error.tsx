"use client";

import { useEffect } from "react";
import { ShieldAlert, RefreshCcw } from "lucide-react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Vergabepilot.AI — unhandled error:", error);
  }, [error]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="bg-white border border-rose-200 rounded-2xl shadow-xl p-8 max-w-md w-full text-center space-y-4">
        <div className="w-14 h-14 bg-rose-50 border border-rose-200 rounded-2xl flex items-center justify-center mx-auto">
          <ShieldAlert className="w-7 h-7 text-rose-600" />
        </div>
        <h1 className="text-xl font-extrabold text-slate-900">Something went wrong</h1>
        <p className="text-sm text-slate-500 leading-relaxed">
          An unexpected error occurred in the Vergabepilot.AI dashboard. The error has been logged.
        </p>
        {error.message && (
          <pre className="bg-slate-950 text-rose-300 text-[10px] font-mono p-3 rounded-xl overflow-x-auto text-left whitespace-pre-wrap">
            {error.message}
          </pre>
        )}
        {error.digest && (
          <p className="text-[10px] text-slate-400 font-mono">Digest: {error.digest}</p>
        )}
        <button
          onClick={reset}
          className="btn-primary w-full justify-center gap-2"
        >
          <RefreshCcw className="w-4 h-4" /> Try Again
        </button>
      </div>
    </div>
  );
}
