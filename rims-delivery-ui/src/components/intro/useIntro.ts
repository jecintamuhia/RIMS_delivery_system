import { useCallback, useEffect, useState } from "react";
import { useIdle } from "@/utils/useIdle";

const SEEN_KEY = "rims.intro.seen";

export function hasSeenIntro(): boolean {
  try {
    return window.sessionStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

export function markIntroSeen(): void {
  try {
    window.sessionStorage.setItem(SEEN_KEY, "1");
  } catch {
  }
}


export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
  );
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

export function useIntro(): { show: boolean; dismiss: () => void } {
  const [show, setShow] = useState(
    () => typeof window !== "undefined" && !hasSeenIntro(),
  );
  return {
    show,
    dismiss: () => {
      markIntroSeen();
      setShow(false);
    },
  };
}

/** Inactivity before the splash replays as an attract screen. */
export const IDLE_SPLASH_MS = 4 * 60 * 1000;

/**
 * Replays the splash screens after the user has been inactive. Pass
 * `enabled = false` to pause the countdown (e.g. while the first-visit opening
 * is already on screen).
 */
export function useIdleSplash(enabled = true): {
  visible: boolean;
  dismiss: () => void;
} {
  const [visible, setVisible] = useState(false);
  useIdle(IDLE_SPLASH_MS, () => setVisible(true), enabled && !visible);
  const dismiss = useCallback(() => setVisible(false), []);
  return { visible, dismiss };
}
