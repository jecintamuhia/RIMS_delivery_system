/**
 * DEVELOPMENT ONLY. Enabled with VITE_USE_MOCKS=true.
 * Simulates the FastAPI contract in memory so every UI state can be exercised without a backend.
 * Every name and amount here is a placeholder fixture. None of it is RIMs data or RIMs pricing.
 */
import { ApiError, type RequestOptions } from "@/services/api/client";
import { getScenario, type Scenario } from "./scenario";
import type {
  AdminQuote,
  AdminUser,
  AppSettings,
  AuditEntry,
  Destination,
  DynamicPricingVersion,
  GeoLocation,
  LatLng,
  PricingRule,
  Quote,
  QuoteStep,
  RoadType,
  StepKey,
  VehicleCategory,
} from "@/types";

const DISPATCH = { name: "Sample dispatch point", lat: -0.3031, lng: 36.08 };
let settings: AppSettings = {
  dispatch: DISPATCH,
  contactPhone: "+254 700 000 000",
  contactEmail: "delivery@example.com",
  activePricingVersion: "mock-v1",
  mapProvider: "Leaflet + OpenStreetMap (dev)",
};

let destinations: Destination[] = [
  {
    id: "d1",
    name: "Sample area 1",
    code: "S1",
    zone: "Zone A",
    county: "Sample county",
    position: { lat: -0.2925, lng: 36.0705 },
    active: true,
  },
  {
    id: "d2",
    name: "Sample area 2",
    code: "S2",
    zone: "Zone B",
    county: "Sample county",
    position: { lat: -0.4, lng: 36.15 },
    active: true,
  },
  {
    id: "d3",
    name: "Sample area 3",
    code: "S3",
    zone: "Zone C",
    county: "Sample county",
    position: { lat: -0.17, lng: 35.95 },
    active: true,
  },
];
let roadTypes: RoadType[] = [];
let vehicles: VehicleCategory[] = [];
let rules: PricingRule[] = [
  {
    id: "r1",
    destinationId: "d1",
    basePrice: 1111,
    adjustmentType: "none",
    effectiveFrom: "2026-01-01",
    priority: 0,
    active: true,
  },
  {
    id: "r2",
    destinationId: "d2",
    basePrice: 2222,
    adjustmentType: "none",
    effectiveFrom: "2026-01-01",
    priority: 0,
    active: true,
  },
  {
    id: "r3",
    destinationId: "d3",
    basePrice: 3333,
    adjustmentType: "none",
    effectiveFrom: "2026-01-01",
    priority: 0,
    active: true,
  },
];
const audit: AuditEntry[] = [];
let loggedIn = false;
const user: AdminUser = {
  id: "u1",
  name: "Mock Admin",
  email: "admin@example.com",
  role: "admin",
};

const places: GeoLocation[] = [
  {
    id: "p1",
    label: "Sample area 1",
    secondary: "Placeholder place · mock data",
    position: { lat: -0.2925, lng: 36.0705 },
  },
  {
    id: "p2",
    label: "Sample area 2",
    secondary: "Placeholder place · mock data",
    position: { lat: -0.4, lng: 36.15 },
  },
  {
    id: "p3",
    label: "Sample area 3",
    secondary: "Placeholder place · mock data",
    position: { lat: -0.17, lng: 35.95 },
  },
];

interface Rec {
  id: string;
  at: number;
  startedAt: number;
  scenario: Scenario;
  label: string;
  position: LatLng;
  locationId?: string;
  reference?: string;
  accepted: boolean;
}
const quotes = new Map<string, Rec>();
let seq = 1000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const rad = (d: number) => (d * Math.PI) / 180;
const km = (a: LatLng, b: LatLng) => {
  const dLat = rad(b.lat - a.lat),
    dLng = rad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
};
const log = (
  action: string,
  entityType: string,
  summary: string,
  entityId?: string,
) =>
  audit.unshift({
    id: `a${audit.length + 1}`,
    at: new Date().toISOString(),
    actor: user.name,
    action,
    entityType,
    entityId,
    summary,
  });

const ORDER: StepKey[] = [
  "location",
  "route",
  "destination",
  "pricing",
  "estimate",
];
const FAIL_AT: Partial<Record<Scenario, [StepKey, Quote["failure"]]>> = {
  "routing-down": ["route", { code: "ROUTING_UNAVAILABLE" }],
  unsupported: ["destination", { code: "DESTINATION_UNSUPPORTED" }],
  "no-rule": ["pricing", { code: "NO_PRICING_RULE" }],
  "manual-review": ["pricing", { code: "MANUAL_REVIEW" }],
};

