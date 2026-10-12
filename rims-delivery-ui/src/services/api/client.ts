import { env } from "@/config/env";
import type { ErrorCode } from "@/types";

export class ApiError extends Error {
  constructor(
    public code: ErrorCode,
    message: string,
    public status = 0,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;
export interface RequestOptions {
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
  skipSessionHandler?: boolean;
}

let sessionExpiredHandler: (() => void) | null = null;
export const onSessionExpired = (fn: (() => void) | null) => {
  sessionExpiredHandler = fn;
};

const buildQuery = (q?: Query) => {
  if (!q) return "";
  const p = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
};

let csrfToken: string | null = null;
export const setCsrfToken = (token: string | null) => {
  csrfToken = token;
};
export const getCsrfToken = () => csrfToken;

export async function request<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  if (env.useMocks) {
    const { mockRequest } = await import("@/services/mocks/handler");
    return mockRequest<T>(method, path, opts);
  }
  let res: Response;
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (csrfToken && method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = csrfToken;
  }
  try {
    res = await fetch(`${env.apiBase}${path}${buildQuery(opts.query)}`, {
      method,
      credentials: "include",
      signal: opts.signal,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("NETWORK", "Could not reach the server.");
  }
  const responseCsrf = res.headers.get("x-csrf-token");
  if (responseCsrf) {
    csrfToken = responseCsrf;
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (res.ok) return data as T;
  if (res.status === 401 && !opts.skipSessionHandler) {
    sessionExpiredHandler?.();
    throw new ApiError("SESSION_EXPIRED", "Your session has expired.", 401);
  }
  // Backend error envelope: { code, message, details }
  const code =
    (data?.code as ErrorCode | undefined) ??
    (res.status >= 500
      ? "SERVER"
      : res.status === 403
        ? "FORBIDDEN"
        : res.status === 404
          ? "NOT_FOUND"
          : res.status === 422
            ? "VALIDATION"
            : "UNKNOWN");
  throw new ApiError(
    code,
    data?.message ?? res.statusText,
    res.status,
    data?.details,
  );
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>("GET", path, { query, signal }),
  post: <T>(
    path: string,
    body?: unknown,
    o?: Pick<RequestOptions, "skipSessionHandler">,
  ) => request<T>("POST", path, { body: body ?? {}, ...o }),
  patch: <T>(path: string, body: unknown) =>
    request<T>("PATCH", path, { body }),
  delete: <T>(path: string) =>
    request<T>("DELETE", path),
};
