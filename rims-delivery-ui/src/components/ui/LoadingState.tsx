import { Loader2 } from "lucide-react";
import { cn } from "@/utils/cn";
export function LoadingState({
  label = "Loading…",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-center justify-center gap-2.5 py-16 text-muted",
        className,
      )}
    >
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
      <span>{label}</span>
    </div>
  );
}
