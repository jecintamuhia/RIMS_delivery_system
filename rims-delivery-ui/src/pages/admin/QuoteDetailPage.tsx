import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { adminQuotesApi } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { Skeleton } from "@/components/ui/Skeleton";
import { QuoteStatusBadge } from "@/components/ui/StatusBadge";
import { MapCard } from "@/components/map/MapCard";
import { MapPicker } from "@/components/map/MapPicker";
import { usePublicConfig } from "@/features/delivery/hooks";
import {
  formatCoords,
  formatDateTime,
  formatKES,
  formatKm,
} from "@/utils/format";

const Row = ({ k, children }: { k: string; children: ReactNode }) => (
  <div className="grid grid-cols-[10rem_1fr] gap-4 border-t border-line px-5 py-3 first:border-0">
    <dt className="text-muted">{k}</dt>
    <dd className="min-w-0 font-medium">{children}</dd>
  </div>
);
const money = (n: number) => `KES ${formatKES(n)}`;

export default function QuoteDetailPage() {
  const { id = "" } = useParams();
  const config = usePublicConfig();
  const {
    data: q,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["admin-quote", id],
    queryFn: () => adminQuotesApi.get(id),
  });
  const crumbs = [{ label: "Quotes", to: "/admin/quotes" }, { label: id }];
  if (error)
    return (
      <>
        <PageHeader title="Quote" crumbs={crumbs} />
        <QueryError error={error} onRetry={() => refetch()} />
      </>
    );
  if (isLoading || !q)
    return (
      <>
        <PageHeader title="Quote" crumbs={crumbs} />
        <div className="grid gap-6 lg:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </>
    );
  const b = q.breakdown;
  return (
    <>
      <PageHeader
        title={q.id}
        crumbs={crumbs}
        description={q.location.label}
        actions={<QuoteStatusBadge status={q.status} />}
      />
      {q.failure && (
        <p
          role="alert"
          className="mb-4 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-warn"
        >
          <strong>{q.failure.code.replace(/_/g, " ").toLowerCase()}.</strong>{" "}
          {q.failure.message}
        </p>
      )}
      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-6">
          <section
            aria-labelledby="inputs"
            className="rounded-lg border border-line bg-surface shadow-sm"
          >
            <h2
              id="inputs"
              className="border-b border-line px-5 py-3.5 text-h2"
            >
              Inputs and route
            </h2>
            <dl>
              <Row k="Destination">
                {q.destination?.name ??
                  (q.pricingModel === "distance_based"
                    ? "Outside the standard price list"
                    : "—")}
              </Row>
              <Row k="Coordinates">
                <span className="tabular-nums">
                  {formatCoords(q.location.position)}
                </span>
              </Row>
              <Row k="Road distance">
                {q.distanceKm != null ? formatKm(q.distanceKm) : "—"}
              </Row>
              <Row k="Route">{q.route?.summary ?? "—"}</Row>
              <Row k="Road type">{q.roadType?.name ?? "—"}</Row>
              <Row k="Vehicle">{q.vehicle?.name ?? "—"}</Row>
              <Row k="Reference">{q.reference || "—"}</Row>
              <Row k="Created">{formatDateTime(q.createdAt)}</Row>
            </dl>
          </section>
          <section
            aria-labelledby="calc"
            className="rounded-lg border border-line bg-surface shadow-sm"
          >
            <h2 id="calc" className="border-b border-line px-5 py-3.5 text-h2">
              How the price was calculated
            </h2>
            {!b ? (
              <p className="px-5 py-6 text-muted">
                No price was produced for this quote, so there is no breakdown.
              </p>
            ) : (
              <dl>
                <Row k="Pricing model">
                  {b.pricingModel === "distance_based"
                    ? "Distance-based (road distance × rate)"
                    : b.pricingModel === "fixed_destination"
                      ? "Official RIMs destination price"
                      : "—"}
                </Row>
                <Row k="Rule applied">{b.ruleLabel ?? b.ruleId ?? "—"}</Row>
                {b.pricingModel === "distance_based" ? (
                  <>
                    <Row k="Road distance">
                      <span className="tabular-nums">
                        {b.pricingDetails?.distanceKm
                          ? formatKm(Number(b.pricingDetails.distanceKm))
                          : "—"}
                      </span>
                    </Row>
                    <Row k="Rate per kilometre">
                      <span className="tabular-nums">
                        KES {b.pricingDetails?.effectiveRatePerKm ?? "—"}
                        {b.pricingDetails?.baseRatePerKm &&
                          ` (base KES ${b.pricingDetails.baseRatePerKm}${
                            b.pricingDetails.fuelAdjustmentPercent &&
                            b.pricingDetails.fuelAdjustmentPercent !== "0"
                              ? `, ${b.pricingDetails.fuelAdjustmentPercent}% fuel`
                              : ""
                          })`}
                      </span>
                    </Row>
                  </>
                ) : (
                  <Row k="Base destination price">
                    <span className="tabular-nums">
                      {money(b.basePrice.amount)}
                    </span>
                  </Row>
                )}
                <Row k="Adjustments">
                  {b.adjustments.length === 0 ? (
                    "None"
                  ) : (
                    <ul className="space-y-1">
                      {b.adjustments.map((a) => (
                        <li
                          key={a.label}
                          className="flex justify-between gap-3"
                        >
                          <span>{a.label}</span>
                          <span className="tabular-nums">
                            {a.amount.amount >= 0 ? "+" : "−"}
                            {money(Math.abs(a.amount.amount))}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Row>
                <Row k="Final delivery price">
                  <span className="text-h2 tabular-nums">
                    {q.fee ? money(q.fee.amount) : "—"}
                  </span>
                </Row>
                <Row k="Price list / rate">
                  {b.pricingVersion ?? b.pricingDetails?.configLabel ?? "—"}
                </Row>
              </dl>
            )}
          </section>
        </div>
        <MapCard className="h-[360px] rounded-lg border border-line shadow-sm lg:sticky lg:top-20 lg:h-[520px]">
          {config.data && (
            <MapPicker
              label={`Map for quote ${q.id}`}
              interactive={false}
              center={config.data.map.center}
              zoom={config.data.map.zoom}
              tileUrl={config.data.map.tileUrl}
              attribution={config.data.map.attribution}
              dispatch={q.dispatch ?? config.data.dispatch}
              marker={q.location.position}
              route={q.route?.geometry}
            />
          )}
        </MapCard>
      </div>
    </>
  );
}
