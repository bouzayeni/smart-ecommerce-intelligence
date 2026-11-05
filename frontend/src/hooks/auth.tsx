import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, refreshSession, setSessionExpiredHandler, tokens } from "../services/api";
import type { Role, Tokens, User } from "../types/api";
import { AuthContext } from "./useAuth";

const RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      tokens.clear();
      setUser(null);
    });
    // Restore a session after reload from the refresh token, if any.
    (async () => {
      if (await refreshSession()) {
        try {
          setUser((await api.get<User>("/auth/me")).data);
        } catch {
          tokens.clear();
        }
      }
      setReady(true);
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post<Tokens>("/auth/login", { email, password });
    tokens.set(data);
    setUser((await api.get<User>("/auth/me")).data);
  }, []);

  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      await api.post("/auth/register", { email, password, full_name: fullName });
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    const refresh = tokens.refreshToken();
    try {
      if (refresh) await api.post("/auth/logout", { refresh_token: refresh });
    } finally {
      tokens.clear();
      setUser(null);
    }
  }, []);

  const hasRole = useCallback((minimum: Role) => !!user && RANK[user.role] >= RANK[minimum], [user]);

  const value = useMemo(
    () => ({ user, ready, login, register, logout, hasRole }),
    [user, ready, login, register, logout, hasRole],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
