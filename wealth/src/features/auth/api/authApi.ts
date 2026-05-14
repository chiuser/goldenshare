import type {
  AuthApiErrorPayload,
  CurrentUserResponse,
  LoginRequest,
  LogoutRequest,
  RefreshTokenRequest,
  TokenResponse,
} from "./authTypes";

export class AuthApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "AUTH_API_ERROR", status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function login(body: LoginRequest, signal?: AbortSignal): Promise<TokenResponse> {
  return postJson<TokenResponse>("/api/v1/auth/login", body, { signal });
}

export async function refreshToken(body: RefreshTokenRequest, signal?: AbortSignal): Promise<TokenResponse> {
  return postJson<TokenResponse>("/api/v1/auth/refresh", body, { signal });
}

export async function fetchCurrentUser(accessToken: string, signal?: AbortSignal): Promise<CurrentUserResponse> {
  const response = await fetch("/api/v1/auth/me", {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  });
  return parseResponse<CurrentUserResponse>(response);
}

export async function logout(body: LogoutRequest, accessToken?: string | null, signal?: AbortSignal): Promise<void> {
  const headers = new Headers({
    Accept: "application/json",
    "Content-Type": "application/json",
  });
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch("/api/v1/auth/logout", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  await parseResponse<unknown>(response);
}

async function postJson<T>(url: string, body: unknown, init: { signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: init.signal,
  });
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let message = `请求失败：${response.status}`;
  let code = `HTTP_${response.status}`;
  try {
    const payload = (await response.json()) as AuthApiErrorPayload;
    if (payload.message) message = payload.message;
    if (payload.code) code = payload.code;
  } catch {
    // Keep fallback status message when response body is not JSON.
  }
  throw new AuthApiError(message, code, response.status);
}

