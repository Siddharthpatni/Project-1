"use client";

import ExcelWorkspace from "@/components/ExcelWorkspace";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default function ExcelPage() {
  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      {/* ── Navigation / Back Button ── */}
      <Link 
        href="/" 
        className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-indigo-600 transition-all hover:translate-x-[-2px] duration-200"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Dashboard
      </Link>

      <ExcelWorkspace />
    </div>
  );
}
