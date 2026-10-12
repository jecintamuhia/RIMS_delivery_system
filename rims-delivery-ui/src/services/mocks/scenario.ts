export type Scenario =
  | "ok"
  | "no-rule"
  | "unsupported"
  | "manual-review"
  | "routing-down"
  | "ambiguous"
  | "invalid"
  | "server"
  | "network"
  | "slow";
export const scenarios: { value: Scenario; label: string }[] = [
  { value: "ok", label: "Priced successfully" },
  { value: "slow", label: "Slow calculation" },
  { value: "no-rule", label: "No pricing rule" },
  { value: "unsupported", label: "Destination unsupported" },
  { value: "manual-review", label: "Manual review" },
  { value: "routing-down", label: "Routing unavailable" },
  { value: "ambiguous", label: "Ambiguous location" },
  { value: "invalid", label: "Invalid location" },
  { value: "server", label: "Server error" },
  { value: "network", label: "Network failure" },
];
const KEY = "rims.mock.scenario";
export const getScenario = (): Scenario =>
  (localStorage.getItem(KEY) as Scenario) || "ok";
export const setScenario = (s: Scenario) => localStorage.setItem(KEY, s);
