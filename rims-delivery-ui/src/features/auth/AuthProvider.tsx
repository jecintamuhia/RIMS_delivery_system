import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi, onSessionExpired } from "@/services/api";
import type { AdminUser } from "@/types";

interface AuthValue {
  user: AdminUser | null;
  loading: boolean;
  sessionExpired: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  canEdit: boolean;
}
const Ctx = createContext<AuthValue | null>(null);

/** Session lives in an httpOnly cookie set by the backend; no tokens are stored in JS. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [sessionExpired, setExpired] = useState(false);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: authApi.me,
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    onSessionExpired(() => {
      setExpired(true);
    });
    return () => onSessionExpired(null);
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const u = await authApi.login(email, password);
      qc.setQueryData(["me"], u);
      setExpired(false);
    },
    [qc],
  );
  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      qc.clear();
      qc.setQueryData(["me"], null);
      setExpired(false);
    }
  }, [qc]);

  const user = me.data ?? null;
  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading: me.isLoading,
      sessionExpired,
      signIn,
      signOut,
      canEdit: user?.role === "admin" || user?.role === "editor",
    }),
    [user, me.isLoading, sessionExpired, signIn, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const useAuth = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("AuthProvider missing");
  return c;
};
