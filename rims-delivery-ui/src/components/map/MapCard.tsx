import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

/** Framed map surface with an optional overlay slot (e.g. location chip, hints). */
export function MapCard({
  children,
  overlay,
  className,
}: {
  children: ReactNode;
  overlay?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("relative isolate overflow-hidden bg-canvas", className)}
    >
      {children}
      {overlay && (
        <div className="pointer-events-none absolute inset-x-3 top-3 z-[500] flex">
          <div className="pointer-events-auto">{overlay}</div>
        </div>
      )}
    </div>
  );
}
