import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { auditApi } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { formatDateTime } from "@/utils/format";
import { useDebounced } from "@/utils/useDebounced";

const PAGE = 25;
export default function AuditLogPage() {
  const [page, setPage] = useState(1);
  const [entityType, setEntity] = useState("");
  const [search, setSearch] = useState("");
  const d = useDebounced(search);
  const params = { page, pageSize: PAGE, entityType, search: d };
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["audit", params],
    queryFn: () => auditApi.list(params),
    placeholderData: (p) => p,
  });
  return (
    <>
      <PageHeader
        title="Audit Log"
        description="A record of every change to destinations, rules, road types, vehicles and settings."
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-[1.5fr_1fr]">
        <Input
          label="Search"
          placeholder="Person or change"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
        <Select
          label="Record type"
          placeholder="All records"
          value={entityType}
          onChange={(e) => {
            setEntity(e.target.value);
            setPage(1);
          }}
          options={[
            ["destination", "Destinations"],
            ["pricing_rule", "Pricing rules"],
            ["road_type", "Road types"],
            ["vehicle", "Vehicles"],
            ["settings", "Settings"],
          ].map(([value, label]) => ({ value, label }))}
        />
      </div>
      <DataTable
        caption="Audit log"
        loading={isLoading}
        rows={data?.items}
        rowKey={(r) => r.id}
        page={page}
        pageSize={PAGE}
        total={data?.total}
        onPageChange={setPage}
        error={
          error ? (
            <QueryError error={error} onRetry={() => refetch()} />
          ) : undefined
        }
        empty={
          <EmptyState
            icon={FileText}
            title="No changes recorded"
            description="Changes made by administrators will be logged here."
          />
        }
        columns={[
          {
            key: "at",
            header: "When",
            cell: (r) => (
              <span className="whitespace-nowrap text-muted">
                {formatDateTime(r.at)}
              </span>
            ),
          },
          { key: "actor", header: "Who", cell: (r) => r.actor },
          {
            key: "action",
            header: "Action",
            cell: (r) => <span className="capitalize">{r.action}</span>,
          },
          {
            key: "entity",
            header: "Record",
            cell: (r) => (
              <span className="capitalize">
                {r.entityType.replace("_", " ")}
              </span>
            ),
          },
          { key: "summary", header: "Details", cell: (r) => r.summary },
        ]}
      />
    </>
  );
}
