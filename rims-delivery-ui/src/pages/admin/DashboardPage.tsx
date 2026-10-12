import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Inbox,
  Layers,
  MapPin,
  ShieldAlert,
} from "lucide-react";
import { dashboardApi, settingsApi } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDateTime, formatKES, formatKm } from "@/utils/format";

function Metric({
  label,
  value,
  loading,
}: {
  label: string;
  value: string;
  loading: boolean;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-5 shadow-sm">
      <p className="text-small text-muted">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-24" />
      ) : (
        <p className="mt-1 text-[1.75rem] font-semibold tabular-nums tracking-tight">
          {value}
        </p>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const {
    data,
    isLoading: dashLoading,
    error: dashError,
    refetch: dashRefetch,
  } = useQuery({
    queryKey: ["dashboard"],
    queryFn: dashboardApi.summary,
  });

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: settingsApi.get,
  });

  if (dashError)
    return (
      <>
        <PageHeader title="Delivery Operations Dashboard" />
        <QueryError error={dashError} onRetry={() => dashRefetch()} />
      </>
    );

  const empty = data && data.quotesThisWeek === 0;
  const max = Math.max(
    1,
    ...(data?.topDestinations.map((d) => d.count) ?? [1]),
  );

  return (
    <>
      <PageHeader
        title="Delivery Operations"
        description="Live overview of RIMs delivery pricing, quote requests, and exceptions."
      />

      {/* Operational Status Banner */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border border-line bg-surface p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-small text-muted flex items-center gap-1.5 font-medium">
              <Layers className="h-4 w-4 text-brand" aria-hidden />
              Pricing Version
            </span>
            <Link
              to="/admin/pricing-versions"
              className="text-small font-medium text-brand hover:underline"
            >
              Manage
            </Link>
          </div>
          <div className="mt-2 flex items-center gap-2">
            {settings?.activePricingVersion ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-brand" aria-hidden />
                <span className="font-semibold text-ink text-small truncate">
                  {settings.activePricingVersion}
                </span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-4 w-4 text-warn" aria-hidden />
                <span className="font-semibold text-warn text-small">
                  Draft list needs activation
                </span>
              </>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-line bg-surface p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-small text-muted flex items-center gap-1.5 font-medium">
              <MapPin className="h-4 w-4 text-brand" aria-hidden />
              Dispatch Origin
            </span>
            <Link
              to="/admin/settings"
              className="text-small font-medium text-brand hover:underline"
            >
              Depot Map
            </Link>
          </div>
          <div className="mt-2 truncate font-semibold text-ink text-small">
            {settings?.dispatch.name ?? "Kenyatta Ave, Naivasha"}
          </div>
        </div>

        <div className="rounded-lg border border-line bg-surface p-4 shadow-xs sm:col-span-2 lg:col-span-1">
          <div className="flex items-center justify-between">
            <span className="text-small text-muted flex items-center gap-1.5 font-medium">
              <ShieldAlert className="h-4 w-4 text-warn" aria-hidden />
              Manual Quote Requests
            </span>
            <Link
              to="/admin/quotes"
              className="text-small font-medium text-brand hover:underline"
            >
              View Quotes
            </Link>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-h2 font-semibold tabular-nums text-ink">
              {data?.needsReview.length ?? 0}
            </span>
            <span className="text-small text-muted">
              {data?.needsReview.length === 1
                ? "quote awaiting operator price"
                : "quotes awaiting operator price"}
            </span>
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          loading={dashLoading}
          label="Quotes today"
          value={String(data?.quotesToday ?? 0)}
        />
        <Metric
          loading={dashLoading}
          label="Quotes this week"
          value={String(data?.quotesThisWeek ?? 0)}
        />
        <Metric
          loading={dashLoading}
          label="Total quoted delivery value"
          value={data ? `KES ${formatKES(data.totalQuotedValue.amount)}` : "—"}
        />
        <Metric
          loading={dashLoading}
          label="Average delivery road distance"
          value={
            data?.averageDistanceKm != null
              ? formatKm(data.averageDistanceKm)
              : "—"
          }
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {/* Most Requested Destinations */}
        <section
          aria-labelledby="top-d"
          className="rounded-lg border border-line bg-surface shadow-sm"
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 id="top-d" className="text-h2 font-medium">
              Most requested destinations
            </h2>
            <Link
              to="/admin/destinations"
              className="text-small font-medium text-brand hover:underline"
            >
              All Destinations
            </Link>
          </div>
          {dashLoading ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-5" />
              <Skeleton className="h-5" />
              <Skeleton className="h-5" />
            </div>
          ) : empty || !data?.topDestinations.length ? (
            <EmptyState
              icon={BarChart3}
              title="No quotes requested yet"
              description="Destinations appear here once customers start calculating delivery fees."
            />
          ) : (
            <ul className="space-y-3.5 p-5">
              {data.topDestinations.map((d) => (
                <li key={d.name}>
                  <div className="flex justify-between text-body">
                    <span className="font-medium">{d.name}</span>
                    <span className="tabular-nums text-muted">{d.count}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-ink/5">
                    <div
                      className="h-full rounded-full bg-brand"
                      style={{ width: `${(d.count / max) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Pricing Exceptions to Review */}
        <section
          aria-labelledby="rev"
          className="rounded-lg border border-line bg-surface shadow-sm"
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <div className="flex items-center gap-2">
              <h2 id="rev" className="text-h2 font-medium">
                Pricing exceptions to review
              </h2>
              {!!data?.needsReview.length && (
                <span className="rounded-full bg-warn-soft px-2 py-0.5 text-small font-semibold text-warn">
                  {data.needsReview.length}
                </span>
              )}
            </div>
            <Link
              to="/admin/quotes"
              className="text-small font-medium text-brand hover:underline"
            >
              All Quotes
            </Link>
          </div>
          {dashLoading ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : !data?.needsReview.length ? (
            <EmptyState
              icon={Inbox}
              title="Nothing needs manual review"
              description="Quotes for unconfigured destinations or locations requiring custom quotation appear here."
            />
          ) : (
            <ul className="divide-y divide-line">
              {data.needsReview.map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/admin/quotes/${r.id}`}
                    className="flex items-start justify-between gap-3 px-5 py-3.5 hover:bg-canvas/70 transition-colors"
                  >
                    <div className="flex items-start gap-3 min-w-0">
                      <AlertTriangle
                        className="mt-0.5 h-4 w-4 shrink-0 text-warn"
                        aria-hidden
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-ink">
                          {r.locationLabel}
                        </span>
                        <span className="block text-small text-muted">
                          {r.reason ?? "Needs manual quotation"} ·{" "}
                          {formatDateTime(r.createdAt)}
                        </span>
                      </span>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
