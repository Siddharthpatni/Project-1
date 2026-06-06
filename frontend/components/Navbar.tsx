"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { Menu, X, Zap, Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/hooks";

const NAV_LINKS = [
  { href: "/",           label: "Dashboard",  exact: true },
  { href: "/jobs",       label: "Jobs" },
  { href: "/extraction", label: "Extraction" },
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
  const { dark, toggle } = useTheme();

  function isActive(link: { href: string; exact?: boolean }) {
    if (link.exact) return path === link.href;
    return path.startsWith(link.href);
  }

  return (
    <nav
      className="sticky top-0 z-50 backdrop-blur-md"
      style={{
        background: "rgba(var(--bg-elevated-raw, 255 255 255) / 0.85)",
        borderBottom: "1px solid var(--border)",
        boxShadow: "0 1px 0 0 var(--border)",
      }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4">

        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2.5 flex-shrink-0 group"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shadow-sm group-hover:scale-105 transition-transform"
            style={{ background: "var(--brand)" }}
          >
            <Zap className="w-4 h-4 text-white fill-white" />
          </div>
          <span className="font-bold tracking-tight text-[15px] hidden sm:block" style={{ color: "var(--fg)" }}>
            Vergabepilot<span style={{ color: "var(--brand)" }}>.AI</span>
          </span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden md:flex flex-1 overflow-x-auto no-scrollbar">
          <ul className="flex items-center gap-0.5 text-sm whitespace-nowrap">
            {NAV_LINKS.map((link) => {
              const active = isActive(link);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className={clsx(
                      "px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-150",
                      active
                        ? "font-semibold"
                        : "hover:opacity-80",
                    )}
                    style={{
                      background: active ? "var(--brand-light)" : "transparent",
                      color: active ? "var(--brand)" : "var(--fg-muted)",
                    }}
                    aria-current={active ? "page" : undefined}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-2">
          {/* Dark mode toggle */}
          <button
            onClick={toggle}
            className="p-2 rounded-lg transition-all"
            style={{
              background: "var(--bg-subtle)",
              color: "var(--fg-muted)",
              border: "1px solid var(--border)",
            }}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {dark
              ? <Sun className="w-4 h-4" />
              : <Moon className="w-4 h-4" />}
          </button>

          {/* Mobile hamburger */}
          <button
            className="md:hidden p-2 rounded-lg transition-all"
            style={{ color: "var(--fg-muted)", background: "var(--bg-subtle)", border: "1px solid var(--border)" }}
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
          >
            {open ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Mobile drawer */}
      {open && (
        <div
          className="md:hidden border-t shadow-lg animate-slide-down"
          style={{ background: "var(--bg-elevated)", borderColor: "var(--border)" }}
        >
          <ul className="px-4 py-3 grid grid-cols-2 gap-1">
            {NAV_LINKS.map((link) => {
              const active = isActive(link);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    onClick={() => setOpen(false)}
                    className={clsx(
                      "block px-3 py-2.5 rounded-lg text-sm font-medium transition-all",
                    )}
                    style={{
                      background: active ? "var(--brand-light)" : "transparent",
                      color: active ? "var(--brand)" : "var(--fg-muted)",
                      fontWeight: active ? "700" : "500",
                    }}
                    aria-current={active ? "page" : undefined}
                  >
                    {link.label}
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
