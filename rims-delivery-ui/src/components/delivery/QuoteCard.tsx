import type { ReactNode } from "react";
import { BadgeCheck, Info, Ruler } from "lucide-react";
import type { Quote } from "@/types";
import { PriceDisplay } from "@/components/ui/PriceDisplay";
import { formatKm, formatMinutes } from "@/utils/format";
import { cn } from "@/utils/cn";

function Row({
  label,
  children,
  mono,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-t border-line py-3 first:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className={cn("text-right font-medium", mono && "mono")}>
        {children}
      </dd>
    </div>
  );
}

/** Presents a backend-calculated quote. Rows only render when the API supplied the value. */
export function QuoteCard({
  quote,
  actions,
}: {
  quote: Quote;
  actions: ReactNode;
}) {
  const fee = quote.fee!;
  const distanceBased = quote.pricingModel === "distance_based";
  return (
    <section
      aria-labelledby="estimate-title"
      className="overflow-hidden rounded-lg border border-line bg-surface shadow-pop"
    >
      <div
        className={cn("h-1.5", distanceBased ? "bg-ink" : "bg-brand")}
        aria-hidden
      />
      <div className="p-6 sm:p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 id="estimate-title" className="text-small font-medium text-muted">
            Delivery estimate
          </h1>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-small font-semibold",
              distanceBased
                ? "bg-ink text-white"
                : "bg-brand-soft text-brand",
            )}
          >
            {distanceBased ? (
              <Ruler className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden />
            )}
            {distanceBased ? "Distance-based rate" : "Official RIMs price"}
          </span>
        </div>
        <PriceDisplay amount={fee.amount} className="mt-2" />
        <p className="mt-3 flex items-start gap-2 text-small text-muted">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {quote.pricingExplanation ??
            "Calculated using RIMs’ current delivery pricing rules."}
        </p>
      </div>
      <dl className="border-t border-line px-6 py-2 sm:px-8">
        {quote.destination ? (
          <Row label="Destination">{quote.destination.name}</Row>
        ) : distanceBased ? (
          <Row label="Destination">
            <span className="font-normal text-muted">
              Outside the standard price list
            </span>
          </Row>
        ) : null}
        {quote.durationMinutes != null && (
          <Row label="Estimated travel" mono>
            {formatMinutes(quote.durationMinutes)}
          </Row>
        )}
        {quote.distanceKm != null && (
          <Row label="Road distance" mono>
            {formatKm(quote.distanceKm)}
          </Row>
        )}
        {quote.route?.summary && (
          <Row label="Estimated route">{quote.route.summary}</Row>
        )}
        {quote.roadType && <Row label="Road type">{quote.roadType.name}</Row>}
        {quote.vehicle && <Row label="Vehicle">{quote.vehicle.name}</Row>}
        {quote.reference && <Row label="Your reference">{quote.reference}</Row>}
      </dl>
      <div className="flex flex-col gap-2.5 border-t border-line bg-canvas/60 p-4 sm:flex-row-reverse sm:px-8">
        {actions}
      </div>
    </section>
  );
}
