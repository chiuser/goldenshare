import { ApiError } from "./errors";


interface ApiRequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
  skipAuthRefresh?: boolean;
  timeoutMs?: number;
}

const AUTH_TOKEN_KEY = "goldenshare.frontend.auth.token";
const AUTH_REFRESH_TOKEN_KEY = "goldenshare.frontend.auth.refresh-token";
const API_REQUEST_TIMEOUT_MS = 8_000;
const REFRESH_PATH = "/api/v1/auth/refresh";
const AUTH_BYPASS_REFRESH_PATHS = new Set([
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/register/verify",
  REFRESH_PATH,
]);

interface TokenRefreshResponse {
  token: string;
  refresh_token: string | null;
}

let refreshInFlight: Promise<string | null> | null = null;

function clearStoredAuth(): void {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
}

function writeStoredAuth(token: string, refreshToken: string | null): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (refreshToken) {
    window.localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, refreshToken);
  } else {
    window.localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const currentRefreshToken = window.localStorage.getItem(AUTH_REFRESH_TOKEN_KEY);
  if (!currentRefreshToken) {
    return null;
  }
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(REFRESH_PATH, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: currentRefreshToken }),
        });
        if (!response.ok) {
          clearStoredAuth();
          return null;
        }
        const payload = (await response.json()) as TokenRefreshResponse;
        if (!payload?.token) {
          clearStoredAuth();
          return null;
        }
        writeStoredAuth(payload.token, payload.refresh_token);
        return payload.token;
      } catch {
        clearStoredAuth();
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

function redirectToLoginOnUnauthorized(path: string, error: ApiError): void {
  if (path === "/api/v1/auth/login") {
    return;
  }
  if (error.status !== 401 || error.code !== "unauthorized") {
    return;
  }

  clearStoredAuth();
  if (window.location.pathname !== "/app/login") {
    window.location.replace("/app/login");
  }
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const token = options.token ?? window.localStorage.getItem(AUTH_TOKEN_KEY);
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? API_REQUEST_TIMEOUT_MS;
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(path, {
      method: options.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal ?? controller.signal,
    });

    if (!response.ok) {
      let payload: unknown = undefined;
      try {
        payload = await response.json();
      } catch {
        payload = undefined;
      }
      const error = new ApiError(response.status, (payload ?? undefined) as { code?: string; message?: string; request_id?: string });
      const shouldTryRefresh = (
        !options.skipAuthRefresh
        && error.status === 401
        && error.code === "unauthorized"
        && !AUTH_BYPASS_REFRESH_PATHS.has(path)
      );
      if (shouldTryRefresh) {
        const refreshedToken = await refreshAccessToken();
        if (refreshedToken) {
          return apiRequest<T>(path, {
            ...options,
            token: refreshedToken,
            skipAuthRefresh: true,
          });
        }
      }
      redirectToLoginOnUnauthorized(path, error);
      throw error;
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`请求超时：${path}`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}
