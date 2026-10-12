import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Brand } from "@/layouts/CustomerLayout";
import { useAuth } from "@/features/auth/AuthProvider";
import { loginSchema, type LoginForm } from "@/schemas";
import type { ApiError } from "@/services/api";

export default function LoginPage() {
  const { user, signIn } = useAuth();
  const nav = useNavigate();
  const from =
    (useLocation().state as { from?: string } | null)?.from ?? "/admin";
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });
  if (user) return <Navigate to={from} replace />;
  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <form
        noValidate
        onSubmit={handleSubmit(async (v) => {
          setError(null);
          try {
            await signIn(v.email, v.password);
            nav(from, { replace: true });
          } catch (e) {
            const c = (e as ApiError).code;
            setError(
              c === "INVALID_CREDENTIALS"
                ? "That email and password don’t match. Check them and try again."
                : c === "NETWORK"
                  ? "We couldn’t reach the server. Check your connection and try again."
                  : "Sign in didn’t complete. Try again in a moment.",
            );
          }
        })}
        className="w-full max-w-sm space-y-5 rounded-lg border border-line bg-surface p-7 shadow-sm"
      >
        <Brand />
        <div>
          <h1 className="text-h1">Sign in</h1>
          <p className="mt-1 text-muted">RIMs delivery administration</p>
        </div>
        {error && (
          <p
            role="alert"
            className="rounded bg-danger-soft px-3 py-2 text-small text-danger"
          >
            {error}
          </p>
        )}
        <Input
          label="Email"
          type="email"
          autoComplete="username"
          error={errors.email?.message}
          {...register("email")}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <Button
          type="submit"
          size="lg"
          className="w-full"
          loading={isSubmitting}
        >
          Sign in
        </Button>
      </form>
    </div>
  );
}
