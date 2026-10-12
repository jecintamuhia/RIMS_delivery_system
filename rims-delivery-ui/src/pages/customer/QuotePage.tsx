import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, MapPin, RefreshCw } from "lucide-react";
import { ApiError, quotesApi } from "@/services/api";
import { useQuote } from "@/features/delivery/hooks";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { QuoteCard } from "@/components/delivery/QuoteCard";
import { CalculatingSteps } from "@/components/delivery/CalculatingSteps";
import { ContactRims } from "@/components/delivery/ContactRims";
import { copyFor } from "@/components/delivery/quoteErrors";
import { MapCard } from "@/components/map/MapCard";
import { MapPicker } from "@/components/map/MapPicker";
import { usePublicConfig } from "@/features/delivery/hooks";
import { formatKm, formatMinutes } from "@/utils/format";
import type { Quote } from "@/types";

/** A fee is only shown when the backend returned a completed quote with every value the price
 *  depends on. A distance-based quote has no destination - being outside the price list is why
 *  it was priced from its road distance - so the destination is required only for the model
 *  that needs one. */
const hasTrustworthyFee = (q: Quote) =>
  (q.status === "completed" || q.status === "accepted") &&
  !!q.fee &&
  q.fee.amount > 0 &&
  q.distanceKm != null &&
  (q.pricingModel === "distance_based" || !!q.destination);

function Calculating({ quote }: { quote: Quote }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 45_000);
    return () => clearTimeout(t);
  }, []);
  return (
    <div
      className="mx-auto max-w-md px-5 py-16 sm:py-24"
      role="status"
      aria-live="polite"
    >
      <h1 className="text-h1">Calculating your delivery…</h1>
      <p className="mt-1.5 flex items-center gap-1.5 text-muted">
        <MapPin className="h-4 w-4" aria-hidden />
        {quote.location.label}
      </p>
      <div className="mt-8 rounded-lg border border-line bg-surface p-6 shadow-sm">
        <CalculatingSteps steps={quote.steps} />
      </div>
      {slow && (
        <p className="mt-5 text-small text-muted">
          This is taking longer than usual. You can keep waiting, or{" "}
          <Link to="/" className="font-medium text-brand underline">
            start again
          </Link>
          .
        </p>
      )}
    </div>
  );
}

