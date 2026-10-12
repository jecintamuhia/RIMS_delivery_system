export interface LatLng {
  lat: number;
  lng: number;
}

export type ErrorCode =
  | "INVALID_LOCATION"
  | "LOCATION_NOT_FOUND"
  | "AMBIGUOUS_LOCATION"
  | "ROUTING_UNAVAILABLE"
  | "DESTINATION_UNSUPPORTED"
  | "NO_PRICING_RULE"
  | "ROAD_TYPE_REQUIRED"
  | "VEHICLE_REQUIRED"
  | "MANUAL_REVIEW"
  | "NETWORK"
  | "SERVER"
  | "SESSION_EXPIRED"
  | "INVALID_CREDENTIALS"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "VALIDATION"
  | "UNKNOWN";

export interface PublicConfig {
  company: {
    name: string;
    logoUrl?: string;
    contactPhone?: string;
    contactEmail?: string;
  };
  dispatch: { name: string } & LatLng;
  map: { center: LatLng; zoom: number; tileUrl?: string; attribution?: string };
}

export interface GeoLocation {
  id: string;
  label: string;
  secondary?: string;
  position: LatLng;
}

export interface Money {
  amount: number;
  currency: "KES";
}

/** How the fee was produced. `fixed_destination` is RIMs' official price for a
 *  destination; `distance_based` is road distance x the configured rate. */
export type PricingModel = "fixed_destination" | "distance_based";

/** Road distance and travel time from the dispatch point, before a quote exists. */
export interface RoutePreview {
  distanceKm: number;
  durationMinutes: number;
  route?: { summary?: string | null; geometry?: LatLng[] } | null;
}

export type QuoteStatus =
  "processing" | "completed" | "accepted" | "needs_review" | "failed";
export type StepKey =
  "location" | "route" | "destination" | "pricing" | "estimate";
export type StepState = "pending" | "running" | "completed" | "failed";
export interface QuoteStep {
  key: StepKey;
  state: StepState;
}

export interface QuoteFailure {
  code: ErrorCode;
  message?: string;
  candidates?: GeoLocation[];
}

/** Customer-facing quote. Contains no internal pricing breakdown. */
export interface Quote {
  id: string;
  reference?: string | null;
  status: QuoteStatus;
  steps: QuoteStep[];
  createdAt: string;
  location: { label: string; position: LatLng };
  dispatch?: { name: string } & LatLng;
  destination?: { id: string; name: string } | null;
  distanceKm?: number | null;
  durationMinutes?: number | null;
  route?: { summary?: string | null; geometry?: LatLng[] } | null;
  roadType?: { id: string; name: string } | null;
  vehicle?: { id: string; name: string } | null;
  fee?: Money | null;
  /** Present whenever a fee is. The customer should always be able to see which
   *  model priced the quote. */
  pricingModel?: PricingModel | null;
  /** One sentence the customer can check the amount against. */
  pricingExplanation?: string | null;
  failure?: QuoteFailure | null;
}

export interface CreateQuoteInput {
  position: LatLng;
  label: string;
  locationId?: string;
  reference?: string;
}

