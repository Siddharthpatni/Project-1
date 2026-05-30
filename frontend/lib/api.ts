/**
 * API client with self-healing retry logic.
 *
 * All requests go through /api/backend/* (Next.js rewrites to FastAPI).
 *
 * Self-healing:
 *   - fetcher: up to 3 retries with 600ms base-delay exponential backoff
 *     for transient failures (network blips, 429, 502, 503, 504).
 *   - postJSON / postMultipart: single-attempt — callers handle their own UX.
 */

const RETRY_STATUS = new Set([429, 502, 503, 504]);
const MAX_RETRIES  = 3;
const BASE_DELAY   = 600; // ms

export function api(path: string): string {
  if (!path.startsWith("/")) path = "/" + path;
  return `/api/backend${path}`;
}

async function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * SWR-compatible fetcher with automatic retry on transient errors.
 * Exponential backoff: 600ms → 1200ms → 2400ms.
 */
export const fetcher = async (url: string): Promise<any> => {
  let lastError: Error | null = null;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const r = await fetch(url);
      if (r.ok) return r.json();

      // Don't retry on permanent client errors
      if (r.status < 500 && !RETRY_STATUS.has(r.status)) {
        throw new Error(`${r.status} ${r.statusText}`);
      }

      lastError = new Error(`${r.status} ${r.statusText}`);
    } catch (e: any) {
      // Network-level failure (offline, DNS, CORS) — always retry
      lastError = e;
    }

    if (attempt < MAX_RETRIES) {
      await sleep(BASE_DELAY * 2 ** (attempt - 1));
    }
  }
  throw lastError!;
};

export async function postJSON<T = any>(path: string, body: unknown): Promise<T> {
  const r = await fetch(api(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText);
    throw new Error(`POST ${path} failed (${r.status}): ${text}`);
  }
  return r.json();
}

export async function postMultipart<T = any>(path: string, formData: FormData): Promise<T> {
  const r = await fetch(api(path), { method: "POST", body: formData });
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText);
    throw new Error(`POST (multipart) ${path} failed (${r.status}): ${text}`);
  }
  return r.json();
}
