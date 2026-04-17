const AUTH_TOKEN_KEY = "goldenshare.frontend.auth.token";
const AUTH_REFRESH_TOKEN_KEY = "goldenshare.frontend.auth.refresh-token";

export function readStoredToken(): string | null {
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function readStoredRefreshToken(): string | null {
  return window.localStorage.getItem(AUTH_REFRESH_TOKEN_KEY);
}

export function writeStoredToken(token: string, refreshToken?: string | null): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (refreshToken) {
    window.localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, refreshToken);
  }
}

export function clearStoredToken(): void {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
}
