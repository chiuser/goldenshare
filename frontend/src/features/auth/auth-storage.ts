const AUTH_TOKEN_KEY = "goldenshare.frontend.auth.token";

export function readStoredToken(): string | null {
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function writeStoredToken(token: string): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
}