function build(r: Rec): AdminQuote {
  const per = r.scenario === "slow" ? 4000 : 700;
  const elapsed = Date.now() - r.startedAt;
  const idx = Math.floor(elapsed / per);
  const fail = FAIL_AT[r.scenario];
  const failIdx = fail ? ORDER.indexOf(fail[0]) : -1;
  const base = {
    id: `Q-${r.id}`,
    reference: r.reference,
    createdAt: new Date(r.at).toISOString(),
    location: { label: r.label, position: r.position },
    dispatch: settings.dispatch,
  };
  const steps: QuoteStep[] = ORDER.map((key, i) => ({
    key,
    state:
      failIdx === i && idx > i
        ? "failed"
        : failIdx >= 0 && i > failIdx
          ? "pending"
          : i < idx
            ? "completed"
            : i === idx
              ? "running"
              : "pending",
  }));
  if (failIdx >= 0 && idx > failIdx)
    return { ...base, steps, status: "needs_review", failure: fail![1] };
  if (idx < ORDER.length) return { ...base, steps, status: "processing" };

  const nearest = destinations
    .filter((d) => d.active && d.position)
    .sort(
      (a, b) => km(r.position, a.position!) - km(r.position, b.position!),
    )[0];
  const rule =
    nearest && rules.find((x) => x.destinationId === nearest.id && x.active);
  if (!nearest || !rule)
    return {
      ...base,
      steps: steps.map((s) => ({ ...s, state: "completed" as const })),
      status: "needs_review",
      failure: { code: "NO_PRICING_RULE" },
    };
  const distance =
    Math.round(km(settings.dispatch, r.position) * 1.3 * 10) / 10;
  const mid = {
    lat: (settings.dispatch.lat + r.position.lat) / 2 + 0.01,
    lng: (settings.dispatch.lng + r.position.lng) / 2 - 0.01,
  };
  return {
    ...base,
    steps,
    status: r.accepted ? "accepted" : "completed",
    destination: { id: nearest.id, name: nearest.name },
    distanceKm: distance,
    route: {
      summary: "Sample route (mock geometry)",
      geometry: [settings.dispatch, mid, r.position],
    },
    roadType: null,
    vehicle: null,
    fee: { amount: rule.basePrice, currency: "KES" },
    breakdown: {
      basePrice: { amount: rule.basePrice, currency: "KES" },
      adjustments: [],
      ruleId: rule.id,
      ruleLabel: `${nearest.name} · base rule`,
      pricingVersion: settings.activePricingVersion ?? "mock",
    },
  };
}
const publicView = ({ breakdown: _b, ...q }: AdminQuote): Quote => q;

const hydrateRule = (r: PricingRule): PricingRule => ({
  ...r,
  destinationName: destinations.find((d) => d.id === r.destinationId)?.name,
  roadTypeName: roadTypes.find((x) => x.id === r.roadTypeId)?.name ?? null,
  vehicleName: vehicles.find((x) => x.id === r.vehicleId)?.name ?? null,
});
const withPrice = (d: Destination): Destination => {
  const r = rules.find((x) => x.destinationId === d.id && x.active);
  return {
    ...d,
    currentBasePrice: r ? { amount: r.basePrice, currency: "KES" } : null,
  };
};
const page = <T>(items: T[], q: Record<string, unknown> = {}) => {
  const size = Number(q.pageSize) || 20,
    p = Number(q.page) || 1;
  return {
    items: items.slice((p - 1) * size, p * size),
    total: items.length,
    page: p,
    pageSize: size,
  };
};

function crud<T extends { id: string }>(
  name: string,
  entity: string,
  get: () => T[],
  set: (v: T[]) => void,
  method: string,
  id: string | undefined,
  body: any,
  query: any,
  view: (x: T) => T = (x) => x,
  filter?: (x: T, q: any) => boolean,
) {
  if (method === "GET" && !id)
    return page(
      get()
        .filter((x) => (filter ? filter(x, query) : true))
        .map(view),
      query,
    );
  if (method === "GET") {
    const x = get().find((i) => i.id === id);
    if (!x) throw new ApiError("NOT_FOUND", `${name} not found`, 404);
    return view(x);
  }
  if (method === "POST") {
    const dup = (get() as any[]).find(
      (i) =>
        i.code && body.code && i.code.toLowerCase() === body.code.toLowerCase(),
    );
    if (dup)
      throw new ApiError(
        "VALIDATION",
        `A ${name.toLowerCase()} with code “${body.code}” already exists.`,
        422,
      );
    const x = { ...body, id: `${entity[0]}${Date.now()}` } as T;
    set([...get(), x]);
    log(
      "created",
      entity,
      `Created ${name.toLowerCase()} ${body.name ?? ""}`.trim(),
      x.id,
    );
    return view(x);
  }
  if (method === "PATCH") {
    const cur = get().find((i) => i.id === id);
    if (!cur) throw new ApiError("NOT_FOUND", `${name} not found`, 404);
    const next = { ...cur, ...body };
    set(get().map((i) => (i.id === id ? next : i)));
    log(
      Object.keys(body).length === 1 && "active" in body
        ? body.active
          ? "activated"
          : "deactivated"
        : "updated",
      entity,
      `${(cur as any).name ?? name}`,
      id,
    );
    return view(next);
  }
  throw new ApiError("UNKNOWN", "Unsupported", 405);
}

