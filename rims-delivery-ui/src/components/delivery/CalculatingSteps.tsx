import { Check, Loader2, X } from "lucide-react";
import type { QuoteStep, StepKey } from "@/types";
import { cn } from "@/utils/cn";

const labels: Record<StepKey, string> = {
  location: "Finding location",
  route: "Calculating road distance",
  destination: "Determining delivery area",
  pricing: "Applying RIMs pricing",
  estimate: "Preparing estimate",
};
const order: StepKey[] = [
  "location",
  "route",
  "destination",
  "pricing",
  "estimate",
];

/** Renders step state exactly as reported by the backend. Nothing is shown complete unless the API says so. */
export function CalculatingSteps({ steps }: { steps: QuoteStep[] }) {
  const byKey = new Map(steps.map((s) => [s.key, s.state]));
  return (
    <ol className="space-y-3.5" aria-label="Calculation progress">
      {order.map((k) => {
        const state = byKey.get(k) ?? "pending";
        return (
          <li
            key={k}
            className="flex items-center gap-3"
            aria-current={state === "running" ? "step" : undefined}
          >
            <span
              className={cn(
                "grid h-6 w-6 shrink-0 place-items-center rounded-full border text-white transition-colors",
                state === "completed" && "border-brand bg-brand",
                state === "failed" && "border-danger bg-danger",
                state === "running" && "border-brand text-brand",
                state === "pending" && "border-line",
              )}
            >
              {state === "completed" && (
                <Check className="h-3.5 w-3.5" aria-hidden />
              )}
              {state === "failed" && <X className="h-3.5 w-3.5" aria-hidden />}
              {state === "running" && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              )}
            </span>
            <span
              className={cn(
                state === "pending" ? "text-muted" : "text-ink",
                state === "running" && "font-medium",
              )}
            >
              {labels[k]}
              <span className="sr-only">
                {" "}
                —{" "}
                {state === "completed"
                  ? "done"
                  : state === "running"
                    ? "in progress"
                    : state === "failed"
                      ? "failed"
                      : "waiting"}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
