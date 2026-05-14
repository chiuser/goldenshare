import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { login as loginRequest, logout as logoutRequest } from "../api/authApi";
import type { LoginRequest } from "../api/authTypes";
import { WEALTH_AUTH_REQUIRED_EVENT } from "./authEvents";
import { clearAuthSession, readAuthSession, saveAuthSession, type StoredAuthSession } from "./authStorage";

type AuthStatus = "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  session: StoredAuthSession | null;
  login: (body: LoginRequest) => Promise<void>;
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
      async login(body) {
        const payload = await loginRequest(body);
        setSession(saveAuthSession(payload));
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

