import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  MapPin,
  Plus,
  Tag,
} from "lucide-react";
import { destinationsApi, type ApiError } from "@/services/api";
import { useResource } from "@/features/crud";
import { ResourceTable } from "@/features/ResourceTable";
import { Drawer } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Checkbox } from "@/components/ui/Input";
import { SearchInput } from "@/components/ui/SearchInput";
import { ActiveBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import {
  destinationSchema,
  numberOrNull,
  type DestinationForm,
} from "@/schemas";
import { formatKES } from "@/utils/format";
import { useDebounced } from "@/utils/useDebounced";
import type { Destination } from "@/types";

export const FLAGGED_DESTINATIONS: Record<string, string> = {
  "G!TUAMBA":
    "Contains exclamation mark '!'. Verify spelling (e.g. Gituamba) and add alias if needed.",
  "TOWN AREA":
    "Vague name representing Naivasha Town central area. Needs coordinates or catchment radius to resolve map pins.",
  "FLYOVER":
    "Vague highway interchange name on Nairobi-Nakuru road. Needs GPS coordinates or alias.",
  "JUNCTION":
    "Vague intersection name. Needs GPS pin or catchment to identify exact junction.",
  "DTI":
    "Acronym (Dairy Training Institute, Naivasha). Recommended to add full alias and coordinates.",
  "SLAUGHTER":
    "Colloquial local area (Naivasha Slaughterhouse). Needs coordinates or alias.",
  "DCK":
    "Acronym/farm name (DCK farm area along Moi South Lake Rd). Needs coordinates.",
  "VI":
    "Abbreviated name (Viwandani ward / Villa). Clarify name or provide alias.",
};

const blank: DestinationForm = {
  name: "",
  code: "",
  zone: "",
  county: "",
  lat: null,
  lng: null,
  active: true,
};

export default function DestinationsPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "flagged" | "unpinned">("all");
  const [newAlias, setNewAlias] = useState("");
  const dq = useDebounced(q);

  const { list, save, toggle } = useResource(
    "destinations",
    destinationsApi,
    { pageSize: 200, search: dq },
    "Destination",
  );

  const [editing, setEditing] = useState<Destination | "new" | null>(null);

  const f = useForm<DestinationForm & { catchmentRadiusKm?: number | null }>({
    resolver: zodResolver(destinationSchema),
    defaultValues: blank,
  });

  useEffect(() => {
    if (editing) {
      f.reset(
        editing === "new"
          ? blank
          : {
              name: editing.name,
              code: editing.code,
              zone: editing.zone,
              county: editing.county ?? "",
              lat: editing.position?.lat ?? null,
              lng: editing.position?.lng ?? null,
              catchmentRadiusKm: editing.catchmentRadiusKm ?? null,
              active: editing.active,
            },
      );
    }
  }, [editing]); // eslint-disable-line

  const addAliasMutation = useMutation({
    mutationFn: ({ destId, alias }: { destId: string; alias: string }) =>
      destinationsApi.addAlias(destId, alias),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["destinations"] });
      setEditing(updated);
      setNewAlias("");
      toast.success("Alias added");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to add alias"),
  });

  const e = f.formState.errors;

  // Filter items by activeTab
  const rawItems = list.data?.items ?? [];
  const filteredItems = rawItems.filter((d) => {
    if (activeTab === "flagged") {
      return Object.keys(FLAGGED_DESTINATIONS).some(
        (fn) => fn.toUpperCase() === d.name.toUpperCase(),
      );
    }
    if (activeTab === "unpinned") {
      return !d.position?.lat || !d.position?.lng;
    }
    return true;
  });

  const flaggedCount = rawItems.filter((d) =>
    Object.keys(FLAGGED_DESTINATIONS).some(
      (fn) => fn.toUpperCase() === d.name.toUpperCase(),
    ),
  ).length;

  const currentFlaggedReason =
    editing && editing !== "new"
      ? FLAGGED_DESTINATIONS[editing.name.toUpperCase()] ||
        FLAGGED_DESTINATIONS[editing.name]
      : null;

  return (
    <>
      <ResourceTable<Destination>
        title="Destinations"
        noun="destination"
        icon={MapPin}
        description="Delivery areas RIMs serves. Fixed prices are retrieved from the active pricing version."
        filters={
          <div className="flex flex-col gap-3 w-full sm:flex-row sm:items-center sm:justify-between">
            <div className="w-full max-w-sm">
              <SearchInput
                hideLabel
                label="Search destinations"
                value={q}
                onChange={setQ}
                placeholder="Search destinations (e.g. Gilgil, Town Area)"
              />
            </div>
            <div className="flex items-center gap-1.5 rounded-lg border border-line bg-canvas/60 p-1 text-small">
              <button
                type="button"
                onClick={() => setActiveTab("all")}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  activeTab === "all"
                    ? "bg-surface text-ink shadow-xs"
                    : "text-muted hover:text-ink"
                }`}
              >
                All ({rawItems.length})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("flagged")}
                className={`flex items-center gap-1.5 rounded px-2.5 py-1 font-medium transition-colors ${
                  activeTab === "flagged"
                    ? "bg-warn-soft text-warn font-semibold shadow-xs"
                    : "text-muted hover:text-ink"
                }`}
              >
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                Review Flagged ({flaggedCount || 8})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("unpinned")}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  activeTab === "unpinned"
                    ? "bg-surface text-ink shadow-xs"
                    : "text-muted hover:text-ink"
                }`}
              >
                Unpinned
              </button>
            </div>
          </div>
        }
        data={list.data ? { ...list.data, items: filteredItems, total: filteredItems.length } : undefined}
        loading={list.isLoading}
        error={list.error}
        onRetry={() => list.refetch()}
        onCreate={() => setEditing("new")}
        onEdit={setEditing}
        onToggle={(r) => toggle.mutate({ id: r.id, active: !r.active })}
        toggling={toggle.isPending}
        extraActions={(r) => (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => nav(`/admin/pricing-rules?destinationId=${r.id}`)}
          >
            Pricing
          </Button>
        )}
        columns={[
          {
            key: "name",
            header: "Destination",
            cell: (r) => {
              const isFlagged = Object.keys(FLAGGED_DESTINATIONS).some(
                (fn) => fn.toUpperCase() === r.name.toUpperCase(),
              );
              return (
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">{r.name}</span>
                    {isFlagged && (
                      <span className="inline-flex items-center gap-1 rounded bg-warn-soft px-1.5 py-0.5 text-[11px] font-semibold text-warn">
                        <AlertTriangle className="h-3 w-3" aria-hidden />
                        Review
                      </span>
                    )}
                  </div>
                  {r.aliases && r.aliases.length > 0 && (
                    <p className="text-[11px] text-muted">
                      Aliases: {r.aliases.join(", ")}
                    </p>
                  )}
                </div>
              );
            },
          },
          { key: "code", header: "Code", cell: (r) => r.code },
          { key: "zone", header: "Zone", cell: (r) => r.zone || "—" },
          {
            key: "coordinates",
            header: "Geographic Location",
            cell: (r) =>
              r.position?.lat && r.position?.lng ? (
                <span className="tabular-nums text-small text-ink">
                  {r.position.lat.toFixed(4)}, {r.position.lng.toFixed(4)}
                </span>
              ) : (
                <span className="text-small text-muted italic">No GPS pin</span>
              ),
          },
          {
            key: "price",
            header: "Current base price",
            align: "right",
            cell: (r) =>
              r.currentBasePrice ? (
                <span className="font-semibold text-ink">
                  KES {formatKES(r.currentBasePrice.amount)}
                </span>
              ) : (
                <span className="text-warn text-small font-medium">No active rule</span>
              ),
          },
          {
            key: "status",
            header: "Status",
            cell: (r) => <ActiveBadge active={r.active} />,
          },
        ]}
      />

      <Drawer
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "New destination" : `Edit: ${editing?.name}`}
        footer={
          <div className="flex justify-end gap-3 w-full">
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="submit" form="dest-form" loading={save.isPending}>
              Save destination
            </Button>
          </div>
        }
      >
        <div className="space-y-6">
          {/* Flagged destination advisory notice */}
          {currentFlaggedReason && (
            <div className="rounded-lg border border-warn/40 bg-warn-soft/40 p-4">
              <div className="flex items-start gap-2.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
                <div className="text-small">
                  <p className="font-semibold text-warn">Flagged for Administrative Review</p>
                  <p className="mt-1 text-ink/80">{currentFlaggedReason}</p>
                  <p className="mt-1.5 text-muted">
                    Do not silently guess or rename this destination. You can add aliases or precise geographic coordinates below.
                  </p>
                </div>
              </div>
            </div>
          )}

          <form
            id="dest-form"
            noValidate
            className="space-y-4"
            onSubmit={f.handleSubmit((v) => {
              const { lat, lng, catchmentRadiusKm, ...rest } = v;
              save.mutate(
                {
                  id: editing !== "new" ? editing?.id : undefined,
                  body: {
                    ...rest,
                    county: rest.county || null,
                    catchmentRadiusKm: catchmentRadiusKm ?? null,
                    position: lat !== null && lng !== null ? { lat, lng } : null,
                  },
                },
                { onSuccess: () => setEditing(null) },
              );
            })}
          >
            <Input
              label="Destination name"
              error={e.name?.message}
              {...f.register("name")}
            />
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Code"
                error={e.code?.message}
                {...f.register("code")}
              />
              <Input
                label="Zone"
                error={e.zone?.message}
                {...f.register("zone")}
              />
            </div>
            <Input label="County" optional {...f.register("county")} />
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Latitude"
                optional
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="-0.7256"
                error={e.lat?.message}
                {...f.register("lat", { setValueAs: numberOrNull })}
              />
              <Input
                label="Longitude"
                optional
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="36.4448"
                error={e.lng?.message}
                {...f.register("lng", { setValueAs: numberOrNull })}
              />
            </div>
            <Input
              label="Catchment Radius (km)"
              optional
              type="number"
              step="any"
              placeholder="e.g. 5.0"
              hint="Radius in km around coordinates that resolves to this destination"
              {...f.register("catchmentRadiusKm", { setValueAs: numberOrNull })}
            />
            <Checkbox label="Active for delivery" {...f.register("active")} />
          </form>

          {/* Aliases Configuration (for existing destination) */}
          {editing && editing !== "new" && (
            <div className="border-t border-line pt-5 space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-small font-semibold text-ink flex items-center gap-1.5">
                  <Tag className="h-4 w-4 text-brand" aria-hidden />
                  Configured Aliases
                </label>
                <span className="text-small text-muted">
                  {editing.aliases?.length ?? 0} alias(es)
                </span>
              </div>
              <p className="text-small text-muted">
                Alternative names or spellings that map directly to this destination during address search.
              </p>

              {editing.aliases && editing.aliases.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {editing.aliases.map((aliasName) => (
                    <span
                      key={aliasName}
                      className="inline-flex items-center gap-1 rounded bg-ink/5 px-2.5 py-1 text-small font-medium text-ink"
                    >
                      {aliasName}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-small text-muted italic">No custom aliases added yet.</p>
              )}

              <div className="flex items-center gap-2 pt-2">
                <Input
                  label="Add destination alias"
                  placeholder="New alias (e.g. Gituamba)"
                  value={newAlias}
                  onChange={(e) => setNewAlias(e.target.value)}
                  className="flex-1"
                />
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!newAlias.trim()}
                  loading={addAliasMutation.isPending}
                  onClick={() =>
                    addAliasMutation.mutate({
                      destId: editing.id,
                      alias: newAlias.trim(),
                    })
                  }
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  Add
                </Button>
              </div>
            </div>
          )}
        </div>
      </Drawer>
    </>
  );
}
