import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { ArrowRight, X } from "lucide-react";
import { Brand } from "@/components/layout/Brand";
import { usePublicConfig } from "@/features/delivery/hooks";
import { cn } from "@/utils/cn";
import type { GeoLocation } from "@/types";
import {
  CLOSE_DURATION_MS,
  LOGO_CANDIDATES,
  LOGO_DWELL_MS,
  SCENE_DWELL_MS,
  STORE_SCENES,
  preloadImage,
} from "./assets";
import { LaptopScreen } from "./LaptopScreen";
import { usePrefersReducedMotion } from "./useIntro";

interface Props {

  onDone: (location?: GeoLocation) => void;
}


function IntroLogo({
  className,
  light = true,
}: {
  className?: string;
  light?: boolean;
}) {
  const config = usePublicConfig();
  const candidates = useMemo(() => {
    const list = [config.data?.company.logoUrl, ...LOGO_CANDIDATES].filter(
      Boolean,
    ) as string[];
    return Array.from(new Set(list));
  }, [config.data?.company.logoUrl]);
  const [index, setIndex] = useState(0);
  const [exhausted, setExhausted] = useState(false);

  if (exhausted || candidates.length === 0) {
    return <Brand light={light} className={className} />;
  }
  return (
    <img
      src={candidates[index]}
      alt={config.data?.company.name ?? "RIMs Supplies & Hardware"}
      className={className}
      decoding="async"
      onError={() => {
        if (index + 1 < candidates.length) setIndex(index + 1);
        else setExhausted(true);
      }}
    />
  );
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return matches;
}

export function CinematicIntro({ onDone }: Props) {
  const reduced = usePrefersReducedMotion();
  const isDesktop = useMediaQuery("(min-width: 768px)");

  const [step, setStep] = useState(0); // 0 logo reveal · 1..n store scenes, looping forever
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const [closing, setClosing] = useState(false);
  const [morph, setMorph] = useState<DOMRect | null>(null);
  const [morphFull, setMorphFull] = useState(false);
  const [faded, setFaded] = useState(false);

  const screenRef = useRef<HTMLDivElement>(null);
  const ctaRef = useRef<HTMLButtonElement>(null);
  const timers = useRef<number[]>([]);
  const closingRef = useRef(false);

  useEffect(() => {
    if (reduced || closing) return;
    const dwell = step === 0 ? LOGO_DWELL_MS : SCENE_DWELL_MS;
    const t = window.setTimeout(
      () => setStep((s) => (s === 0 || s >= STORE_SCENES.length ? 1 : s + 1)),
      dwell,
    );
    return () => window.clearTimeout(t);
  }, [step, reduced, closing]);

  useEffect(() => {
    if (reduced) return;
    const upcoming = STORE_SCENES[step];
    if (upcoming) preloadImage(upcoming.src);
  }, [step, reduced]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    ctaRef.current?.focus();
  }, []);

  useEffect(
    () => () => {
      timers.current.forEach((t) => window.clearTimeout(t));
    },
    [],
  );

  const finish = useCallback(
    (location?: GeoLocation) => {
      if (closingRef.current) return;
      closingRef.current = true;
      setClosing(true);

      const rect = isDesktop ? screenRef.current?.getBoundingClientRect() : null;
      if (rect && rect.width > 0) {
        setMorph(rect);
        timers.current.push(window.setTimeout(() => setMorphFull(true), 20));
        timers.current.push(window.setTimeout(() => setFaded(true), 620));
        timers.current.push(
          window.setTimeout(() => onDone(location), CLOSE_DURATION_MS),
        );
      } else {
        timers.current.push(window.setTimeout(() => onDone(location), 300));
      }
    },
    [isDesktop, onDone],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finish]);

  const activeScene = step >= 1 && step <= 3 ? STORE_SCENES[step - 1] : null;

  if (reduced) {
    return (
      <StaticIntro ctaRef={ctaRef} closing={closing} onStart={finish} />
    );
  }

  return (
    <div
      className={cn(
        "intro",
        closing && "is-closing",
        faded && "is-faded",
      )}
      role="dialog"
      aria-modal="true"
      aria-label="RIMs introduction"
    >
      <div className="intro-stage" aria-hidden>
        <div
          className={cn(
            "intro-scene intro-scene--logo",
            step === 0 && "is-active",
            step > 0 && "is-past",
          )}
        >
          <div className="intro-plate intro-plate--logo" />
        </div>

        {STORE_SCENES.map((scene, i) => {
          const index = i + 1;
          const mounted = step >= index - 1;
          const isActive = step === index;
          const isPast = step > index;
          return (
            <div
              key={scene.key}
              className={cn(
                "intro-scene",
                isActive && "is-active",
                isPast && "is-past",
              )}
            >
              <div className={cn("intro-plate", `intro-plate--${scene.key}`)} />
              {mounted && !failed[scene.key] && (
                <img
                  className="intro-scene__img"
                  src={scene.src}
                  alt=""
                  decoding="async"
                  onError={() =>
                    setFailed((f) => ({ ...f, [scene.key]: true }))
                  }
                />
              )}
              <div className="intro-scene__veil" />
            </div>
          );
        })}
      </div>

      <div className="intro-chrome intro-topbar">
        <div className={cn("intro-toplogo", step > 0 && "is-shown")}>
          <IntroLogo className="h-6 w-auto" />
        </div>
        <button
          type="button"
          className="intro-skip"
          onClick={() => finish()}
        >
          Skip intro
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>

      <div className="intro-content">
        {step === 0 && (
          <div className="intro-lockup">
            <IntroLogo className="intro-lockup__logo h-16 w-auto sm:h-24" />
            <p className="intro-lockup__sub">Supplies &amp; Hardware</p>
          </div>
        )}

        {activeScene && (
          <div key={activeScene.key} className="intro-caption">
            <p className="intro-caption__eyebrow">{activeScene.eyebrow}</p>
            <p className="intro-caption__title">{activeScene.caption}</p>
          </div>
        )}

        {step === 4 && (
          <div className="intro-ready">
            <div className="intro-ready__head">
              <IntroLogo className="h-10 w-auto sm:h-12" />
              <h1 className="intro-ready__brand">RIMs Supplies &amp; Hardware</h1>
              <p className="intro-ready__tag">Your destination. Our delivery.</p>
            </div>
            {isDesktop && (
              <div className="intro-ready__device">
                <LaptopScreen onStart={finish} screenRef={screenRef} />
              </div>
            )}
          </div>
        )}
      </div>

      <div className="intro-cta">
        <button
          ref={ctaRef}
          type="button"
          className="intro-cta__button"
          onClick={() => finish()}
        >
          Start your delivery
          <ArrowRight className="h-4 w-4" aria-hidden />
        </button>
        <span className="intro-cta__hint">
          {step < 4 ? "Skip straight to the calculator" : "Enter your delivery location"}
        </span>
      </div>

      {morph && (
        <div
          className={cn("intro-morph", morphFull && "is-full")}
          style={{
            top: morph.top,
            left: morph.left,
            width: morph.width,
            height: morph.height,
          }}
          aria-hidden
        />
      )}
    </div>
  );
}

