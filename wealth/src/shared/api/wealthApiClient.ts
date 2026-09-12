import { refreshToken } from "../../features/auth/api/authApi";
import { notifyAuthRequired } from "../../features/auth/model/authEvents";
import { clearAuthSession, getAuthEpoch, readAuthSession, saveAuthSession } from "../../features/auth/model/authStorage";

export async function wealthFetch(input: RequestInfo | URL, init: RequestInit = {},
  { replayAfterRefresh = true }: { replayAfterRefresh?: boolean } = {}): Promise<Response> {
  const epoch = getAuthEpoch();
  const originalSession = readAuthSession();
  const firstResponse = await fetchWithCurrentToken(input, init);
  if (firstResponse.status !== 401) return firstResponse;
  if (getAuthEpoch() !== epoch) return firstResponse;

  const session = originalSession;
  if (!session?.refreshToken) {
    clearAuthSession();
    notifyAuthRequired();
    return firstResponse;
  }

  try {
    const refreshed = await refreshToken({ refresh_token: session.refreshToken }, init.signal ?? undefined);
    if (getAuthEpoch() !== epoch || readAuthSession()?.refreshToken !== session.refreshToken) return firstResponse;
    saveAuthSession(refreshed, "refresh");
  } catch {
    if (init.signal?.aborted) return firstResponse;
    if (getAuthEpoch() !== epoch || readAuthSession()?.refreshToken !== session.refreshToken) return firstResponse;
    clearAuthSession();
    notifyAuthRequired();
    return firstResponse;
  }

  if (!replayAfterRefresh || init.signal?.aborted) return firstResponse;

  const replayToken = readAuthSession()?.accessToken;
  const secondResponse = await fetchWithCurrentToken(input, init);
  if (secondResponse.status === 401 && getAuthEpoch() === epoch
      && readAuthSession()?.accessToken === replayToken) {
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
