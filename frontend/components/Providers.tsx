"use client";

import { SWRConfig } from "swr";
import { ToastProvider } from "@/components/Toast";
import { fetcher } from "@/lib/api";

/**
 * Global providers — SWR config + Toast notifications.
 * Wraps the entire app from layout.tsx.
 *
 * SWR self-healing config:
 *   revalidateOnFocus   – refreshes stale data when user tabs back
 *   revalidateOnReconnect – refreshes when network comes back online
 *   errorRetryCount     – SWR retries 3 times on top of fetcher retries
 *   dedupingInterval    – prevents duplicate requests in 4s window
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        fetcher,
        revalidateOnFocus: true,
        revalidateOnReconnect: true,
        errorRetryCount: 3,
        errorRetryInterval: 800,
        dedupingInterval: 4000,
        shouldRetryOnError: (err: Error) => {
          // Don't retry on permanent 4xx errors
          const status = parseInt(err.message.split(" ")[0]);
          return isNaN(status) || status >= 500 || status === 429;
        },
      }}
    >
      <ToastProvider>
        {children}
      </ToastProvider>
    </SWRConfig>
  );
}
