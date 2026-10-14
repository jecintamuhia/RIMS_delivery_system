import {
  AlertTriangle,
  MapPinOff,
  SearchX,
  WifiOff,
  ServerCrash,
  Hammer,
  type LucideIcon,
} from "lucide-react";
import type { ErrorCode } from "@/types";

export interface ErrorCopy {
  title: string;
  body: string;
  icon: LucideIcon;
  tone: "danger" | "warn";
  /** What the customer can do next. */
  next: "change-location" | "retry" | "contact";
}

/** Every failure says what happened and what to do next. Codes are produced by the backend. */
export const errorCopy: Partial<Record<ErrorCode, ErrorCopy>> & {
  default: ErrorCopy;
} = {
  INVALID_LOCATION: {
    title: "That location can’t be used",
    body: "The pin is outside the area we can deliver to, or isn’t a valid point on land. Pick a spot in Kenya on the map.",
    icon: MapPinOff,
    tone: "danger",
    next: "change-location",
  },
  LOCATION_NOT_FOUND: {
    title: "We couldn’t find that location",
    body: "Check the spelling, try a nearby town or landmark, or drop a pin on the map.",
    icon: SearchX,
    tone: "danger",
    next: "change-location",
  },
  AMBIGUOUS_LOCATION: {
    title: "More than one place matches",
    body: "Choose the correct place below, or pin the exact spot on the map.",
    icon: SearchX,
    tone: "warn",
    next: "change-location",
  },
  ROUTING_UNAVAILABLE: {
    title: "This delivery needs a manual quotation",
    body: "We couldn’t confirm the road distance for this route, so we can’t price it automatically. Nothing has been charged or saved — please contact RIMs and we’ll price it for you.",
    icon: Hammer,
    tone: "warn",
    next: "contact",
  },
  DESTINATION_UNSUPPORTED: {
    title: "We don’t have a delivery area for this location yet",
    body: "RIMs hasn’t set a delivery price for this area. Contact RIMs for a quotation.",
    icon: MapPinOff,
    tone: "warn",
    next: "contact",
  },
  NO_PRICING_RULE: {
    title: "We couldn’t determine a delivery price for this location",
    body: "Please contact RIMs for a quotation.",
    icon: AlertTriangle,
    tone: "warn",
    next: "contact",
  },
  ROAD_TYPE_REQUIRED: {
    title: "This delivery needs a manual quotation",
    body: "The price for this area depends on road conditions that we couldn’t confirm. Please contact RIMs for a quotation.",
    icon: Hammer,
    tone: "warn",
    next: "contact",
  },
  VEHICLE_REQUIRED: {
    title: "This delivery needs a manual quotation",
    body: "The price depends on the vehicle needed for your order, which we couldn’t confirm. Please contact RIMs for a quotation.",
    icon: Hammer,
    tone: "warn",
    next: "contact",
  },
  MANUAL_REVIEW: {
    title: "This delivery needs a manual quotation",
    body: "We couldn’t price this location automatically. Please contact RIMs for a quotation.",
    icon: Hammer,
    tone: "warn",
    next: "contact",
  },
  NETWORK: {
    title: "You appear to be offline",
    body: "We couldn’t reach the server. Check your connection and try again.",
    icon: WifiOff,
    tone: "danger",
    next: "retry",
  },
  SERVER: {
    title: "Something went wrong on our side",
    body: "The request didn’t complete and no price was produced. Try again, or contact RIMs if it keeps happening.",
    icon: ServerCrash,
    tone: "danger",
    next: "retry",
  },
  NOT_FOUND: {
    title: "We couldn’t find that quote",
    body: "The link may be wrong or the quote may have expired. Start a new estimate.",
    icon: SearchX,
    tone: "danger",
    next: "change-location",
  },
  default: {
    title: "We couldn’t complete your estimate",
    body: "No price was produced. Try again, or contact RIMs for a quotation.",
    icon: AlertTriangle,
    tone: "danger",
    next: "retry",
  },
};
export const copyFor = (code?: ErrorCode) =>
  (code && errorCopy[code]) || errorCopy.default;
