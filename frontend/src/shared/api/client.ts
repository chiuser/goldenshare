import { ApiError } from "./errors";


interface ApiRequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
}

const AUTH_TOKEN_KEY = "goldenshare.frontend.auth.token";
const API_REQUEST_TIMEOUT_MS = 8_000;

function redirectToLoginOnUnauthorized(path: string, error: ApiError): void {
  if (path === "/api/v1/auth/login") {
    return;
  }
  if (error.status !== 401 || error.code !== "unauthorized") {
    return;
  }

  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  if (window.location.pathname !== "/app/login") {
    window.location.replace("/app/login");
  }
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const token = options.token ?? window.localStorage.getItem(AUTH_TOKEN_KEY);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);

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
