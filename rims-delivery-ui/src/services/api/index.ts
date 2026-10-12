import { api } from "./client";
import { createCrudApi } from "./crud";
import type {
  AdminQuote,
  AdminUser,
  AppSettings,
  AuditEntry,
  CreateQuoteInput,
  DashboardSummary,
  Destination,
  DynamicPricingActivation,
  DynamicPricingInput,
  DynamicPricingPreviewResult,
  DynamicPricingVersion,
  GeoLocation,
  LatLng,
  Page,
  PricingRule,
  PublicConfig,
  Quote,
  RoutePreview,
  PricingVersion,
  VersionValidationResult,
  ActivationResult,
  PricingImportReport,
  StaffUser,
  RoadType,
  VehicleCategory,
} from "@/types";

export { ApiError, onSessionExpired } from "./client";

/** Public, customer-facing endpoints. */
export const deliveryApi = {
  config: () => api.get<PublicConfig>("/public/config"),
  searchLocations: (q: string, signal?: AbortSignal) =>
    api.get<GeoLocation[]>("/public/locations/search", { q }, signal),
  reverseGeocode: (p: LatLng) =>
    api.get<GeoLocation>("/public/locations/reverse", {
      lat: p.lat,
      lng: p.lng,
    }),
  /** Distance and travel time from the dispatch point. Carries no price:
   *  pricing happens once, in the quote pipeline. */
  routePreview: (p: LatLng, signal?: AbortSignal) =>
    api.get<RoutePreview>("/public/route", { lat: p.lat, lng: p.lng }, signal),
};

/** Quote lifecycle. The backend pricing engine is the only source of fees. */
export const quotesApi = {
  create: (input: CreateQuoteInput) => api.post<Quote>("/public/quotes", input),
  get: (id: string) => api.get<Quote>(`/public/quotes/${id}`),
  recalculate: (id: string) =>
    api.post<Quote>(`/public/quotes/${id}/recalculate`),
  accept: (id: string) => api.post<Quote>(`/public/quotes/${id}/accept`),
};

export interface QuoteListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  status?: string;
  destinationId?: string;
  from?: string;
  to?: string;
}
export const adminQuotesApi = {
  list: (p: QuoteListParams) =>
    api.get<Page<Quote & { destinationName?: string }>>(
      "/admin/quotes",
      p as Record<string, string | number>,
    ),
  get: (id: string) => api.get<AdminQuote>(`/admin/quotes/${id}`),
};

export type DestinationInput = Omit<Destination, "id" | "currentBasePrice">;
export type RoadTypeInput = Omit<RoadType, "id">;
export type VehicleInput = Omit<VehicleCategory, "id">;
export type PricingRuleInput = Omit<
  PricingRule,
  "id" | "destinationName" | "roadTypeName" | "vehicleName"
>;

export const destinationsApi = {
  ...createCrudApi<Destination, DestinationInput>("/admin/destinations"),
  addAlias: (destinationId: string, alias: string) =>
    api.post<Destination>(`/admin/destinations/${destinationId}/aliases`, { alias }),
  removeAlias: (destinationId: string, aliasId: string) =>
    api.delete<void>(`/admin/destinations/${destinationId}/aliases/${aliasId}`),
};
export const pricingApi = createCrudApi<PricingRule, PricingRuleInput>(
  "/admin/pricing-rules",
);
export const roadsApi = createCrudApi<RoadType, RoadTypeInput>(
  "/admin/road-types",
);
export const vehiclesApi = createCrudApi<VehicleCategory, VehicleInput>(
  "/admin/vehicles",
);

export const pricingVersionsApi = {
  files: () => api.get<string[]>("/admin/pricing-import/files"),
  list: () => api.get<PricingVersion[]>("/admin/pricing-versions"),
  create: (b: {
    label: string;
    effectiveFrom: string;
    effectiveTo?: string | null;
    currency?: string;
    notes?: string | null;
    activate?: boolean;
  }) => api.post<PricingVersion>("/admin/pricing-versions", b),
  validate: (id: string) =>
    api.post<VersionValidationResult>(`/admin/pricing-versions/${id}/validate`),
  confirmValidation: (id: string, note?: string) =>
    api.post<PricingVersion>(`/admin/pricing-versions/${id}/confirm-validation`, { note }),
  activate: (id: string) =>
    api.post<ActivationResult>(`/admin/pricing-versions/${id}/activate`),
  retire: (id: string) =>
    api.post<PricingVersion>(`/admin/pricing-versions/${id}/retire`),
  importCsv: (input: { filename: string; label: string; effectiveFrom: string; dryRun: boolean }) =>
    api.post<PricingImportReport>("/admin/pricing-import", input),
};

/** Distance-based pricing (model B). Activating and retiring are admin-only. */
export const dynamicPricingApi = {
  list: () => api.get<DynamicPricingVersion[]>("/admin/dynamic-pricing"),
  active: () => api.get<DynamicPricingVersion | null>("/admin/dynamic-pricing/active"),
  create: (b: DynamicPricingInput) =>
    api.post<DynamicPricingVersion>("/admin/dynamic-pricing", b),
  update: (id: string, b: Partial<DynamicPricingInput>) =>
    api.patch<DynamicPricingVersion>(`/admin/dynamic-pricing/${id}`, b),
  activate: (id: string) =>
    api.post<DynamicPricingActivation>(`/admin/dynamic-pricing/${id}/activate`),
  retire: (id: string) =>
    api.post<DynamicPricingVersion>(`/admin/dynamic-pricing/${id}/retire`),
  preview: (b: {
    distanceKm: string;
    versionId?: string;
    baseRatePerKm?: string;
    fuelAdjustmentPercent?: string;
    minCharge?: string;
  }) => api.post<DynamicPricingPreviewResult>("/admin/dynamic-pricing/preview", b),
};

export const usersApi = {
  list: (p?: { page?: number; pageSize?: number; search?: string; role?: string }) =>
    api.get<Page<StaffUser>>("/admin/users", p as Record<string, string | number>),
  create: (b: { fullName: string; email: string; password: string; role: string; active?: boolean }) =>
    api.post<StaffUser>("/admin/users", b),
  update: (
    id: string,
    b: { fullName?: string; password?: string; role?: string; active?: boolean },
  ) => api.patch<StaffUser>(`/admin/users/${id}`, b),
};

export const dashboardApi = {
  summary: () => api.get<DashboardSummary>("/admin/dashboard"),
};
export const auditApi = {
  list: (p: {
    page?: number;
    pageSize?: number;
    entityType?: string;
    search?: string;
  }) =>
    api.get<Page<AuditEntry>>(
      "/admin/audit-log",
      p as Record<string, string | number>,
    ),
};
export const settingsApi = {
  get: () => api.get<AppSettings>("/admin/settings"),
  update: (b: Partial<AppSettings>) =>
    api.patch<AppSettings>("/admin/settings", b),
};
export const authApi = {
  login: (email: string, password: string) =>
    api.post<AdminUser>(
      "/auth/login",
      { email, password },
      { skipSessionHandler: true },
    ),
  logout: () => api.post<void>("/auth/logout"),
  me: () =>
    api.post<AdminUser>("/auth/me", undefined, { skipSessionHandler: true }),
};
