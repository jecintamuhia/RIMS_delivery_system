import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {Icon && (
        <div className="mb-4 rounded-full border border-line bg-surface p-3 text-muted">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      )}
      <h3 className="text-h2">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-muted">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
