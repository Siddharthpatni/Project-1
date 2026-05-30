"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { Menu, X, Zap } from "lucide-react";

const NAV_LINKS = [
  { href: "/",           label: "Dashboard" },
  { href: "/jobs",       label: "Jobs" },
  { href: "/scrapers",   label: "Scrapers" },
  { href: "/audit",      label: "Audit" },
  { href: "/tests",      label: "Tests" },
  { href: "/evaluation", label: "Benchmarks" },
  { href: "/agents",     label: "CUA Agents" },
  { href: "/excel",      label: "Excel" },
  { href: "/admin",      label: "Admin" },
];

export default function Navbar() {
  const path = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <nav className="bg-white/90 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4">

        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 flex-shrink-0 group" onClick={() => setOpen(false)}>
          <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center shadow-sm group-hover:bg-indigo-700 transition-colors">
            <Zap className="w-4 h-4 text-white fill-white" />
          </div>
          <span className="font-bold tracking-tight text-slate-800 text-[15px] hidden sm:block">
            Vergabepilot<span className="text-indigo-600">.AI</span>
          </span>
        </Link>

        {/* Desktop nav — scrollable if narrow */}
        <div className="hidden md:flex flex-1 overflow-x-auto no-scrollbar">
          <ul className="flex items-center gap-0.5 text-sm whitespace-nowrap">
            {NAV_LINKS.map((l) => {
              const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    className={clsx(
                      "px-3 py-1.5 rounded-md font-medium transition-colors text-sm",
                      active
                        ? "bg-indigo-50 text-indigo-700 font-semibold"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-800"
                    )}
                  >
                    {l.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden p-2 rounded-lg text-slate-500 hover:bg-slate-100 transition-colors"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Close menu" : "Open menu"}
        >
          {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Mobile drawer */}
      {open && (
        <div className="md:hidden border-t border-slate-100 bg-white shadow-lg animate-slide-down">
          <ul className="px-4 py-3 grid grid-cols-2 gap-1">
            {NAV_LINKS.map((l) => {
              const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    onClick={() => setOpen(false)}
                    className={clsx(
                      "block px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                      active
                        ? "bg-indigo-50 text-indigo-700 font-semibold"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                    )}
                  >
                    {l.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </nav>
  );
}
