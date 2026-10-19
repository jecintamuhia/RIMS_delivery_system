import { useEffect, useRef } from "react";

const ACTIVITY_EVENTS = [
  "pointerdown",
  "pointermove",
  "keydown",
  "wheel",
  "touchstart",
  "scroll",
] as const;

/**
 * Fires `onIdle` once the user has been inactive for `timeoutMs`. Any pointer,
 * key, wheel, touch or scroll activity restarts the countdown. Pass
 * `enabled = false` to pause the countdown (e.g. while an overlay is open).
 */
export function useIdle(
  timeoutMs: number,
  onIdle: () => void,
  enabled = true,
): void {
  const onIdleRef = useRef(onIdle);
  onIdleRef.current = onIdle;

  useEffect(() => {
    if (!enabled) return;
    let timer = window.setTimeout(() => onIdleRef.current(), timeoutMs);
    const restart = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => onIdleRef.current(), timeoutMs);
    };
    const options: AddEventListenerOptions = { passive: true, capture: true };
    ACTIVITY_EVENTS.forEach((event) =>
      window.addEventListener(event, restart, options),
    );
    return () => {
      window.clearTimeout(timer);
      ACTIVITY_EVENTS.forEach((event) =>
        window.removeEventListener(event, restart, options),
      );
    };
  }, [timeoutMs, enabled]);
}
