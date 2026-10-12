import { lazy, Suspense } from "react";
import { Skeleton } from "@/components/ui/Skeleton";
import type { MapCanvasProps } from "./types";

const MapCanvas = lazy(() => import("./providers/leaflet"));

export function MapPicker(props: MapCanvasProps) {
  return (
    <Suspense fallback={<Skeleton className="h-full w-full rounded-none" />}>
      <MapCanvas {...props} />
    </Suspense>
  );
}