/** Distance rates (pricing model B) held by the mock server. */
const effective = (base: number, fuel: number) => Number((base * (1 + fuel / 100)).toFixed(2));
let dynamicRates: DynamicPricingVersion[] = [
  {
    id: "dp-1",
    label: "Mock distance rate",
    status: "active",
    baseRatePerKm: 48,
    fuelAdjustmentPercent: 10,
    minCharge: null,
    currency: "KES",
    effectiveRatePerKm: effective(48, 10),
    effectiveFrom: null,
    notes: null,
    createdAt: new Date().toISOString(),
    activatedAt: new Date().toISOString(),
    retiredAt: null,
  },
];
let dpSeq = 1;

export async function mockRequest<T>(
  method: string,
  path: string,
  opts: RequestOptions,
): Promise<T> {
  await sleep(250 + Math.random() * 250);
  const q = (opts.query ?? {}) as Record<string, any>;
  const body = opts.body as any;
  const sc = getScenario();
  const m = (re: RegExp) => path.match(re);
  const out = (v: unknown) => v as T;
  let r: RegExpMatchArray | null;

  // ── public ──
  if (path === "/public/config")
    return out({
      company: {
        name: "RIMs Hardware & Supplies",
        logoUrl: "/brand/rims-logo.png",
        contactPhone: settings.contactPhone,
        contactEmail: settings.contactEmail,
      },
      dispatch: settings.dispatch,
      map: { center: { lat: -0.3031, lng: 36.08 }, zoom: 10 },
    });
  if (path === "/public/locations/search") {
    const s = String(q.q ?? "").toLowerCase();
    return out(
      places.filter(
        (p) => p.label.toLowerCase().includes(s) || "sample".includes(s),
      ),
    );
  }
  if (path === "/public/locations/reverse") {
    const lat = Number(q.lat),
      lng = Number(q.lng);
    if (sc === "invalid" || lat < -5 || lat > 5.5 || lng < 33.5 || lng > 42)
      throw new ApiError("INVALID_LOCATION", "Outside supported area", 422);
    return out({
      id: `pin-${lat.toFixed(4)}-${lng.toFixed(4)}`,
      label: "Pinned location",
      secondary: "Mock address near the selected point",
      position: { lat, lng },
    });
  }
  if (path === "/public/route") {
    const lat = Number(q.lat),
      lng = Number(q.lng);
    if (sc === "invalid")
      throw new ApiError("ROUTING_UNAVAILABLE", "No route found", 502);
    const km = Math.max(
      1,
      Math.hypot(lat - settings.dispatch.lat, lng - settings.dispatch.lng) * 11,
    );
    return out({
      distanceKm: Number(km.toFixed(1)),
      durationMinutes: Math.max(5, Math.round(km * 2.4)),
      route: null,
    });
  }
  if (path === "/public/quotes" && method === "POST") {
    if (sc === "network")
      throw new ApiError("NETWORK", "Could not reach the server.");
    if (sc === "server") throw new ApiError("SERVER", "Internal error", 500);
    if (sc === "ambiguous")
      throw new ApiError(
        "AMBIGUOUS_LOCATION",
        "More than one place matches",
        422,
        { candidates: places.slice(0, 2) },
      );
    const id = String(++seq);
    const rec: Rec = {
      id,
      at: Date.now(),
      startedAt: Date.now(),
      scenario: sc,
      label: body.label,
      position: body.position,
      locationId: body.locationId,
      reference: body.reference,
      accepted: false,
    };
    quotes.set(id, rec);
    return out(publicView(build(rec)));
  }
  if ((r = m(/^\/public\/quotes\/(\d+)(?:\/(recalculate|accept))?$/))) {
    const rec = quotes.get(r[1]);
    if (!rec) throw new ApiError("NOT_FOUND", "Quote not found", 404);
    if (sc === "network" && method === "GET")
      throw new ApiError("NETWORK", "Could not reach the server.");
    if (r[2] === "recalculate") {
      rec.startedAt = Date.now();
      rec.scenario = sc;
      rec.accepted = false;
    }
    if (r[2] === "accept") rec.accepted = true;
    return out(publicView(build(rec)));
  }

  // ── auth ──
  if (path === "/auth/login") {
    loggedIn = true;
    return out(user);
  }
  if (path === "/auth/logout") {
    loggedIn = false;
    return out(undefined);
  }
  if (path === "/auth/me") {
    if (!loggedIn) throw new ApiError("SESSION_EXPIRED", "Not signed in", 401);
    return out(user);
  }
  if (!loggedIn) throw new ApiError("SESSION_EXPIRED", "Not signed in", 401);

  // ── admin ──
  if (path === "/admin/dashboard") {
    const all = [...quotes.values()].map(build);
    const priced = all.filter((x) => x.fee),
      startToday = new Date().setHours(0, 0, 0, 0);
    const counts = new Map<string, number>();
    priced.forEach((x) =>
      counts.set(
        x.destination!.name,
        (counts.get(x.destination!.name) ?? 0) + 1,
      ),
    );
    return out({
      quotesToday: all.filter((x) => +new Date(x.createdAt) >= startToday)
        .length,
      quotesThisWeek: all.length,
      totalQuotedValue: {
        amount: priced.reduce((s, x) => s + x.fee!.amount, 0),
        currency: "KES",
      },
      averageDistanceKm: priced.length
        ? priced.reduce((s, x) => s + x.distanceKm!, 0) / priced.length
        : null,
      topDestinations: [...counts]
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 5),
      needsReview: all
        .filter((x) => x.status === "needs_review")
        .map((x) => ({
          id: x.id,
          locationLabel: x.location.label,
          reason: x.failure?.code.replace(/_/g, " ").toLowerCase(),
          createdAt: x.createdAt,
        })),
    });
  }
  if (path === "/admin/quotes") {
    let items = [...quotes.values()]
      .map(build)
      .reverse()
      .map((x) => ({ ...publicView(x), destinationName: x.destination?.name }));
    if (q.search)
      items = items.filter(
        (x) =>
          x.id.toLowerCase().includes(String(q.search).toLowerCase()) ||
          x.reference?.toLowerCase().includes(String(q.search).toLowerCase()),
      );
    if (q.status) items = items.filter((x) => x.status === q.status);
    if (q.destinationId)
      items = items.filter((x) => x.destination?.id === q.destinationId);
    if (q.from) items = items.filter((x) => x.createdAt.slice(0, 10) >= q.from);
    if (q.to) items = items.filter((x) => x.createdAt.slice(0, 10) <= q.to);
    return out(page(items, q));
  }
  if ((r = m(/^\/admin\/quotes\/(.+)$/))) {
    const rec = quotes.get(r[1].replace("Q-", ""));
    if (!rec) throw new ApiError("NOT_FOUND", "Quote not found", 404);
    return out(build(rec));
  }
  // ── distance pricing (model B) ──
  if (path === "/admin/dynamic-pricing") {
    if (method === "POST") {
      const base = Number(body.baseRatePerKm);
      const fuel = Number(body.fuelAdjustmentPercent ?? 0);
      const row: DynamicPricingVersion = {
        id: `dp-${++dpSeq}`,
        label: body.label,
        status: "draft",
        baseRatePerKm: base,
        fuelAdjustmentPercent: fuel,
        minCharge: body.minCharge ? Number(body.minCharge) : null,
        currency: "KES",
        effectiveRatePerKm: effective(base, fuel),
        effectiveFrom: null,
        notes: body.notes ?? null,
        createdAt: new Date().toISOString(),
        activatedAt: null,
        retiredAt: null,
      };
      dynamicRates = [row, ...dynamicRates];
      return out(row);
    }
    return out(dynamicRates);
  }
  if (path === "/admin/dynamic-pricing/active")
    return out(dynamicRates.find((r) => r.status === "active") ?? null);
  if (path === "/admin/dynamic-pricing/preview" && method === "POST") {
    const active = dynamicRates.find((r) => r.status === "active");
    const base = Number(body.baseRatePerKm ?? active?.baseRatePerKm ?? 0);
    const fuel = Number(body.fuelAdjustmentPercent ?? active?.fuelAdjustmentPercent ?? 0);
    const km = Number(body.distanceKm);
    const perKm = effective(base, fuel);
    if (!base)
      return out({
        priced: false,
        reason: "dynamic_pricing_unavailable",
        message: "No distance rate is configured, so there is nothing to preview.",
        currency: "KES",
        distanceKm: km,
      });
    const calculated = Number((km * perKm).toFixed(2));
    const total = Math.round(calculated);
    const fuelAmount = Number((km * base * (fuel / 100)).toFixed(2));
    const adjustments: { label: string; amount: number; kind: string }[] = [];
    if (fuelAmount)
      adjustments.push({ label: "Fuel adjustment", amount: fuelAmount, kind: "fuel" });
    if (total !== calculated)
      adjustments.push({
        label: "Rounding",
        amount: Number((total - calculated).toFixed(2)),
        kind: "rounding",
      });
    return out({
      priced: true,
      currency: "KES",
      distanceKm: km,
      configId: active?.id ?? "preview",
      configLabel: active ? `${active.label} (preview)` : "Unsaved preview",
      baseRatePerKm: base,
      fuelAdjustmentPercent: fuel,
      effectiveRatePerKm: perKm,
      total,
      adjustments,
      notes: [],
    });
  }
  if ((r = m(/^\/admin\/dynamic-pricing\/([^/]+)\/(activate|retire)$/))) {
    const row = dynamicRates.find((x) => x.id === r![1]);
    if (!row) throw new ApiError("NOT_FOUND", "Distance rate not found", 404);
    if (r![2] === "activate") {
      dynamicRates = dynamicRates.map((x) =>
        x.id === row.id
          ? { ...x, status: "active", activatedAt: new Date().toISOString() }
          : x.status === "active"
            ? { ...x, status: "retired", retiredAt: new Date().toISOString() }
            : x,
      );
      return out({
        versionId: row.id,
        label: row.label,
        activatedAt: new Date().toISOString(),
      });
    }
    if (row.status !== "active")
      throw new ApiError("VALIDATION", "Only the active rate can be retired.", 422);
    dynamicRates = dynamicRates.map((x) =>
      x.id === row.id
        ? { ...x, status: "retired", retiredAt: new Date().toISOString() }
        : x,
    );
    return out({ ...row, status: "retired" });
  }
  if (path.startsWith("/admin/dynamic-pricing/") && method === "PATCH")
    throw new ApiError(
      "VALIDATION",
      "This configuration is active, so it cannot be edited. Create a new one instead.",
      422,
    );

  if (sc === "server" && method === "GET" && path.startsWith("/admin/"))
    throw new ApiError("SERVER", "Internal error", 500);
  if ((r = m(/^\/admin\/destinations(?:\/(.+))?$/)))
    return out(
      crud(
        "Destination",
        "destination",
        () => destinations,
        (v) => (destinations = v),
        method,
        r[1],
        body,
        q,
        withPrice,
        (x, f) =>
          !f.search ||
          x.name.toLowerCase().includes(String(f.search).toLowerCase()),
      ),
    );
  if ((r = m(/^\/admin\/pricing-rules(?:\/(.+))?$/)))
    return out(
      crud(
        "Pricing rule",
        "pricing_rule",
        () => rules,
        (v) => (rules = v),
        method,
        r[1],
        body,
        q,
        hydrateRule,
        (x, f) => !f.destinationId || x.destinationId === f.destinationId,
      ),
    );
  if ((r = m(/^\/admin\/road-types(?:\/(.+))?$/)))
    return out(
      crud(
        "Road type",
        "road_type",
        () => roadTypes,
        (v) => (roadTypes = v),
        method,
        r[1],
        body,
        q,
      ),
    );
  if ((r = m(/^\/admin\/vehicles(?:\/(.+))?$/)))
    return out(
      crud(
        "Vehicle",
        "vehicle",
        () => vehicles,
        (v) => (vehicles = v),
        method,
        r[1],
        body,
        q,
      ),
    );
  if (path === "/admin/audit-log") {
    let items = audit.filter(
      (a) =>
        (!q.entityType || a.entityType === q.entityType) &&
        (!q.search ||
          `${a.actor} ${a.summary}`
            .toLowerCase()
            .includes(String(q.search).toLowerCase())),
    );
    return out(page(items, q));
  }
  if (path === "/admin/settings") {
    if (method === "PATCH") {
      settings = { ...settings, ...body };
      log("updated", "settings", "Updated settings");
    }
    return out(settings);
  }
  throw new ApiError("NOT_FOUND", `No mock for ${method} ${path}`, 404);
}
