import type { ReactNode } from "react";
import { Breadcrumb, type Crumb } from "@/components/ui/Breadcrumb";
export function PageHeader({
  title,
  description,
  crumbs,
  actions,
}: {
  title: string;
  description?: string;
  crumbs?: Crumb[];
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 space-y-2">
      {crumbs && <Breadcrumb items={crumbs} />}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-h1">{title}</h1>
          {description && (
            <p className="mt-1 max-w-2xl text-muted">{description}</p>
          )}
        </div>
        {actions && <div className="flex gap-2.5">{actions}</div>}
      </div>
    </div>
  );
}
