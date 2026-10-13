/**
 * Brand-film assets.
 *
 * The cinematic intro is built around six genuine RIMs photographs and the
 * official logo shipped into `public/brand/`. Filenames are mirrored in the
 * `public/brand/README.md` spec: drop files there and rebuild for a production
 * deployment. Missing files degrade to branded plates, never to a broken image
 * or a blocked calculator.
 */

export const LOGO_CANDIDATES = [
  "/brand/rims-logo.svg",
  "/brand/rims-logo.png",
] as const;

export interface IntroScene {
  key: string;
  src: string;
  alt: string;
  eyebrow: string;
  caption: string;
}

export const STORE_SCENES: IntroScene[] = [
  {
    key: "p1",
    src: "/brand/rims-1.jpg",
    alt: "RIMs Supplies and Hardware",
    eyebrow: "RIMs Supplies & Hardware",
    caption: "Everything your build needs, delivered.",
  },
  {
    key: "p2",
    src: "/brand/rims-2.jpg",
    alt: "RIMs Supplies and Hardware",
    eyebrow: "Kenyatta Avenue, Naivasha",
    caption: "Stocked deep. Moving fast.",
  },
  {
    key: "p3",
    src: "/brand/rims-3.jpg",
    alt: "RIMs Supplies and Hardware",
    eyebrow: "RIMs Supplies & Hardware",
    caption: "From our shelves to your site.",
  },
  {
    key: "p4",
    src: "/brand/rims-4.jpg",
    alt: "RIMs Supplies and Hardware",
    eyebrow: "RIMs Supplies & Hardware",
    caption: "The hardware you need, where you need it.",
  },
  {
    key: "p5",
    src: "/brand/rims-5.jpg",
    alt: "RIMs Supplies and Hardware",
    eyebrow: "Priced before you order",
    caption: "Real prices, on real roads.",
  },
  {
    key: "p6",
    src: "/brand/rims-6.jpg",
    alt: "RIMs Supplies and Hardware",
    eyebrow: "RIMs Supplies & Hardware",
    caption: "Your destination. Our delivery.",
  },
];

/** Dwell time each photograph holds before the next cross-dissolve. */
export const SCENE_DWELL_MS = 1900;
/** The black opening that carries the logo reveal. */
export const LOGO_DWELL_MS = 1800;
/** How long the closing morph runs before the calculator is handed control. */
export const CLOSE_DURATION_MS = 1050;

/**
 * Kick the browser into fetching a scene image early without rendering it.
 * Failures are ignored: a missing photograph is expected until supplied.
 */
export function preloadImage(src: string): void {
  if (typeof window === "undefined") return;
  const img = new Image();
  img.decoding = "async";
  img.src = src;
}