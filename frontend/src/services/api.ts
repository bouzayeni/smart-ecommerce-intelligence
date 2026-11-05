import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

import type { ApiErrorBody, Tokens } from "../types/api";

/*
 * Token handling
 * - The access token (15 min) lives only in memory: never in storage an XSS payload can read
 *   after the tab is gone.
 * - The refresh token is in sessionStorage so a reload keeps the session, and closing the tab
 *   ends it. httpOnly cookies would be stronger; the API issues tokens in JSON, so this is the
 *   least-exposed client-side option. Refresh tokens rotate and reuse revokes the session.
 */
const REFRESH_KEY = "sei.refresh_token";
let accessToken: string | null = null;

export const tokens = {
  set(t: Tokens) {
    accessToken = t.access_token;
    try {
      sessionStorage.setItem(REFRESH_KEY, t.refresh_token);
    } catch {
      /* storage unavailable: session lasts until the access token expires */
    }
  },
  clear() {
    accessToken = null;
    try {
      sessionStorage.removeItem(REFRESH_KEY);
    } catch {
      /* ignore */
    }
  },
  refreshToken(): string | null {
    try {
      return sessionStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  },
  hasAccess: () => accessToken !== null,
};

export const api = axios.create({ baseURL: "/api", timeout: 30_000 });

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

let onSessionExpired: (() => void) | null = null;
export const setSessionExpiredHandler = (fn: () => void) => {
  onSessionExpired = fn;
};

// Single-flight refresh. Refresh tokens rotate and the API revokes the whole session when a
// rotated token is presented again, so two concurrent refreshes with the same token (e.g. the
// startup bootstrap running twice under React StrictMode, or parallel 401s) would log the user
// out. Every caller shares one in-flight request.
let refreshing: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  refreshing ??= doRefresh().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function doRefresh(): Promise<boolean> {
  const token = tokens.refreshToken();
  if (!token) return false;
  try {
    const { data } = await axios.post<Tokens>("/api/auth/refresh", { refresh_token: token });
    tokens.set(data);
    return true;
  } catch {
    tokens.clear();
    return false;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
    const isAuthCall = original?.url?.startsWith("/auth/");
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true;
      if (await refreshSession()) return api(original);
      onSessionExpired?.();
    }
    return Promise.reject(error);
  },
);

export interface ApiFailure {
  status: number | null;
  code: string;
  message: string;
  requestId: string | null;
}

export function toFailure(error: unknown): ApiFailure {
  if (axios.isCancel(error)) return { status: null, code: "cancelled", message: "Cancelled", requestId: null };
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorBody | undefined;
    if (body?.error) {
      return {
        status: error.response?.status ?? null,
        code: body.error.code,
        message: body.error.message,
        requestId: body.error.request_id,
      };
    }
    if (!error.response) {
      return { status: null, code: "network", message: "The API is unreachable. Is the backend running?", requestId: null };
    }
    return { status: error.response.status, code: "error", message: error.message, requestId: null };
  }
  return { status: null, code: "error", message: String(error), requestId: null };
}
