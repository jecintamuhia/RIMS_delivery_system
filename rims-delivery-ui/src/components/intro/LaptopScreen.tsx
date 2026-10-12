import { useState, type RefObject } from "react";
import { MousePointerClick } from "lucide-react";
import { MapPicker } from "@/components/map/MapPicker";
import { SearchInput } from "@/components/ui/SearchInput";
import { Skeleton } from "@/components/ui/Skeleton";
import { useLocationSearch, usePublicConfig } from "@/features/delivery/hooks";
import type { GeoLocation } from "@/types";


export function LaptopScreen({
  onStart,
  screenRef,
}: {
  onStart: (location?: GeoLocation) => void;
  screenRef: RefObject<HTMLDivElement | null>;
}) {
  const config = usePublicConfig();
  const cfg = config.data;
  const [text, setText] = useState("");
  const search = useLocationSearch(text);

  return (
    <div className="intro-laptop">
      <div className="intro-laptop__lid">
        <div className="intro-laptop__screen" ref={screenRef}>
          {cfg ? (
            <MapPicker
              label="RIMs dispatch on the delivery map"
              center={cfg.map.center}
              zoom={Math.max(cfg.map.zoom, 12)}
              tileUrl={cfg.map.tileUrl}
              attribution={cfg.map.attribution}
              dispatch={cfg.dispatch}
              interactive={false}
            />
          ) : (
            <Skeleton className="h-full w-full rounded-none" />
          )}
          <button
            type="button"
            aria-label="Open the delivery calculator"
            className="absolute inset-0 z-0 cursor-pointer bg-brand/0 transition-colors hover:bg-brand/10"
            onClick={() => onStart()}
          />
          <span className="intro-scan pointer-events-none absolute inset-0 z-[1]" aria-hidden />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[2] flex items-center justify-center gap-2 bg-gradient-to-t from-ink/80 to-transparent px-3 pb-2.5 pt-8 text-small font-medium text-white">
            <MousePointerClick className="h-4 w-4" aria-hidden />
            Click to calculate your delivery
          </div>
        </div>
      </div>
      <div className="intro-laptop__base" aria-hidden />

      <div className="intro-laptop__search">
        <SearchInput
          hideLabel
          label="Delivery location"
          value={text}
          onChange={setText}
          results={search.data}
          loading={search.isFetching}
          placeholder="Search a delivery location"
          onSelect={(r) => onStart(r as GeoLocation)}
        />
      </div>
    </div>
  );
}
