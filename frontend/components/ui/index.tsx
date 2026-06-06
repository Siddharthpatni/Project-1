"use client";
/**
 * Vergabepilot Design System
 * All shared UI primitives — Button, Badge, Card, Input, Skeleton, Progress,
 * Alert, Spinner, Tabs, Modal, Tooltip, and more.
 *
 * Every component is:
 *  - Fully typed
 *  - Dark-mode aware (uses CSS variables from globals.css)
 *  - Keyboard accessible
 *  - aria-labelled where appropriate
 */

import React, { forwardRef, ReactNode, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Loader2, X, CheckCircle2, AlertCircle, Info, AlertTriangle } from "lucide-react";

// ─── Button ─────────────────────────────────────────────────────────────────

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "outline";
  size?: "xs" | "sm" | "md" | "lg" | "icon";
  loading?: boolean;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "md", loading, className, children, disabled, ...props }, ref) => {
    const variantCls = {
      primary:  "btn-primary",
      secondary:"btn-secondary",
      ghost:    "btn-ghost",
      danger:   "btn-danger",
      outline:  "btn border",
    }[variant];

    const sizeCls = {
      xs:   "btn-xs",
      sm:   "btn-sm",
      md:   "",
      lg:   "px-5 py-2.5 text-base",
      icon: "btn-icon",
    }[size];

    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={clsx("btn", variantCls, sizeCls, className)}
        {...props}
      >
        {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

// ─── Badge ───────────────────────────────────────────────────────────────────

interface BadgeProps {
  variant?: "default" | "success" | "failed" | "warning" | "info" | "running" | "pending" | "partial";
  size?: "sm" | "md";
  className?: string;
  children: ReactNode;
}

export function Badge({ variant = "default", size = "md", className, children }: BadgeProps) {
  const v = {
    default: "badge-pending",
    success: "badge-success",
    failed:  "badge-failed",
    warning: "bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800",
    info:    "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800",
    running: "badge-running",
    pending: "badge-pending",
    partial: "badge-partial",
  }[variant];
  return (
    <span className={clsx("badge", v, size === "sm" && "text-[10px] px-2 py-px", className)}>
      {children}
    </span>
  );
}

// ─── Card ────────────────────────────────────────────────────────────────────

interface CardProps {
  className?: string;
  hover?: boolean;
  children: ReactNode;
  onClick?: () => void;
}

export function Card({ className, hover, children, onClick }: CardProps) {
  return (
    <div
      className={clsx(hover ? "card-hover cursor-pointer" : "card", "p-5", className)}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("flex items-center justify-between mb-4 pb-3", className)}
         style={{ borderBottom: "1px solid var(--border)" }}>
      {children}
    </div>
  );
}

// ─── Input ───────────────────────────────────────────────────────────────────

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, leadingIcon, trailingIcon, className, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s/g, "-");
    return (
      <div className="space-y-1">
        {label && (
          <label htmlFor={inputId} className="text-xs font-semibold" style={{ color: "var(--fg-muted)" }}>
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leadingIcon && (
            <span className="absolute left-3 flex items-center pointer-events-none" style={{ color: "var(--fg-subtle)" }}>
              {leadingIcon}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            className={clsx(
              "form-input",
              leadingIcon && "pl-9",
              trailingIcon && "pr-9",
              error && "border-rose-400 focus:border-rose-500",
              className,
            )}
            aria-invalid={!!error}
            aria-describedby={error ? `${inputId}-error` : undefined}
            {...props}
          />
          {trailingIcon && (
            <span className="absolute right-3 flex items-center pointer-events-none" style={{ color: "var(--fg-subtle)" }}>
              {trailingIcon}
            </span>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="text-xs text-rose-600 dark:text-rose-400" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";

// ─── Skeleton ────────────────────────────────────────────────────────────────

export function Skeleton({ className, width, height }: { className?: string; width?: string | number; height?: string | number }) {
  return (
    <div
      className={clsx("skeleton", className)}
      style={{ width, height: height ?? "1rem" }}
      aria-hidden="true"
    />
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card p-5 space-y-3 animate-fade-in">
      <Skeleton height="1.25rem" width="60%" />
      {Array.from({ length: lines - 1 }).map((_, i) => (
        <Skeleton key={i} width={i === lines - 2 ? "40%" : "100%"} />
      ))}
    </div>
  );
}

// ─── Progress ────────────────────────────────────────────────────────────────

interface ProgressProps {
  value: number;
  max?: number;
  color?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
  label?: string;
}

export function Progress({ value, max = 100, color, size = "md", className, label }: ProgressProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const h = { sm: "h-1", md: "h-2", lg: "h-3" }[size];
  return (
    <div className={clsx("w-full rounded-full overflow-hidden", h, className)}
         style={{ background: "var(--bg-muted)" }}
         role="progressbar" aria-valuenow={value} aria-valuemax={max} aria-label={label}>
      <div
        className={clsx("h-full rounded-full transition-all duration-500")}
        style={{ width: `${pct}%`, background: color ?? "var(--brand)" }}
      />
    </div>
  );
}

// ─── Alert ───────────────────────────────────────────────────────────────────

interface AlertProps {
  variant?: "info" | "success" | "warning" | "error";
  title?: string;
  className?: string;
  children: ReactNode;
}

const ALERT_STYLES = {
  info:    { cls: "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200",    Icon: Info },
  success: { cls: "bg-emerald-50 dark:bg-emerald-950 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200", Icon: CheckCircle2 },
  warning: { cls: "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200", Icon: AlertTriangle },
  error:   { cls: "bg-rose-50 dark:bg-rose-950 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200",   Icon: AlertCircle },
};

export function Alert({ variant = "info", title, className, children }: AlertProps) {
  const { cls, Icon } = ALERT_STYLES[variant];
  return (
    <div className={clsx("flex gap-3 p-4 rounded-xl border text-sm", cls, className)} role="alert">
      <Icon className="w-4 h-4 flex-shrink-0 mt-0.5" />
      <div>
        {title && <p className="font-semibold mb-0.5">{title}</p>}
        <div className="opacity-90">{children}</div>
      </div>
    </div>
  );
}

// ─── Spinner ─────────────────────────────────────────────────────────────────

export function Spinner({ size = "md", className }: { size?: "sm" | "md" | "lg"; className?: string }) {
  const s = { sm: "w-3.5 h-3.5", md: "w-5 h-5", lg: "w-7 h-7" }[size];
  return <Loader2 className={clsx(s, "animate-spin", className)} style={{ color: "var(--brand)" }} aria-label="Loading" />;
}

// ─── Empty state ─────────────────────────────────────────────────────────────

interface EmptyProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function Empty({ icon, title, description, action, className }: EmptyProps) {
  return (
    <div className={clsx("flex flex-col items-center justify-center py-16 text-center px-4", className)}>
      {icon && (
        <div className="mb-4 opacity-30" style={{ color: "var(--fg-subtle)" }}>
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold" style={{ color: "var(--fg-muted)" }}>{title}</p>
      {description && (
        <p className="text-xs mt-1 max-w-xs" style={{ color: "var(--fg-subtle)" }}>{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ─── Tabs ────────────────────────────────────────────────────────────────────

interface Tab { id: string; label: string; count?: number; icon?: ReactNode; }

interface TabsProps {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, active, onChange, className }: TabsProps) {
  return (
    <div
      className={clsx("flex gap-1 p-1 rounded-xl", className)}
      style={{ background: "var(--bg-subtle)" }}
      role="tablist"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={clsx(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
            active === tab.id
              ? "bg-white dark:bg-slate-700 shadow-sm text-indigo-700 dark:text-indigo-300"
              : "hover:text-slate-700 dark:hover:text-slate-300",
          )}
          style={{ color: active === tab.id ? undefined : "var(--fg-subtle)" }}
        >
          {tab.icon}
          {tab.label}
          {tab.count !== undefined && (
            <span className={clsx(
              "px-1.5 py-0.5 rounded-full text-[10px] font-bold",
              active === tab.id ? "bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300" : "bg-slate-200 dark:bg-slate-600",
            )}>
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

// ─── KPI Card ────────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: ReactNode;
  sub?: string;
  icon?: ReactNode;
  trend?: { value: number; label: string };
  loading?: boolean;
  color?: "default" | "success" | "warning" | "error" | "brand";
  className?: string;
}

export function KpiCard({ label, value, sub, icon, trend, loading, color = "default", className }: KpiCardProps) {
  const colorMap = {
    default: "var(--fg)",
    success: "#10b981",
    warning: "#f59e0b",
    error:   "#ef4444",
    brand:   "var(--brand)",
  };

  return (
    <div className={clsx("card p-5 relative overflow-hidden group", className)}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <p className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--fg-subtle)" }}>
          {label}
        </p>
        {icon && (
          <span className="flex-shrink-0 opacity-70" style={{ color: colorMap[color] }}>
            {icon}
          </span>
        )}
      </div>

      {loading ? (
        <Skeleton height="2rem" width="60%" />
      ) : (
        <p className="text-2xl font-extrabold tracking-tight" style={{ color: colorMap[color] }}>
          {value}
        </p>
      )}

      {(sub || trend) && !loading && (
        <div className="flex items-center gap-2 mt-1.5">
          {sub && <p className="text-xs" style={{ color: "var(--fg-subtle)" }}>{sub}</p>}
          {trend && (
            <span className={clsx(
              "text-xs font-semibold px-1.5 py-0.5 rounded-full",
              trend.value >= 0
                ? "bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300"
                : "bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300",
            )}>
              {trend.value >= 0 ? "↑" : "↓"} {Math.abs(trend.value)}% {trend.label}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Section header ──────────────────────────────────────────────────────────

interface SectionHeaderProps {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function SectionHeader({ title, description, icon, action, className }: SectionHeaderProps) {
  return (
    <div className={clsx("section-header", className)}>
      <div className="flex items-center gap-3">
        {icon && (
          <div className="p-2.5 rounded-xl border" style={{ background: "var(--brand-light)", borderColor: "var(--brand-muted)", color: "var(--brand)" }}>
            {icon}
          </div>
        )}
        <div>
          <h1 className="text-heading" style={{ color: "var(--fg)" }}>{title}</h1>
          {description && <p className="text-xs mt-0.5" style={{ color: "var(--fg-subtle)" }}>{description}</p>}
        </div>
      </div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  );
}

// ─── Modal ───────────────────────────────────────────────────────────────────

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  maxWidth?: string;
  footer?: ReactNode;
}

export function Modal({ open, onClose, title, children, maxWidth = "max-w-2xl", footer }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto py-8 px-4"
      style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(4px)" }}
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? "modal-title" : undefined}
    >
      <div className={clsx("card w-full animate-scale-in", maxWidth)}>
        {title && (
          <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: "1px solid var(--border)" }}>
            <h2 id="modal-title" className="text-subheading" style={{ color: "var(--fg)" }}>{title}</h2>
            <button onClick={onClose} className="btn-icon btn-ghost rounded-lg p-1.5" aria-label="Close">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
        <div className="p-6 max-h-[75vh] overflow-y-auto custom-scrollbar">
          {children}
        </div>
        {footer && (
          <div className="px-6 py-4 flex justify-end gap-2" style={{ borderTop: "1px solid var(--border)" }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Tooltip ─────────────────────────────────────────────────────────────────

export function Tooltip({ content, children }: { content: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg"
            style={{ background: "var(--fg)", color: "var(--bg-elevated)" }}
            role="tooltip">
        {content}
      </span>
    </span>
  );
}

// ─── Search input ────────────────────────────────────────────────────────────

interface SearchInputProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}

export function SearchInput({ value, onChange, placeholder = "Search…", className }: SearchInputProps) {
  return (
    <div className={clsx("relative", className)}>
      <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
        <svg className="w-4 h-4" style={{ color: "var(--fg-subtle)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={clsx("form-input pl-9 pr-4")}
        aria-label={placeholder}
      />
    </div>
  );
}

// ─── Loading page ────────────────────────────────────────────────────────────

export function LoadingPage({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[40vh] gap-3">
      <Spinner size="lg" />
      <p className="text-sm" style={{ color: "var(--fg-subtle)" }}>{label}</p>
    </div>
  );
}

// ─── Divider ─────────────────────────────────────────────────────────────────

export function Divider({ className }: { className?: string }) {
  return <div className={clsx("divider", className)} aria-hidden="true" />;
}

// ─── Code block ──────────────────────────────────────────────────────────────

export function CodeBlock({ children, className }: { children: ReactNode; className?: string }) {
  return <pre className={clsx("code-block", className)}><code>{children}</code></pre>;
}
