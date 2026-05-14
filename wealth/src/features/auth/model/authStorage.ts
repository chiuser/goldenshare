import type { TokenResponse } from "../api/authTypes";

const ACCESS_TOKEN_KEY = "wealth.auth.access-token";
const REFRESH_TOKEN_KEY = "wealth.auth.refresh-token";
const EXPIRES_AT_KEY = "wealth.auth.expires-at";
const USERNAME_KEY = "wealth.auth.username";
const DISPLAY_NAME_KEY = "wealth.auth.display-name";

export interface StoredAuthSession {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt?: string | null;
  username?: string | null;
  displayName?: string | null;
}

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

export function readAuthSession(): StoredAuthSession | null {
  const storage = getStorage();
  if (!storage) return null;
  const accessToken = storage.getItem(ACCESS_TOKEN_KEY);
  if (!accessToken) return null;
  return {
    accessToken,
    refreshToken: storage.getItem(REFRESH_TOKEN_KEY),
    expiresAt: storage.getItem(EXPIRES_AT_KEY),
    username: storage.getItem(USERNAME_KEY),
    displayName: storage.getItem(DISPLAY_NAME_KEY),
  };
}

export function saveAuthSession(payload: TokenResponse): StoredAuthSession {
  const storage = getStorage();
  const session: StoredAuthSession = {
    accessToken: payload.token,
    refreshToken: payload.refresh_token ?? null,
    expiresAt: payload.access_token_expires_at ?? null,
    username: payload.username,
    displayName: payload.display_name ?? null,
  };
  if (!storage) return session;
  storage.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  setOrRemove(storage, REFRESH_TOKEN_KEY, session.refreshToken);
  setOrRemove(storage, EXPIRES_AT_KEY, session.expiresAt);
  setOrRemove(storage, USERNAME_KEY, session.username);
  setOrRemove(storage, DISPLAY_NAME_KEY, session.displayName);
  return session;
}

export function clearAuthSession() {
  const storage = getStorage();
  if (!storage) return;
  storage.removeItem(ACCESS_TOKEN_KEY);
  storage.removeItem(REFRESH_TOKEN_KEY);
  storage.removeItem(EXPIRES_AT_KEY);
  storage.removeItem(USERNAME_KEY);
  storage.removeItem(DISPLAY_NAME_KEY);
}

function setOrRemove(storage: Storage, key: string, value?: string | null) {
  if (value) {
    storage.setItem(key, value);
  } else {
    storage.removeItem(key);
  }
}

