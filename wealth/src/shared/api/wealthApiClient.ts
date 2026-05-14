import { refreshToken } from "../../features/auth/api/authApi";
import { notifyAuthRequired } from "../../features/auth/model/authEvents";
import { clearAuthSession, readAuthSession, saveAuthSession } from "../../features/auth/model/authStorage";

export async function wealthFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const firstResponse = await fetchWithCurrentToken(input, init);
  if (firstResponse.status !== 401) return firstResponse;

  const session = readAuthSession();
  if (!session?.refreshToken) {
    clearAuthSession();
    notifyAuthRequired();
    return firstResponse;
  }

  try {
    const refreshed = await refreshToken({ refresh_token: session.refreshToken });
    saveAuthSession(refreshed);
  } catch {
    clearAuthSession();
    notifyAuthRequired();
    return firstResponse;
  }

  const secondResponse = await fetchWithCurrentToken(input, init);
  if (secondResponse.status === 401) {
    clearAuthSession();
    notifyAuthRequired();
  }
  return secondResponse;
}

function fetchWithCurrentToken(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  const session = readAuthSession();
  if (session?.accessToken) headers.set("Authorization", `Bearer ${session.accessToken}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  return fetch(input, {
    ...init,
    headers,
  });
}

