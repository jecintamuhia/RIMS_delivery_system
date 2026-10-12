import { AlertTriangle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

export function ErrorState({
  title,
  description,
  icon: Icon = AlertTriangle,
  actions,
  children,
  tone = "danger",
  className,
}: {
  title: string;
  description: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  children?: ReactNode;
  tone?: "danger" | "warn";
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg border border-line bg-surface p-6 shadow-sm",
        className,
      )}
    >
      <div
        className={cn(
          "mb-4 inline-flex rounded-full p-2.5",
          tone === "danger"
            ? "bg-danger-soft text-danger"
            : "bg-warn-soft text-warn",
        )}
      >
        <Icon className="h-5 w-5" aria-hidden />
      </div>
      <h2 className="text-h2">{title}</h2>
      <p className="mt-1.5 max-w-prose text-muted">{description}</p>
      {children && <div className="mt-4">{children}</div>}
      {actions && <div className="mt-5 flex flex-wrap gap-2.5">{actions}</div>}
    </div>
  );
}
