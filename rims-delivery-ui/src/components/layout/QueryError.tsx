import type { ApiError } from "@/services/api";
import { ErrorState } from "@/components/ui/ErrorState";
import { Button } from "@/components/ui/Button";
import { copyFor } from "@/components/delivery/quoteErrors";

export function QueryError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const code = (error as ApiError)?.code;
  const forbidden = code === "FORBIDDEN";
  const c = copyFor(code);
  return (
    <ErrorState
      className="m-4 shadow-none"
      title={forbidden ? "You don’t have access to this" : c.title}
      description={
        forbidden
          ? "Ask an administrator to grant your account the right role."
          : c.body
      }
      icon={c.icon}
      tone={c.tone}
      actions={
        !forbidden && (
          <Button variant="secondary" onClick={onRetry}>
            Try again
          </Button>
        )
      }
    />
  );
}