function StaticIntro({
  onStart,
  ctaRef,
  closing,
}: {
  onStart: (location?: GeoLocation) => void;
  ctaRef: RefObject<HTMLButtonElement | null>;
  closing: boolean;
}) {
  useEffect(() => {
    ctaRef.current?.focus();
  }, [ctaRef]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onStart();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onStart]);

  return (
    <div
      className={cn("intro intro--static", closing && "is-closing")}
      role="dialog"
      aria-modal="true"
      aria-label="RIMs introduction"
    >
      <div className="intro-stage" aria-hidden>
        <div className="intro-scene is-active">
          <div className="intro-plate intro-plate--day" />
          <img
            className="intro-scene__img"
            src={STORE_SCENES[0].src}
            alt=""
            decoding="async"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
          <div className="intro-scene__veil" />
        </div>
      </div>
      <div className="intro-content">
        <div className="intro-lockup">
          <IntroLogo className="intro-lockup__logo h-16 w-auto sm:h-24" />
          <p className="intro-lockup__sub">Supplies &amp; Hardware</p>
          <h1 className="intro-ready__brand mt-6">
            RIMs Supplies &amp; Hardware
          </h1>
          <p className="intro-ready__tag">Your destination. Our delivery.</p>
        </div>
      </div>
      <div className="intro-cta">
        <button
          ref={ctaRef}
          type="button"
          className="intro-cta__button"
          onClick={() => onStart()}
        >
          Start your delivery
          <ArrowRight className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <button
        type="button"
        className="intro-skip intro-skip--floating"
        onClick={() => onStart()}
      >
        Skip
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
