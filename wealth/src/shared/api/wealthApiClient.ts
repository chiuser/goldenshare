import { refreshToken } from "../../features/auth/api/authApi";
import { notifyAuthRequired } from "../../features/auth/model/authEvents";
import {
  clearAuthSession, getAuthEpoch, readAuthSession, saveAuthSession, type StoredAuthSession,
} from "../../features/auth/model/authStorage";

interface PendingRefresh {
  epoch: number;
  token: string;
  controller: AbortController;
  result: Promise<boolean>;
  waiters: number;
  settled: boolean;
}

let pendingRefresh: PendingRefresh | undefined;

function sameCredentials(left: StoredAuthSession | null, right: StoredAuthSession | null): boolean {
  return left?.accessToken === right?.accessToken && left?.refreshToken === right?.refreshToken;
}

function expireSession() {
  clearAuthSession();
  notifyAuthRequired();
}

function isCurrentRefresh(refresh: PendingRefresh): boolean {
  return pendingRefresh === refresh && getAuthEpoch() === refresh.epoch
    && readAuthSession()?.refreshToken === refresh.token;
}

async function runRefresh(refresh: PendingRefresh): Promise<boolean> {
  try {
    if (!isCurrentRefresh(refresh)) return false;
    const refreshed = await refreshToken({ refresh_token: refresh.token }, refresh.controller.signal);
    if (!isCurrentRefresh(refresh)) return false;
    saveAuthSession(refreshed, "refresh");
    return true;
  } catch {
    if (isCurrentRefresh(refresh)) expireSession();
    return false;
  } finally {
    refresh.settled = true;
    if (pendingRefresh === refresh) pendingRefresh = undefined;
  }
}

function getPendingRefresh(epoch: number, token: string): PendingRefresh {
  if (pendingRefresh?.epoch === epoch && pendingRefresh.token === token) return pendingRefresh;

  const refresh: PendingRefresh = {
    epoch, token, controller: new AbortController(), waiters: 0, settled: false,
    // Register the shared request and its first waiter before starting transport.
    result: Promise.resolve().then(() => runRefresh(refresh)),
  };
  pendingRefresh = refresh;
  return refresh;
}

function waitForRefresh(refresh: PendingRefresh, signal: AbortSignal | null | undefined): Promise<boolean> {
  refresh.waiters += 1;
  return new Promise((resolve, reject) => {
    let finished = false;
    const finish = () => {
      if (finished) return false;
      finished = true;
      signal?.removeEventListener("abort", onAbort);
      refresh.waiters -= 1;
      if (refresh.waiters === 0 && !refresh.settled) {
        if (pendingRefresh === refresh) pendingRefresh = undefined;
        refresh.controller.abort();
      }
      return true;
    };
    const onAbort = () => { if (finish()) resolve(false); };
    signal?.addEventListener("abort", onAbort, { once: true });
    refresh.result.then((result) => {
      if (finish()) resolve(result);
    }, (error: unknown) => {
      if (finish()) reject(error);
    });
  });
}

export async function wealthFetch(input: RequestInfo | URL, init: RequestInit = {},
  { replayAfterRefresh = true }: { replayAfterRefresh?: boolean } = {}): Promise<Response> {
  const epoch = getAuthEpoch();
  const originalSession = readAuthSession();
  const firstResponse = await fetchWithToken(input, init, originalSession?.accessToken);
  if (firstResponse.status !== 401) return firstResponse;
  if (init.signal?.aborted || getAuthEpoch() !== epoch) return firstResponse;

  const currentSession = readAuthSession();
  // A late 401 from the same login can already have fresh credentials to use.
  if (sameCredentials(originalSession, currentSession)) {
    if (!currentSession?.refreshToken) {
      expireSession();
      return firstResponse;
    }
    const refreshed = await waitForRefresh(getPendingRefresh(epoch, currentSession.refreshToken), init.signal);
    if (!refreshed) return firstResponse;
  }

  if (!replayAfterRefresh || init.signal?.aborted || getAuthEpoch() !== epoch) return firstResponse;
  const replaySession = readAuthSession();
  if (!replaySession) return firstResponse;

  const secondResponse = await fetchWithToken(input, init, replaySession.accessToken);
  if (secondResponse.status === 401 && !init.signal?.aborted && getAuthEpoch() === epoch
      && sameCredentials(readAuthSession(), replaySession)) {
    expireSession();
  }
  return secondResponse;
}

function fetchWithToken(input: RequestInfo | URL, init: RequestInit, accessToken?: string): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  return fetch(input, {
    ...init,
    headers,
  });
}
