import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
export interface Crumb {
  label: string;
  to?: string;
}
export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1 text-small text-muted">
        {items.map((c, i) => (
          <li key={c.label} className="flex items-center gap-1">
            {c.to && i < items.length - 1 ? (
              <Link
                to={c.to}
                className="rounded hover:text-ink hover:underline"
              >
                {c.label}
              </Link>
            ) : (
              <span
                aria-current={i === items.length - 1 ? "page" : undefined}
                className={i === items.length - 1 ? "text-ink" : ""}
              >
                {c.label}
              </span>
            )}
            {i < items.length - 1 && (
              <ChevronRight className="h-3.5 w-3.5" aria-hidden />
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
