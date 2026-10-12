import { formatKES } from "@/utils/format";
import { cn } from "@/utils/cn";

export function PriceDisplay({
  amount,
  size = "xl",
  className,
}: {
  amount: number;
  size?: "md" | "xl";
  className?: string;
}) {
  return (
    <p
      className={cn("flex items-baseline gap-2 tabular-nums", className)}
      aria-label={`${formatKES(amount)} Kenya shillings`}
    >
      <span
        className={cn(
          "font-semibold text-muted",
          size === "xl" ? "text-h2" : "text-small",
        )}
        aria-hidden
      >
        KES
      </span>
      <span
        className={cn(
          "font-bold tracking-tight",
          size === "xl"
            ? "text-[3.5rem] leading-none sm:text-[4.25rem]"
            : "text-h1",
        )}
        aria-hidden
      >
        {formatKES(amount)}
      </span>
    </p>
  );
}
