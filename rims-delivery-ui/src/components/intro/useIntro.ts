import { useEffect, useState } from "react";

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
