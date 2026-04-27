import { createContext, useContext, useMemo, useState, type PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../shared/api/client";
import type { CurrentUserResponse } from "../../shared/api/types";
import { clearStoredToken, readStoredRefreshToken, readStoredToken, writeStoredToken } from "./auth-storage";


interface AuthContextValue {
  token: string | null;
  refreshToken: string | null;
  setToken: (token: string, refreshToken?: string | null) => void;
  clearToken: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [token, setTokenState] = useState<string | null>(() => readStoredToken());
  const [refreshToken, setRefreshTokenState] = useState<string | null>(() => readStoredRefreshToken());

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      refreshToken,
      setToken: (nextToken: string, nextRefreshToken?: string | null) => {
        writeStoredToken(nextToken, nextRefreshToken);
        setTokenState(nextToken);
        if (nextRefreshToken !== undefined) {
          setRefreshTokenState(nextRefreshToken || null);
        }
      },
      clearToken: () => {
        clearStoredToken();
        setTokenState(null);
        setRefreshTokenState(null);
      },
    }),
    [refreshToken, token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return context;
}

export function useCurrentUser() {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["auth", "me", token],
    queryFn: () => apiRequest<CurrentUserResponse>("/api/v1/auth/me"),
    enabled: Boolean(token),
    retry: false,
  });
}
