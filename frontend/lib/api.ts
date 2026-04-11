/**
 * Tiny API client.
 *
 * The Next.js rewrite in next.config.js maps `/api/backend/*` to the
 * FastAPI service. Calling `api("/jobs")` therefore hits the backend
 * via the same origin as the frontend (no CORS headaches in the
 * browser).
 */
export function api(path: string): string {
  if (!path.startsWith("/")) path = "/" + path;
  return `/api/backend${path}`;
}

export const fetcher = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export async function postJSON<T = any>(path: string, body: unknown): Promise<T> {
  const r = await fetch(api(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`POST ${path} failed: ${r.status} ${text}`);
  }
  return r.json();
}

export async function postMultipart<T = any>(path: string, formData: FormData): Promise<T> {
  const r = await fetch(api(path), {
    method: "POST",
    body: formData,
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`POST (multipart) ${path} failed: ${r.status} ${text}`);
  }
  return r.json();
}
