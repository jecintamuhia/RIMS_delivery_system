import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import { LoadingState } from "@/components/ui/LoadingState";

/** Client-side guard for UX only. Every admin endpoint is also authorised by the backend. */
export function RequireAuth() {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading)
    return (
      <LoadingState label="Checking your session…" className="min-h-dvh" />
    );
  if (!user)
    return (
      <Navigate
        to="/admin/login"
        replace
        state={{ from: loc.pathname + loc.search }}
      />
    );
  return <Outlet />;
}
