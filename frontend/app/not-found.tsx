import Link from "next/link";
import { FileSearch, ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <div className="min-h-[60vh] flex items-center justify-center px-4">
      <div className="text-center space-y-5 max-w-sm">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto"
          style={{ background: "var(--brand-light)", color: "var(--brand)" }}
        >
          <FileSearch className="w-8 h-8" />
        </div>

        <div className="space-y-2">
          <h1 className="text-4xl font-extrabold" style={{ color: "var(--fg)" }}>404</h1>
          <p className="text-base font-semibold" style={{ color: "var(--fg)" }}>Page not found</p>
          <p className="text-sm" style={{ color: "var(--fg-subtle)" }}>
            This page doesn&apos;t exist or was moved.
          </p>
        </div>

        <Link
          href="/"
          className="btn btn-primary inline-flex gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
