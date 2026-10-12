import { type ReactNode, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { useAuth } from "@/features/auth/AuthProvider";
import type { Page } from "@/types";

interface Props<T extends { id: string; active: boolean }> {
  title: string;
  noun: string;
  description: string;
  icon: LucideIcon;
  data?: Page<T>;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  columns: Column<T>[];
  onCreate: () => void;
  onEdit: (r: T) => void;
  onToggle: (r: T) => void;
  toggling?: boolean;
  extraActions?: (r: T) => ReactNode;
  filters?: ReactNode;
  emptyHint?: string;
}

/** Standard list screen for admin-configurable records. Records are deactivated, never deleted. */
export function ResourceTable<
  T extends { id: string; active: boolean; name?: string },
>(p: Props<T>) {
  const { canEdit } = useAuth();
  const [confirm, setConfirm] = useState<T | null>(null);
  const columns: Column<T>[] = [
    ...p.columns,
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (r) =>
        canEdit ? (
          <div
            className="flex justify-end gap-1.5"
            onClick={(e) => e.stopPropagation()}
          >
            {p.extraActions?.(r)}
            <Button size="sm" variant="secondary" onClick={() => p.onEdit(r)}>
              Edit
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => (r.active ? setConfirm(r) : p.onToggle(r))}
            >
              {r.active ? "Deactivate" : "Activate"}
            </Button>
          </div>
        ) : null,
    },
  ];
  return (
    <>
      <PageHeader
        title={p.title}
        description={p.description}
        actions={
          canEdit && (
            <Button onClick={p.onCreate}>
              <Plus className="h-4 w-4" aria-hidden />
              New {p.noun}
            </Button>
          )
        }
      />
      {p.filters && (
        <div className="mb-4 flex flex-wrap gap-3">{p.filters}</div>
      )}
      <DataTable
        caption={p.title}
        columns={columns}
        rows={p.data?.items}
        rowKey={(r) => r.id}
        loading={p.loading}
        error={
          p.error ? (
            <QueryError error={p.error} onRetry={p.onRetry} />
          ) : undefined
        }
        empty={
          <EmptyState
            icon={p.icon}
            title={`No ${p.title.toLowerCase()} yet`}
            description={
              p.emptyHint ??
              `${p.noun[0].toUpperCase()}${p.noun.slice(1)} records you add here will appear in this list.`
            }
            action={
              canEdit ? (
                <Button onClick={p.onCreate}>
                  <Plus className="h-4 w-4" aria-hidden />
                  New {p.noun}
                </Button>
              ) : undefined
            }
          />
        }
      />
      <ConfirmDialog
        open={!!confirm}
        danger
        title={`Deactivate ${confirm?.name ?? p.noun}?`}
        loading={p.toggling}
        description="It will no longer be used by the pricing engine. Existing quotes keep their original price. You can reactivate it at any time."
        confirmLabel="Deactivate"
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm) p.onToggle(confirm);
          setConfirm(null);
        }}
      />
    </>
  );
}