export default function QuotePage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const config = usePublicConfig();
  const { data: quote, isPending, isError, error, refetch } = useQuote(id);
  const set = (q: Quote) => qc.setQueryData(["quote", id], q);
  const recalc = useMutation({
    mutationFn: () => quotesApi.recalculate(id),
    onSuccess: set,
  });
  const accept = useMutation({
    mutationFn: () => quotesApi.accept(id),
    onSuccess: set,
  });
  const [copied, setCopied] = useState(false);

  if (isPending)
    return (
      <div
        className="mx-auto grid max-w-6xl gap-6 p-5 lg:grid-cols-2 lg:p-10"
        aria-busy="true"
        aria-label="Loading estimate"
      >
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
      </div>
    );
  if (isError) {
    const c = copyFor((error as ApiError).code);
    return (
      <div className="mx-auto max-w-xl p-5 pt-12">
        <ErrorState
          title={c.title}
          description={c.body}
          icon={c.icon}
          tone={c.tone}
          actions={
            c.next === "retry" ? (
              <Button onClick={() => refetch()}>Try again</Button>
            ) : (
              <Button onClick={() => nav("/")}>Start a new estimate</Button>
            )
          }
        />
      </div>
    );
  }
  if (quote.status === "processing") return <Calculating quote={quote} />;

  if (!hasTrustworthyFee(quote)) {
    const code = quote.failure?.code ?? "MANUAL_REVIEW";
    const c = copyFor(code);
    return (
      <div className="mx-auto max-w-xl p-5 pt-10 sm:pt-16">
        <p className="mb-3 flex items-center gap-1.5 text-muted">
          <MapPin className="h-4 w-4" aria-hidden />
          {quote.location.label}
        </p>
        <ErrorState
          title={c.title}
          description={quote.failure?.message || c.body}
          icon={c.icon}
          tone={c.tone}
          actions={
            <>
              {c.next === "retry" && (
                <Button
                  loading={recalc.isPending}
                  onClick={() => recalc.mutate()}
                >
                  <RefreshCw className="h-4 w-4" aria-hidden />
                  Try again
                </Button>
              )}
              <Button
                variant={c.next === "retry" ? "secondary" : "primary"}
                onClick={() => nav("/")}
              >
                Change location
              </Button>
            </>
          }
        >
          {c.next === "contact" && <ContactRims />}
          {quote.failure?.candidates && (
            <ul className="space-y-1.5">
              {quote.failure.candidates.map((cand) => (
                <li
                  key={cand.id}
                  className="rounded border border-line px-3 py-2"
                >
                  {cand.label}
                </li>
              ))}
            </ul>
          )}
        </ErrorState>
        <p className="mt-4 text-small text-muted">Reference: {quote.id}</p>
      </div>
    );
  }

  const accepted = quote.status === "accepted";
  const actionError = (recalc.error || accept.error) as ApiError | null;
  return (
    <div className="mx-auto grid max-w-[1200px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:py-10">
      <div className="space-y-4">
        {accepted && (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg border border-brand/30 bg-brand-soft p-4"
          >
            <CheckCircle2
              className="mt-0.5 h-5 w-5 shrink-0 text-brand"
              aria-hidden
            />
            <div className="min-w-0">
              <p className="font-medium">Estimate saved with RIMs</p>
              <p className="text-small text-muted">
                Quote reference{" "}
                <span className="font-medium text-ink">{quote.id}</span>. Quote
                this when you place your order.
              </p>
              <button
                className="mt-1.5 inline-flex items-center gap-1.5 rounded text-small font-medium text-brand hover:underline"
                onClick={() => {
                  navigator.clipboard?.writeText(quote.id);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
              >
                <Copy className="h-3.5 w-3.5" aria-hidden />
                {copied ? "Copied" : "Copy reference"}
              </button>
            </div>
          </div>
        )}
        <QuoteCard
          quote={quote}
          actions={
            <>
              {!accepted && (
                <Button
                  size="lg"
                  loading={accept.isPending}
                  onClick={() => accept.mutate()}
                  className="sm:min-w-36"
                >
                  Continue
                </Button>
              )}
              <Button size="lg" variant="secondary" onClick={() => nav("/")}>
                Change location
              </Button>
              <Button
                size="lg"
                variant="ghost"
                loading={recalc.isPending}
                onClick={() => recalc.mutate()}
                className="sm:mr-auto"
              >
                <RefreshCw className="h-4 w-4" aria-hidden />
                Recalculate
              </Button>
            </>
          }
        />
        {actionError &&
          (() => {
            const c = copyFor(actionError.code);
            return (
              <ErrorState
                title={c.title}
                description={c.body}
                icon={c.icon}
                tone={c.tone}
              />
            );
          })()}
        <p className="px-1 text-small text-muted">Quote {quote.id}</p>
      </div>
      <MapCard
        className="h-[320px] rounded-lg border border-line shadow-sm lg:sticky lg:top-24 lg:h-[640px]"
        overlay={
          <div className="flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface/95 px-3 py-2 text-small shadow-pop backdrop-blur-sm">
            <span className="truncate font-medium">{quote.location.label}</span>
            {quote.distanceKm != null && (
              <span className="mono text-muted">
                {formatKm(quote.distanceKm)}
              </span>
            )}
            {quote.durationMinutes != null && (
              <span className="mono text-muted">
                {formatMinutes(quote.durationMinutes)}
              </span>
            )}
          </div>
        }
      >
        {config.data && (
          <MapPicker
            label={`Map showing the route to ${quote.location.label}`}
            interactive={false}
            center={config.data.map.center}
            zoom={config.data.map.zoom}
            tileUrl={config.data.map.tileUrl}
            attribution={config.data.map.attribution}
            dispatch={quote.dispatch ?? config.data.dispatch}
            marker={quote.location.position}
            route={quote.route?.geometry}
          />
        )}
      </MapCard>
    </div>
  );
}
