import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { MapPin, Navigation } from "lucide-react";
import { settingsApi, type ApiError } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { MapCard } from "@/components/map/MapCard";
import { MapPicker } from "@/components/map/MapPicker";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/features/auth/AuthProvider";
import { settingsSchema, type SettingsForm } from "@/schemas";
import type { LatLng } from "@/types";

const RIMS_DEFAULT_ORIGIN = {
  name: "RIMs Supplies and Hardware — Kenyatta Avenue, Naivasha",
  lat: -0.7256336,
  lng: 36.4448417,
};

export default function SettingsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { canEdit } = useAuth();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["settings"],
    queryFn: settingsApi.get,
  });

  const f = useForm<SettingsForm>({ resolver: zodResolver(settingsSchema) });
  const currentLat = f.watch("lat");
  const currentLng = f.watch("lng");
  const currentName = f.watch("dispatchName");

  useEffect(() => {
    if (data)
      f.reset({
        dispatchName: data.dispatch.name,
        lat: data.dispatch.lat,
        lng: data.dispatch.lng,
        contactPhone: data.contactPhone ?? "",
        contactEmail: data.contactEmail ?? "",
      });
  }, [data]); // eslint-disable-line

  const save = useMutation({
    mutationFn: (v: SettingsForm) =>
      settingsApi.update({
        dispatch: { name: v.dispatchName, lat: v.lat, lng: v.lng },
        contactPhone: v.contactPhone || null,
        contactEmail: v.contactEmail || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["public-config"] });
      toast.success("Settings saved");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Couldn’t save settings"),
  });

  const handleMapPick = (pos: LatLng) => {
    if (!canEdit) return;
    f.setValue("lat", Number(pos.lat.toFixed(7)));
    f.setValue("lng", Number(pos.lng.toFixed(7)));
  };

  const resetToNaivasha = () => {
    f.setValue("dispatchName", RIMS_DEFAULT_ORIGIN.name);
    f.setValue("lat", RIMS_DEFAULT_ORIGIN.lat);
    f.setValue("lng", RIMS_DEFAULT_ORIGIN.lng);
    toast.success("Reset to Kenyatta Avenue, Naivasha");
  };

  const e = f.formState.errors;

  return (
    <>
      <PageHeader
        title="Settings & Dispatch Location"
        description="Configure the physical RIMs dispatch depot and public contact channels for manual quote reviews."
      />
      {error ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Form Column */}
          <div className="space-y-6">
            <form
              noValidate
              onSubmit={f.handleSubmit((v) => save.mutate(v))}
              className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-sm"
            >
              <fieldset disabled={!canEdit} className="space-y-4">
                <div className="flex items-center justify-between border-b border-line pb-2">
                  <legend className="text-h2 font-semibold text-ink flex items-center gap-2">
                    <MapPin className="h-5 w-5 text-brand" aria-hidden />
                    RIMs Dispatch Origin
                  </legend>
                  {canEdit && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={resetToNaivasha}
                    >
                      <Navigation className="h-3.5 w-3.5" aria-hidden />
                      Reset to Naivasha
                    </Button>
                  )}
                </div>
                <Input
                  label="Depot premises display name"
                  error={e.dispatchName?.message}
                  {...f.register("dispatchName")}
                />
                <div className="grid grid-cols-2 gap-3">
                  <Input
                    label="Depot Latitude"
                    type="number"
                    step="any"
                    error={e.lat?.message}
                    {...f.register("lat", { valueAsNumber: true })}
                  />
                  <Input
                    label="Depot Longitude"
                    type="number"
                    step="any"
                    error={e.lng?.message}
                    {...f.register("lng", { valueAsNumber: true })}
                  />
                </div>
                <p className="text-small text-muted">
                  Click or drag the pin on the map to accurately place the RIMs dispatch point. All road distances and routing are calculated from this origin.
                </p>
              </fieldset>

              <fieldset
                disabled={!canEdit}
                className="space-y-4 border-t border-line pt-5"
              >
                <legend className="mb-1 text-h2 font-semibold text-ink">Customer Contact</legend>
                <Input
                  label="Phone number"
                  optional
                  type="tel"
                  placeholder="+254 700 000 000"
                  {...f.register("contactPhone")}
                />
                <Input
                  label="Support email"
                  optional
                  type="email"
                  placeholder="supplies@rims.co.ke"
                  error={e.contactEmail?.message}
                  {...f.register("contactEmail")}
                />
              </fieldset>

              {canEdit && (
                <div className="flex justify-end pt-2">
                  <Button type="submit" loading={save.isPending}>
                    Save Settings
                  </Button>
                </div>
              )}
            </form>

            <dl className="rounded-lg border border-line bg-surface text-body shadow-sm">
              <div className="flex justify-between border-b border-line px-6 py-3">
                <dt className="text-muted">Active pricing version</dt>
                <dd className="font-semibold text-ink">
                  {data?.activePricingVersion ?? "None (Draft only)"}
                </dd>
              </div>
              <div className="flex justify-between px-6 py-3">
                <dt className="text-muted">Routing & map provider</dt>
                <dd className="font-medium text-ink">
                  {data?.mapProvider ?? "OpenStreetMap / OSRM"}
                </dd>
              </div>
            </dl>
          </div>

          {/* Map Column */}
          <div className="space-y-3">
            <h3 className="text-small font-semibold uppercase tracking-wider text-muted">
              Live Dispatch Location Pin
            </h3>
            <MapCard className="h-[460px] rounded-lg border border-line shadow-sm lg:h-[540px]">
              {data && (
                <MapPicker
                  label="Map showing RIMs dispatch premises pin"
                  interactive={canEdit}
                  center={{
                    lat: currentLat || data.dispatch.lat,
                    lng: currentLng || data.dispatch.lng,
                  }}
                  zoom={14}
                  dispatch={{
                    name: currentName || data.dispatch.name,
                    lat: currentLat || data.dispatch.lat,
                    lng: currentLng || data.dispatch.lng,
                  }}
                  marker={
                    currentLat && currentLng
                      ? { lat: currentLat, lng: currentLng }
                      : null
                  }
                  onPick={handleMapPick}
                />
              )}
            </MapCard>
            <p className="text-small text-muted text-center">
              Coordinates: {currentLat?.toFixed(6)}, {currentLng?.toFixed(6)}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
