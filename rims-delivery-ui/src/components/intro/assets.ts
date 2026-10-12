

export const LOGO_CANDIDATES = [
  "/brand/rims-logo.svg",
  "/brand/rims-logo.png",
] as const;

export interface IntroScene {
  key: "day" | "night" | "interior";
  src: string;
  size: string;
  alt: string;
  eyebrow: string;
  caption: string;
}

export const STORE_SCENES: IntroScene[] = [
  {
    key: "day",
    src: "/brand/store-day.jpg",
    size: "2560×1440",
    alt: "RIMs Supplies and Hardware storefront on Kenyatta Avenue, Naivasha, in daylight",
    eyebrow: "Kenyatta Avenue, Naivasha",
    caption: "Supplies and hardware, on the shelves and on the road.",
  },
  {
    key: "night",
    src: "/brand/store-night.jpg",
    size: "2560×1440",
    alt: "The RIMs Supplies and Hardware storefront lit at night",
    eyebrow: "Open for the workday ahead",
    caption: "From first light to last load.",
  },
  {
    key: "interior",
    src: "/brand/store-interior.jpg",
    size: "2560×1440",
    alt: "Inside the RIMs Supplies and Hardware shop, showing stocked shelving",
    eyebrow: "Everything your build needs",
    caption: "Stocked deep, moving fast.",
  },
];

export const SCENE_DWELL_MS = 2400;
export const LOGO_DWELL_MS = 2000;
export const CLOSE_DURATION_MS = 1050;

export const SCENE_STEPS = ["logo", "day", "night", "interior", "ready"] as const;
export type IntroStep = (typeof SCENE_STEPS)[number];


export function preloadImage(src: string): void {
  if (typeof window === "undefined") return;
  const img = new Image();
  img.decoding = "async";
  img.src = src;
}
