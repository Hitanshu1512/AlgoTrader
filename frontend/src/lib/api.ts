// Same-origin API client. The session lives in an httpOnly cookie the browser sends
// automatically; state-changing requests also carry the CSRF token (double-submit).

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null | undefined): void {
  if (token) csrfToken = token;
}

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("at_csrf=") || c.startsWith("__Host-at_csrf="));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const h = new Headers(headers);
  if (json !== undefined) h.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    const token = csrfToken ?? readCsrfCookie();
    if (token) h.set("X-CSRF-Token", token);
  }
  const res = await fetch(`/api${path}`, {
    ...rest,
    method,
    headers: h,
    credentials: "same-origin",
    cache: "no-store",
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface SessionState {
  email: string;
  role: string;
  mfa_enrolled: boolean;
  mfa_verified: boolean;
  step_up_valid: boolean;
  session_expires_at: string;
  csrf_token: string | null;
}

export interface Component {
  name: string;
  status: "ok" | "degraded" | "down" | "not_configured" | "not_deployed";
  latency_ms: number | null;
  detail: string | null;
}

export interface SystemStatus {
  version: string;
  app_env: string;
  trading_env: "paper" | "live";
  server_time_utc: string;
  server_time_ist: string;
  components: Component[];
}

export interface AuditEntry {
  id: number;
  occurred_at: string;
  actor: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip: string | null;
}
