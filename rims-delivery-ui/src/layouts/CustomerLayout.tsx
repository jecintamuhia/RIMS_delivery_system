import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { CinematicIntro } from "@/components/intro/CinematicIntro";
import { useIntro } from "@/components/intro/useIntro";
import { Brand } from "@/components/layout/Brand";
import { env } from "@/config/env";
import type { GeoLocation } from "@/types";
import {
  getScenario,
  scenarios,
  setScenario,
  type Scenario,
} from "@/services/mocks/scenario";

export { Brand } from "@/components/layout/Brand";

/** Shared between the intro and the calculator that sits beneath it. */
export interface CustomerOutletContext {
  /** Increments each time the opening hands over, to focus the location field. */
  searchFocus: number;
  /** A place picked inside the intro's device screen, if any. */
  pendingLocation: GeoLocation | null;
  consumePendingLocation: () => void;
  /** True while the opening is on screen, so the calculator can defer the map. */
  introVisible: boolean;
}

function MockBanner() {
  const [s, setS] = useState<Scenario>(getScenario());
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 bg-warn-soft px-4 py-1.5 text-small text-warn">
      <span>
        <strong>Mock API.</strong> Amounts shown are test data, not RIMs
        pricing.
      </span>
      <label className="flex items-center gap-2">
        Scenario
        <select
          value={s}
          onChange={(e) => {
            setScenario(e.target.value as Scenario);
            setS(e.target.value as Scenario);
          }}
          className="rounded border border-warn/30 bg-surface px-1.5 py-0.5 text-ink"
        >
          {scenarios.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export function CustomerLayout() {
  const location = useLocation();
  const intro = useIntro();
  const [searchFocus, setSearchFocus] = useState(0);
  const [pendingLocation, setPendingLocation] = useState<GeoLocation | null>(
    null,
  );

  // The opening belongs to the locate screen; the quote page is mid-task.
  const introVisible = intro.show && location.pathname === "/";

  const handleIntroDone = (picked?: GeoLocation) => {
    if (picked) setPendingLocation(picked);
    setSearchFocus((n) => n + 1);
    intro.dismiss();
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <div
        className="flex flex-1 flex-col"
        inert={introVisible ? true : undefined}
      >
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        {env.useMocks && <MockBanner />}
        <header className="sticky top-0 z-40 border-b border-line bg-surface/95 backdrop-blur">
          <div className="mx-auto flex h-16 max-w-[1400px] items-center justify-between px-4 sm:px-6">
            <Link
              to="/"
              className="rounded"
              aria-label="Delivery calculator home"
            >
              <Brand />
            </Link>
            <span className="hidden text-small text-muted sm:block">
              Delivery charges
            </span>
          </div>
        </header>
        <main id="main" className="flex-1">
          <Outlet
            context={
              {
                searchFocus,
                pendingLocation,
                consumePendingLocation: () => setPendingLocation(null),
                introVisible,
              } satisfies CustomerOutletContext
            }
          />
        </main>
      </div>

      {introVisible && <CinematicIntro onDone={handleIntroDone} />}
    </div>
  );
}
