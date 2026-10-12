import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Skeleton } from "./Skeleton";
import { Button } from "./Button";
import { cn } from "@/utils/cn";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  align?: "right";
  className?: string;
}
interface Props<T> {
  columns: Column<T>[];
  rows?: T[];
  rowKey: (r: T) => string;
  loading?: boolean;
  caption: string;
  onRowClick?: (r: T) => void;
  empty?: ReactNode;
  error?: ReactNode;
  page?: number;
  pageSize?: number;
  total?: number;
  onPageChange?: (p: number) => void;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  caption,
  onRowClick,
  empty,
  error,
  page = 1,
  pageSize = 20,
  total = 0,
  onPageChange,
}: Props<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-sm">
      {error ?? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-left text-body">
              <caption className="sr-only">{caption}</caption>
              <thead>
                <tr className="border-b border-line bg-canvas/70 text-small text-muted">
                  {columns.map((c) => (
                    <th
                      key={c.key}
                      scope="col"
                      className={cn(
                        "px-4 py-2.5 font-medium",
                        c.align === "right" && "text-right",
                      )}
                    >
                      {c.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading &&
                  Array.from({ length: 6 }, (_, i) => (
                    <tr key={i} className="border-b border-line last:border-0">
                      {columns.map((c) => (
                        <td key={c.key} className="px-4 py-3.5">
                          <Skeleton className="h-4 w-24 max-w-full" />
                        </td>
                      ))}
                    </tr>
                  ))}
                {!loading &&
                  rows?.map((r) => (
                    <tr
                      key={rowKey(r)}
                      tabIndex={onRowClick ? 0 : undefined}
                      onClick={() => onRowClick?.(r)}
                      onKeyDown={(e) => {
                        if (onRowClick && e.key === "Enter") onRowClick(r);
                      }}
                      className={cn(
                        "border-b border-line last:border-0",
                        onRowClick &&
                          "cursor-pointer hover:bg-canvas/70 focus-visible:bg-canvas/70",
                      )}
                    >
                      {columns.map((c) => (
                        <td
                          key={c.key}
                          className={cn(
                            "px-4 py-3",
                            c.align === "right" && "text-right tabular-nums",
                            c.className,
                          )}
                        >
                          {c.cell(r)}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {!loading && rows?.length === 0 && empty}
          {onPageChange && total > pageSize && (
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-small text-muted">
              <span>
                Page {page} of {pages} · {total} results
              </span>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label="Previous page"
                  disabled={page <= 1}
                  onClick={() => onPageChange(page - 1)}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label="Next page"
                  disabled={page >= pages}
                  onClick={() => onPageChange(page + 1)}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
