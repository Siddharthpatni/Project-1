"use client";

import { createContext, useCallback, useContext, useState, useEffect } from "react";
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from "lucide-react";

type ToastLevel = "success" | "error" | "warning" | "info";

interface Toast {
  id: string;
  level: ToastLevel;
  title: string;
  message?: string;
}

interface ToastContextValue {
  toast: (level: ToastLevel, title: string, message?: string) => void;
  success: (title: string, msg?: string) => void;
  error:   (title: string, msg?: string) => void;
  warning: (title: string, msg?: string) => void;
  info:    (title: string, msg?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const ICON: Record<ToastLevel, any> = {
  success: CheckCircle2,
  error:   XCircle,
  warning: AlertTriangle,
  info:    Info,
};

const STYLE: Record<ToastLevel, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error:   "border-rose-200 bg-rose-50 text-rose-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info:    "border-indigo-200 bg-indigo-50 text-indigo-800",
};

const ICON_COLOR: Record<ToastLevel, string> = {
  success: "text-emerald-500",
  error:   "text-rose-500",
  warning: "text-amber-500",
  info:    "text-indigo-500",
};

function ToastItem({ t, onDismiss }: { t: Toast; onDismiss: (id: string) => void }) {
  const Icon = ICON[t.level];

  useEffect(() => {
    const timer = setTimeout(() => onDismiss(t.id), 5000);
    return () => clearTimeout(timer);
  }, [t.id, onDismiss]);

  return (
    <div className={`toast-enter flex items-start gap-3 w-full max-w-sm p-4 rounded-2xl border shadow-lg ${STYLE[t.level]}`}>
      <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${ICON_COLOR[t.level]}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold leading-snug">{t.title}</p>
        {t.message && <p className="text-xs mt-0.5 opacity-80 leading-snug">{t.message}</p>}
      </div>
      <button onClick={() => onDismiss(t.id)} className="flex-shrink-0 opacity-50 hover:opacity-100 transition-opacity">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((level: ToastLevel, title: string, message?: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev.slice(-4), { id, level, title, message }]);
  }, []);

  const ctx: ToastContextValue = {
    toast,
    success: (t, m) => toast("success", t, m),
    error:   (t, m) => toast("error", t, m),
    warning: (t, m) => toast("warning", t, m),
    info:    (t, m) => toast("info", t, m),
  };

  return (
    <ToastContext.Provider value={ctx}>
      {children}
      {/* Notification stack — bottom-right */}
      <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-3 items-end pointer-events-none">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto">
            <ToastItem t={t} onDismiss={dismiss} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
