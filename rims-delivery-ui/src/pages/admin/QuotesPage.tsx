import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Receipt } from "lucide-react";
import { adminQuotesApi, destinationsApi } from "@/services/api";
import { useOptions } from "@/features/crud";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { QuoteStatusBadge } from "@/components/ui/StatusBadge";
import { formatDateTime, formatKES, formatKm } from "@/utils/format";
import { useEffect, useState } from "react";
import { useDebounced } from "@/utils/useDebounced";
import type { Quote } from "@/types";

type Row = Quote & { destinationName?: string };
const PAGE = 20;

export default function QuotesPage() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const get = (k: string) => sp.get(k) ?? "";
  const set = (k: string, v: string) =>
    setSp(
      (p) => {
        v ? p.set(k, v) : p.delete(k);
        if (k !== "page") p.delete("page");
        return p;
      },
      { replace: true },
    );
  const [search, setSearch] = useState(get("search"));
  const dSearch = useDebounced(search);
  useEffect(() => {
    if (dSearch !== get("search")) set("search", dSearch);
  }, [dSearch]); // eslint-disable-line
  const page = Number(get("page") || 1);
  const params = {
    page,
    pageSize: PAGE,
    search: get("search"),
    status: get("status"),
    destinationId: get("destinationId"),
    from: get("from"),
    to: get("to"),
  };
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["quotes", params],
    queryFn: () => adminQuotesApi.list(params),
    placeholderData: (p) => p,
  });
  const dests = useOptions("destinations", destinationsApi);
  const filtered = Object.entries(params).some(
    ([k, v]) => !["page", "pageSize"].includes(k) && v,
  );

  const columns: Column<Row>[] = [
    {
      key: "id",
      header: "Quote ID",
      cell: (r) => <span className="font-medium">{r.id}</span>,
    },
    {
      key: "ref",
      header: "Customer / reference",
      cell: (r) => r.reference || <span className="text-muted">—</span>,
    },
    {
      key: "dest",
      header: "Destination",
      cell: (r) =>
        r.destinationName ??
        r.destination?.name ?? (
          <span className="text-muted">{r.location.label}</span>
        ),
    },
    {
      key: "dist",
      header: "Distance",
      align: "right",
      cell: (r) => (r.distanceKm != null ? formatKm(r.distanceKm) : "—"),
    },
    { key: "road", header: "Road type", cell: (r) => r.roadType?.name ?? "—" },
    { key: "veh", header: "Vehicle", cell: (r) => r.vehicle?.name ?? "—" },
    {
      key: "fee",
      header: "Delivery fee",
      align: "right",
      cell: (r) => (r.fee ? `KES ${formatKES(r.fee.amount)}` : "—"),
    },
    {
      key: "status",
      header: "Status",
      cell: (r) => <QuoteStatusBadge status={r.status} />,
    },
    {
      key: "at",
      header: "Created",
      cell: (r) => (
        <span className="whitespace-nowrap text-muted">
          {formatDateTime(r.createdAt)}
        </span>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title="Quotes"
        description="Every delivery estimate generated for customers."
      />
      <form
        role="search"
        aria-label="Filter quotes"
        className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_auto_auto_auto]"
        onSubmit={(e) => e.preventDefault()}
      >
        <Input
          label="Search"
          placeholder="Quote ID or reference"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Select
          label="Destination"
          placeholder="All destinations"
          value={get("destinationId")}
          onChange={(e) => set("destinationId", e.target.value)}
          options={(dests.data?.items ?? []).map((d) => ({
            value: d.id,
            label: d.name,
          }))}
        />
        <Select
          label="Status"
          placeholder="All statuses"
          value={get("status")}
          onChange={(e) => set("status", e.target.value)}
          options={[
            ["completed", "Quoted"],
            ["accepted", "Accepted"],
            ["needs_review", "Needs review"],
            ["failed", "Failed"],
            ["processing", "Calculating"],
          ].map(([value, label]) => ({ value, label }))}
        />
        <Input
          label="From"
          type="date"
          value={get("from")}
          onChange={(e) => set("from", e.target.value)}
        />
        <Input
          label="To"
          type="date"
          value={get("to")}
          onChange={(e) => set("to", e.target.value)}
        />
        {filtered && (
          <Button
            variant="ghost"
            className="self-end"
            onClick={() => {
              setSearch("");
              setSp({}, { replace: true });
            }}
          >
            Clear
          </Button>
        )}
      </form>
      <DataTable<Row>
        caption="Quotes"
        columns={columns}
        rows={data?.items}
        rowKey={(r) => r.id}
        loading={isLoading}
        onRowClick={(r) => nav(`/admin/quotes/${r.id}`)}
        page={page}
        pageSize={PAGE}
        total={data?.total}
        onPageChange={(p) => set("page", String(p))}
        error={
          error ? (
            <QueryError error={error} onRetry={() => refetch()} />
          ) : undefined
        }
        empty={
          <EmptyState
            icon={Receipt}
            title={filtered ? "No quotes match these filters" : "No quotes yet"}
            description={
              filtered
                ? "Try widening the date range or clearing a filter."
                : "Quotes appear here as soon as customers request a delivery estimate."
            }
          />
        }
      />
    </>
  );
}
