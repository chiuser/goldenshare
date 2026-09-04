import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { login as loginRequest, logout as logoutRequest } from "../api/authApi";
import type { LoginRequest } from "../api/authTypes";
import { WEALTH_AUTH_REQUIRED_EVENT } from "./authEvents";
import { clearAuthSession, readAuthSession, saveAuthSession, type StoredAuthSession } from "./authStorage";
import { DEFAULT_LOGIN_TIMEOUT_MS } from "./loginPolicy";

type AuthStatus = "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  session: StoredAuthSession | null;
  login: (body: LoginRequest, options: { signal: AbortSignal }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredAuthSession | null>(() => readAuthSession());

  useEffect(() => {
    const handleAuthRequired = () => {
      clearAuthSession();
      setSession(null);
    };
    window.addEventListener(WEALTH_AUTH_REQUIRED_EVENT, handleAuthRequired);
    return () => window.removeEventListener(WEALTH_AUTH_REQUIRED_EVENT, handleAuthRequired);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status: session?.accessToken ? "authenticated" : "unauthenticated",
      session,
      async login(body, { signal }) {
        if (signal.aborted) throw new DOMException("登录已取消", "AbortError");
        const deadline = performance.now() + DEFAULT_LOGIN_TIMEOUT_MS;
        const controller = new AbortController();
        let terminalError: DOMException | undefined;
        let rejectControl!: (error: DOMException) => void;
        const control = new Promise<never>((_, reject) => { rejectControl = reject; });
        const cancel = (name: "AbortError" | "TimeoutError") => {
          if (terminalError) return;
          terminalError = new DOMException(name === "TimeoutError" ? "登录超时，请重试" : "登录已取消", name);
          // Preserve the terminal reason before abort can reject fetch/body parsing.
          rejectControl(terminalError);
          controller.abort();
        };
        const onAbort = () => cancel("AbortError");
        signal.addEventListener("abort", onAbort, { once: true });
        const timer = window.setTimeout(() => cancel("TimeoutError"), DEFAULT_LOGIN_TIMEOUT_MS);
        try {
          const payload = await Promise.race([loginRequest(body, controller.signal), control]);
          if (terminalError) throw terminalError;
          if (signal.aborted || controller.signal.aborted) throw new DOMException("登录已取消", "AbortError");
          // Timers can be delayed in background tabs; completion still has a hard deadline.
          if (performance.now() >= deadline) {
            cancel("TimeoutError");
            throw terminalError;
          }
          setSession(saveAuthSession(payload));
        } catch (error) {
          throw terminalError ?? error;
        } finally {
          window.clearTimeout(timer);
          signal.removeEventListener("abort", onAbort);
        }
      },
      async logout() {
        const currentSession = readAuthSession();
        clearAuthSession();
        setSession(null);
        try {
          await logoutRequest(
            {
              refresh_token: currentSession?.refreshToken ?? null,
            },
            currentSession?.accessToken,
          );
        } catch {
          // Local logout must succeed even if the server session is already invalid.
        }
      },
    }),
    [session],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
