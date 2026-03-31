import { createContext, useContext, useMemo, useState, type PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../shared/api/client";
import type { CurrentUserResponse } from "../../shared/api/types";
import { clearStoredToken, readStoredToken, writeStoredToken } from "./auth-storage";


interface AuthContextValue {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [token, setTokenState] = useState<string | null>(() => readStoredToken());

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      setToken: (nextToken: string) => {
        writeStoredToken(nextToken);
        setTokenState(nextToken);
      },
      clearToken: () => {
        clearStoredToken();
        setTokenState(null);
      },
    }),
    [token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}

export function useCurrentUser() {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["auth", "me", token],
    queryFn: () => apiRequest<CurrentUserResponse>("/api/v1/auth/me", { token }),
    enabled: Boolean(token),
    retry: false,
  });
}
