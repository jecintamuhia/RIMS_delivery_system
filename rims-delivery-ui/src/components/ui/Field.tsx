import { useId, type ReactNode } from "react";
import { cn } from "@/utils/cn";

export interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  optional?: boolean;
  className?: string;
}

/** Provides ids and aria wiring for any single form control. */
export function Field({
  label,
  hint,
  error,
  optional,
  className,
  children,
}: FieldProps & {
  children: (p: {
    id: string;
    describedBy?: string;
    invalid: boolean;
  }) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={id}
        className="flex items-baseline justify-between text-small font-medium"
      >
        <span>{label}</span>
        {optional && <span className="font-normal text-muted">Optional</span>}
      </label>
      {children({ id, describedBy, invalid: !!error })}
      {hint && !error && (
        <p id={hintId} className="text-small text-muted">
          {hint}
        </p>
      )}
      <p id={errId} aria-live="polite" className="text-small text-danger">
        {error}
      </p>
    </div>
  );
}

export const controlClass = (invalid: boolean) =>
  cn(
    "h-10 w-full rounded border bg-surface px-3 text-body placeholder:text-muted/70 transition-colors hover:border-ink/30 disabled:bg-canvas disabled:text-muted",
    invalid ? "border-danger" : "border-line",
  );
