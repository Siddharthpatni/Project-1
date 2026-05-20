"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const links = [
  { href: "/",            label: "Dashboard" },
  { href: "/jobs",        label: "Jobs" },
  { href: "/library",     label: "Library" },
  { href: "/scrapers",    label: "Scrapers" },
  { href: "/evaluation",  label: "Phase 1 Eval" },
  { href: "/agents",      label: "Phase 2 CUA" },
  { href: "/admin",       label: "Admin" },
];

export default function Navbar() {
  const path = usePathname();
  return (
    <nav className="bg-white/80 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 shadow-sm">
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center gap-6">
        <Link href="/" className="font-semibold tracking-tight text-brand-700">
          Vergabepilot<span className="text-slate-400">.AI</span>
        </Link>
        <ul className="flex items-center gap-1 text-sm">
          {links.map((l) => (
            <li key={l.href}>
              <Link
                href={l.href}
                className={clsx(
                  "px-3 py-1.5 rounded-md transition-colors",
                  path === l.href
                    ? "bg-brand-50 text-brand-700"
                    : "text-slate-600 hover:bg-slate-100"
                )}
              >
                {l.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
