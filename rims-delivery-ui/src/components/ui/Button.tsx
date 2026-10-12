import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/utils/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const variants: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-strong shadow-sm",
  secondary: "bg-surface text-ink border border-line hover:bg-canvas",
  ghost: "text-ink hover:bg-ink/5",
  danger: "bg-danger text-white hover:bg-danger/90",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-small gap-1.5",
  md: "h-10 px-4 text-body gap-2",
  lg: "h-12 px-5 text-body gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "md",
      loading,
      disabled,
      className,
      children,
      type = "button",
      ...rest
    },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          variants[variant],
          sizes[size],
          className,
        )}
        {...rest}
      >
        {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
        {children}
      </button>
    );
  },
);
