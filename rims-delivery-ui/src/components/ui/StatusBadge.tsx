import { cn } from "@/utils/cn";
import type { QuoteStatus } from "@/types";

const tones = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  neutral: "bg-ink/5 text-muted",
};
export function StatusBadge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof tones;
  children: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-small font-medium",
        tones[tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {children}
    </span>
  );
}

const quoteMap: Record<QuoteStatus, [keyof typeof tones, string]> = {
  processing: ["neutral", "Calculating"],
  completed: ["ok", "Quoted"],
  accepted: ["ok", "Accepted"],
  needs_review: ["warn", "Needs review"],
  failed: ["danger", "Failed"],
};
export function QuoteStatusBadge({ status }: { status: QuoteStatus }) {
  const [tone, label] = quoteMap[status];
  return <StatusBadge tone={tone}>{label}</StatusBadge>;
}
export const ActiveBadge = ({ active }: { active: boolean }) => (
  <StatusBadge tone={active ? "ok" : "neutral"}>
    {active ? "Active" : "Inactive"}
  </StatusBadge>
);