export interface QuoteAdjustment {
  label: string;
  amount: Money;
}
export interface AdminQuote extends Quote {
  breakdown?: {
    basePrice: Money;
    adjustments: QuoteAdjustment[];
    ruleId?: string | null;
    ruleLabel?: string | null;
    pricingVersion?: string | null;
    pricingModel?: PricingModel | null;
    /** Audit record for a distance-based amount: distance, rates, fuel, total. */
    pricingDetails?: Record<string, string | null> | null;
    notes?: string[];
  } | null;
  calculations?: {
    id: string;
    createdAt: string;
    basePrice: Money;
    total: Money;
    ruleLabel?: string | null;
    pricingVersion?: string | null;
    pricingModel?: PricingModel | null;
    pricingDetails?: Record<string, string | null> | null;
    notes?: string[];
  }[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface Destination {
  id: string;
  name: string;
  code: string;
  zone: string;
  county?: string | null;
  position?: LatLng | null;
  active: boolean;
  currentBasePrice?: Money | null;
  aliases?: string[];
  aliasesCount?: number;
  hasBoundary?: boolean;
  catchmentRadiusKm?: number | null;
}
export interface RoadType {
  id: string;
  name: string;
  code: string;
  description?: string | null;
  active: boolean;
}
export interface VehicleCategory {
  id: string;
  name: string;
  code: string;
  maxWeightKg?: number | null;
  maxVolumeM3?: number | null;
  active: boolean;
}

export type AdjustmentType = "none" | "fixed" | "percent";
export interface PricingRule {
  id: string;
  destinationId: string;
  destinationName?: string;
  roadTypeId?: string | null;
  roadTypeName?: string | null;
  vehicleId?: string | null;
  vehicleName?: string | null;
  basePrice: number;
  adjustmentType: AdjustmentType;
  adjustmentValue?: number | null;
  effectiveFrom: string;
  effectiveTo?: string | null;
  priority: number;
  active: boolean;
}

export type PricingVersionStatus = "draft" | "active" | "retired";
export interface PricingVersion {
  id: string;
  label: string;
  status: PricingVersionStatus;
  effectiveFrom: string;
  effectiveTo?: string | null;
  currency: string;
  notes?: string | null;
  source?: string | null;
  ruleCount: number;
  destinationCount: number;
  createdAt: string;
  activatedAt?: string | null;
  validatedAt?: string | null;
  validatedBy?: string | null;
  validationNote?: string | null;
}

/** A configured distance rate (pricing model B). Exactly one is active at a time,
 *  an active one is immutable, and only an admin may activate or retire one. */
export interface DynamicPricingVersion {
  id: string;
  label: string;
  status: PricingVersionStatus;
  baseRatePerKm: number;
  fuelAdjustmentPercent: number;
  minCharge?: number | null;
  currency: string;
  effectiveRatePerKm: number;
  effectiveFrom?: string | null;
  notes?: string | null;
  createdAt: string;
  activatedAt?: string | null;
  retiredAt?: string | null;
}

export interface DynamicPricingInput {
  label: string;
  baseRatePerKm: string;
  fuelAdjustmentPercent?: string;
  minCharge?: string | null;
  currency?: string;
  notes?: string | null;
}

export interface DynamicPricingActivation {
  versionId: string;
  label: string;
  activatedAt: string;
  retiredVersionId?: string | null;
  retiredLabel?: string | null;
}

export interface DynamicPricingPreviewResult {
  priced: boolean;
  reason?: string | null;
  message?: string | null;
  distanceKm?: number | null;
  currency: string;
  configId?: string | null;
  configLabel?: string | null;
  baseRatePerKm?: number | null;
  fuelAdjustmentPercent?: number | null;
  effectiveRatePerKm?: number | null;
  total?: number | null;
  adjustments?: { label: string; amount: number; kind: string; detail?: string | null }[];
  notes?: string[];
}

export interface ValidationFinding {
  code: string;
  severity: "error" | "warning";
  message: string;
  destinationName?: string | null;
  ruleId?: string | null;
}

export interface VersionValidationResult {
  versionId: string;
  label: string;
  status: string;
  valid: boolean;
  ruleCount: number;
  destinationCount: number;
  findings: ValidationFinding[];
  summary: string;
}

export interface ActivationResult {
  versionId: string;
  label: string;
  activatedAt: string;
  retiredVersionId?: string | null;
  retiredLabel?: string | null;
  ruleCount: number;
}

export interface PricingImportReport {
  versionId?: string | null;
  label: string;
  ruleCount: number;
  destinationCount: number;
  dryRun: boolean;
  createdDestinations: string[];
  problems: string[];
}

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
  action: string;
  entityType: string;
  entityId?: string | null;
  summary: string;
}

export interface DashboardSummary {
  quotesToday: number;
  quotesThisWeek: number;
  totalQuotedValue: Money;
  averageDistanceKm: number | null;
  topDestinations: { name: string; count: number }[];
  needsReview: {
    id: string;
    locationLabel: string;
    reason?: string;
    createdAt: string;
  }[];
}

export interface AppSettings {
  dispatch: { name: string } & LatLng;
  contactPhone?: string | null;
  contactEmail?: string | null;
  activePricingVersion?: string | null;
  mapProvider?: string | null;
}

export type Role = "admin" | "editor" | "viewer";
export interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: Role;
}

export interface StaffUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  active: boolean;
  lastLoginAt?: string | null;
  createdAt?: string | null;
}
