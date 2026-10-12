import { useEffect, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Crosshair, MapPin, Navigation, Pencil } from "lucide-react";
import { ApiError, deliveryApi, quotesApi } from "@/services/api";
import {
  useLocationSearch,
  usePublicConfig,
  useRoutePreview,
} from "@/features/delivery/hooks";
import { SearchInput } from "@/components/ui/SearchInput";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { MapCard } from "@/components/map/MapCard";
import { MapPicker } from "@/components/map/MapPicker";
import { copyFor } from "@/components/delivery/quoteErrors";
import { referenceSchema, type ReferenceForm } from "@/schemas";
import { formatKm, formatMinutes } from "@/utils/format";
import type { CustomerOutletContext } from "@/layouts/CustomerLayout";
import type { GeoLocation, LatLng } from "@/types";

export default function LocatePage() {
  const nav = useNavigate();
  const { searchFocus, pendingLocation, consumePendingLocation, introVisible } =
    useOutletContext<CustomerOutletContext>();
  const config = usePublicConfig();
  const [text, setText] = useState("");
  const [selected, setSelected] = useState<GeoLocation | null>(null);
  const [pinError, setPinError] = useState<ApiError | null>(null);
  const [geoMessage, setGeoMessage] = useState<string | null>(null);
  const search = useLocationSearch(selected ? "" : text);
  const form = useForm<ReferenceForm>({
    resolver: zodResolver(referenceSchema),
    defaultValues: { reference: "" },
  });

  const reverse = useMutation({
    mutationFn: (p: LatLng) => deliveryApi.reverseGeocode(p),
    onSuccess: (loc) => {
      setSelected(loc);
      setText(loc.label);
      setPinError(null);
    },
    onError: (e) => {
      setSelected(null);
      setPinError(e as ApiError);
    },
  });
  const create = useMutation({
    mutationFn: (reference?: string) =>
      quotesApi.create({
        position: selected!.position,
        label: selected!.label,
        locationId: selected!.id,
        reference: reference || undefined,
      }),
    onSuccess: (q) => nav(`/quote/${q.id}`),
  });

  // A place chosen inside the cinematic opening arrives through the outlet context.
  useEffect(() => {
    if (!pendingLocation) return;
    setSelected(pendingLocation);
    setText(pendingLocation.label);
    setPinError(null);
    create.reset();
    consumePendingLocation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingLocation]);

  // Road distance and travel time from RIMs' dispatch, shown before a quote exists.
  const route = useRoutePreview(
    selected && !reverse.isPending ? selected.position : null,
  );

  const pick = (p: LatLng) => {
    setPinError(null);
    create.reset();
    setSelected({ id: "pin", label: "Finding address…", position: p });
    reverse.mutate(p);
  };
  const useMyLocation = () => {
    setGeoMessage(null);
    if (!navigator.geolocation) {
      setGeoMessage(
        "Your browser can’t share its location. Search or pin the spot on the map instead.",
      );
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => pick({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () =>
        setGeoMessage(
          "We couldn’t get your location. Allow location access, or search for a place instead.",
        ),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };
  const clear = () => {
    setSelected(null);
    setText("");
    create.reset();
    setPinError(null);
  };

  if (config.isError) {
    const c = copyFor((config.error as ApiError).code);
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState
          title={c.title}
          description={c.body}
          icon={c.icon}
          actions={<Button onClick={() => config.refetch()}>Try again</Button>}
        />
      </div>
    );
  }
  const cfg = config.data;
  const resolving = reverse.isPending;
  const createErr = create.error as ApiError | null;
  const candidates = (
    createErr?.details as { candidates?: GeoLocation[] } | undefined
  )?.candidates;

  return (
    <div className="grid lg:h-[calc(100dvh-4rem)] lg:grid-cols-[minmax(380px,480px)_1fr]">
      <div className="overflow-y-auto px-5 py-7 sm:px-8 lg:px-10 lg:py-12">
        <p className="eyebrow">Delivery estimate</p>
        <h1 className="text-[2rem] font-semibold leading-[1.08] tracking-tight sm:text-display">
          Know your delivery cost before you order.
        </h1>
        <p className="mt-3 max-w-md text-muted">
          Enter your delivery location and we’ll calculate the applicable
          delivery charge.
        </p>

        <div className="mt-7 space-y-3">
          <SearchInput
            label="Delivery location"
            value={text}
            onChange={(v) => {
              setText(v);
              if (selected) {
                setSelected(null);
              }
            }}
            placeholder="Town, area or address"
            results={search.data}
            loading={search.isFetching}
            focusSignal={searchFocus}
            onSelect={(r) => {
              setSelected(r as GeoLocation);
              setText(r.label);
              create.reset();
              setPinError(null);
            }}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={useMyLocation}
            className="-ml-2"
          >
            <Crosshair className="h-4 w-4" aria-hidden />
            Use my location
          </Button>
          {search.isError && (
            <p role="alert" className="text-small text-danger">
              Search isn’t working right now. You can still tap the map to drop
              a pin.
            </p>
          )}
          {geoMessage && (
            <p role="alert" className="text-small text-danger">
              {geoMessage}
            </p>
          )}
        </div>

        {pinError &&
          (() => {
            const c = copyFor(pinError.code);
            return (
              <ErrorState
                className="mt-6"
                title={c.title}
                description={c.body}
                icon={c.icon}
                tone={c.tone}
              />
            );
          })()}

        {selected && (
          <form
            onSubmit={form.handleSubmit((v) => create.mutate(v.reference))}
            className="mt-6 rounded-lg border border-line bg-surface p-5 shadow-sm"
            aria-labelledby="confirm-title"
            noValidate
          >
            <h2
              id="confirm-title"
              className="text-small font-medium text-muted"
            >
              Confirm delivery location
            </h2>
            <div className="mt-2 flex items-start gap-3">
              <MapPin
                className="mt-1 h-5 w-5 shrink-0 text-brand"
                aria-hidden
              />
              <div className="min-w-0">
                <p className="text-h2">
                  {resolving ? "Finding address…" : selected.label}
                </p>
                {!resolving && selected.secondary && (
                  <p className="text-muted">{selected.secondary}</p>
                )}
                {route.data && (
                  <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-small text-muted">
                    <Navigation className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="mono">
                      {formatKm(route.data.distanceKm)}
                    </span>
                    <span aria-hidden>·</span>
                    <span className="mono">
                      {formatMinutes(route.data.durationMinutes)}
                    </span>
                    <span>from RIMs dispatch</span>
                  </p>
                )}
              </div>
            </div>
            <p className="mt-3 flex items-center gap-2 text-small text-muted">
              <Pencil className="h-3.5 w-3.5" aria-hidden />
              Not quite right? Drag the pin or tap the map to adjust.
            </p>
            <Input
              className="mt-5"
              label="Your reference"
              optional
              hint="For example an order or job name. It appears on your quote."
              maxLength={80}
              error={form.formState.errors.reference?.message}
              {...form.register("reference")}
            />

            {createErr &&
              (() => {
                const c = copyFor(createErr.code);
                return (
                  <ErrorState
                    className="mt-5 shadow-none"
                    title={c.title}
                    description={
                      createErr.code === "NETWORK" ||
                      createErr.code === "SERVER"
                        ? c.body
                        : createErr.message && createErr.code !== "UNKNOWN"
                          ? createErr.message
                          : c.body
                    }
                    icon={c.icon}
                    tone={c.tone}
                  >
                    {candidates && (
                      <ul className="space-y-1.5">
                        {candidates.map((cand) => (
                          <li key={cand.id}>
                            <button
                              type="button"
                              className="w-full rounded border border-line px-3 py-2 text-left hover:bg-canvas"
                              onClick={() => {
                                setSelected(cand);
                                setText(cand.label);
                                create.reset();
                              }}
                            >
                              <span className="font-medium">{cand.label}</span>
                              {cand.secondary && (
                                <span className="block text-small text-muted">
                                  {cand.secondary}
                                </span>
                              )}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </ErrorState>
                );
              })()}

            <div className="mt-5 flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-between">
              <Button variant="ghost" onClick={clear}>
                Change location
              </Button>
              <Button
                type="submit"
                size="lg"
                loading={create.isPending}
                disabled={resolving}
              >
                Confirm and get estimate
              </Button>
            </div>
          </form>
        )}
      </div>

      <MapCard
        className="h-[42dvh] min-h-[280px] border-y border-line lg:h-full lg:border-y-0 lg:border-l"
        overlay={cfg && (
          <div className="flex min-w-0 items-center gap-2 rounded-lg border border-line bg-surface/95 px-3 py-2 text-small shadow-pop backdrop-blur-sm">
            <span className="inline-block h-3 w-3 shrink-0 rounded-[3px] bg-ink" aria-hidden />
            <span className="shrink-0 font-medium">RIMs dispatch</span>
            <span className="text-muted">·</span>
            <span className="truncate text-muted">{selected && !resolving ? selected.label : "Choose a delivery point"}</span>
            {route.data && (
              <>
                <span className="text-muted" aria-hidden>
                  ·
                </span>
                <span className="mono shrink-0 text-muted">
                  {formatKm(route.data.distanceKm)}
                </span>
                <span className="mono shrink-0 text-muted">
                  {formatMinutes(route.data.durationMinutes)}
                </span>
              </>
            )}
          </div>
        )}
      >
        {cfg && !introVisible ? (
          <MapPicker
            label="Map. RIMs dispatch location and your selected delivery location. Select a point by tapping or clicking."
            center={cfg.map.center}
            zoom={cfg.map.zoom}
            tileUrl={cfg.map.tileUrl}
            attribution={cfg.map.attribution}
            dispatch={cfg.dispatch}
            marker={selected?.position ?? null}
            onPick={pick}
          />
        ) : (
          <Skeleton className="h-full w-full rounded-none" />
        )}
      </MapCard>
    </div>
  );
}
