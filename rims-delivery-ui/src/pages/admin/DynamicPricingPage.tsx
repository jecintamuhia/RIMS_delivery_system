import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Play,
  Plus,
  StopCircle,
} from "lucide-react";
import { dynamicPricingApi, type ApiError } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/features/auth/AuthProvider";
import { formatDateTime } from "@/utils/format";
import type { DynamicPricingPreviewResult } from "@/types";

interface RateForm {
  label: string;
  baseRatePerKm: string;
  fuelAdjustmentPercent: string;
  minCharge: string;
  notes?: string;
}

const rate = (value: number | null | undefined) =>
  value == null ? "—" : Number(value).toFixed(2);

export default function DynamicPricingPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { canEdit, user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [newDrawer, setNewDrawer] = useState(false);
  const [previewDistance, setPreviewDistance] = useState("100");
  const [previewBase, setPreviewBase] = useState("");
  const [previewFuel, setPreviewFuel] = useState("");
  const [preview, setPreview] = useState<DynamicPricingPreviewResult | null>(
    null,
  );

  const { data: configs, isLoading, error, refetch } = useQuery({
    queryKey: ["dynamic-pricing"],
    queryFn: dynamicPricingApi.list,
  });
  const active = configs?.find((c) => c.status === "active") ?? null;

  const form = useForm<RateForm>({
    defaultValues: {
      label: "",
      baseRatePerKm: "",
      fuelAdjustmentPercent: "",
      minCharge: "",
      notes: "",
    },
  });

  const createMutation = useMutation({
    mutationFn: (v: RateForm) =>
      dynamicPricingApi.create({
        label: v.label,
        baseRatePerKm: v.baseRatePerKm,
        fuelAdjustmentPercent: v.fuelAdjustmentPercent || "0",
        minCharge: v.minCharge ? v.minCharge : null,
        notes: v.notes || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dynamic-pricing"] });
      setNewDrawer(false);
      form.reset();
      toast.success("Distance rate saved as a draft");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to save the rate"),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => dynamicPricingApi.activate(id),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["dynamic-pricing"] });
      toast.success(
        res.retiredLabel
          ? `'${res.label}' is now active; '${res.retiredLabel}' retired`
          : `'${res.label}' is now active`,
      );
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to activate the rate"),
  });

  const retireMutation = useMutation({
    mutationFn: (id: string) => dynamicPricingApi.retire(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dynamic-pricing"] });
      toast.success("Distance-based pricing switched off");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to retire the rate"),
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      dynamicPricingApi.preview({
        distanceKm: previewDistance,
        ...(previewBase ? { baseRatePerKm: previewBase } : {}),
        ...(previewFuel ? { fuelAdjustmentPercent: previewFuel } : {}),
      }),
    onSuccess: setPreview,
    onError: (e) => {
      setPreview(null);
      toast.error((e as ApiError).message || "Preview failed");
    },
  });

  return (
    <>
      <PageHeader
        title="Distance Pricing"
        description="Road distance x a configured rate per kilometre, used only for locations that are not on RIMs' official price list. Official destination prices are never replaced by this rate."
        actions={
          canEdit && (
            <Button size="sm" onClick={() => setNewDrawer(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              New distance rate
            </Button>
          )
        }
      />

      {error ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-32 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div className="space-y-6">
            {active ? (
              <section className="rounded-lg border border-brand/40 bg-brand-soft/40 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="space-y-1">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-0.5 text-small font-medium text-brand-strong">
                      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                      Active distance rate
                    </span>
                    <h2 className="text-h2 font-semibold text-ink">
                      {active.label}
                    </h2>
                    <p className="text-small text-muted">
                      Effective from{" "}
                      {active.activatedAt
                        ? formatDateTime(active.activatedAt)
                        : "activation"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="mono text-h1 font-semibold text-ink">
                      KES {rate(active.effectiveRatePerKm)}
                    </p>
                    <p className="text-small text-muted">per kilometre, all in</p>
                  </div>
                </div>
                <dl className="mt-4 grid gap-3 border-t border-brand/25 pt-4 text-small sm:grid-cols-3">
                  <div>
                    <dt className="text-muted">Base rate</dt>
                    <dd className="mono font-medium">
                      KES {rate(active.baseRatePerKm)}/km
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">Fuel adjustment</dt>
                    <dd className="mono font-medium">
                      {rate(active.fuelAdjustmentPercent)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">Minimum charge</dt>
                    <dd className="mono font-medium">
                      {active.minCharge == null
                        ? "None"
                        : `KES ${rate(active.minCharge)}`}
                    </dd>
                  </div>
                </dl>
                {isAdmin && (
                  <div className="mt-4 flex justify-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={retireMutation.isPending}
                      onClick={() => retireMutation.mutate(active.id)}
                    >
                      <StopCircle className="h-4 w-4" aria-hidden />
                      Switch off distance pricing
                    </Button>
                  </div>
                )}
              </section>
            ) : (
              <div className="flex items-start gap-3 rounded-lg border border-warn/40 bg-warn-soft/40 p-5">
                <AlertTriangle
                  className="mt-0.5 h-5 w-5 shrink-0 text-warn"
                  aria-hidden
                />
                <div className="space-y-1">
                  <p className="font-semibold text-ink">
                    Distance pricing is switched off
                  </p>
                  <p className="text-small text-muted">
                    A location that is not on the official price list cannot be
                    quoted automatically and will be sent for manual review.
                    Activate a rate below to price it from the road distance.
                  </p>
                </div>
              </div>
            )}

            <section className="overflow-hidden rounded-lg border border-line bg-surface shadow-sm">
              <div className="border-b border-line px-5 py-4">
                <h3 className="text-h2 font-medium">All distance rates</h3>
                <p className="text-small text-muted">
                  Only one can be active. The active rate cannot be edited - a
                  change is made by activating a new one, so quotes already
                  issued keep the rate they were priced with.
                </p>
              </div>
              {!configs?.length ? (
                <div className="p-8 text-center text-muted">
                  <Gauge className="mx-auto h-8 w-8 text-muted/60" aria-hidden />
                  <p className="mt-2 font-medium">No distance rates configured</p>
                  <p className="text-small">
                    Create one to price deliveries outside the price list.
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-small">
                    <thead className="border-b border-line bg-canvas/40 text-muted">
                      <tr>
                        <th className="px-5 py-3 font-medium">Rate</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                        <th className="px-4 py-3 font-medium text-right">
                          Base / km
                        </th>
                        <th className="px-4 py-3 font-medium text-right">Fuel</th>
                        <th className="px-4 py-3 font-medium text-right">
                          Effective / km
                        </th>
                        <th className="px-5 py-3 font-medium text-right">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {configs.map((cfg) => (
                        <tr key={cfg.id} className="hover:bg-canvas/30">
                          <td className="px-5 py-4">
                            <p className="font-medium text-ink">{cfg.label}</p>
                            <p className="text-small text-muted">
                              Created {formatDateTime(cfg.createdAt)}
                            </p>
                          </td>
                          <td className="px-4 py-4">
                            <StatusBadge
                              tone={
                                cfg.status === "active"
                                  ? "ok"
                                  : cfg.status === "draft"
                                    ? "warn"
                                    : "neutral"
                              }
                            >
                              {cfg.status.toUpperCase()}
                            </StatusBadge>
                          </td>
                          <td className="mono px-4 py-4 text-right">
                            {rate(cfg.baseRatePerKm)}
                          </td>
                          <td className="mono px-4 py-4 text-right">
                            {rate(cfg.fuelAdjustmentPercent)}%
                          </td>
                          <td className="mono px-4 py-4 text-right font-medium text-ink">
                            {rate(cfg.effectiveRatePerKm)}
                          </td>
                          <td className="px-5 py-4 text-right">
                            {cfg.status === "draft" && isAdmin && (
                              <Button
                                size="sm"
                                loading={
                                  activateMutation.isPending &&
                                  activateMutation.variables === cfg.id
                                }
                                onClick={() => activateMutation.mutate(cfg.id)}
                              >
                                <Play className="h-4 w-4" aria-hidden />
                                Activate
                              </Button>
                            )}
                            {cfg.status === "retired" && (
                              <span className="text-small text-muted">
                                Archived
                              </span>
                            )}
                            {cfg.status === "active" && (
                              <span className="text-small text-muted">In use</span>
                            )}
                            {cfg.status === "draft" && !isAdmin && (
                              <span className="text-small text-muted">
                                Awaiting admin
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          {/* Preview: the server runs the real pricing engine, never a second copy of the maths. */}
          <section className="h-fit rounded-lg border border-line bg-surface p-5 shadow-sm">
            <h3 className="text-h2 font-medium">Preview a distance</h3>
            <p className="mt-1 text-small text-muted">
              The API prices it with the same engine used for live quotes. Try a
              rate before saving it.
            </p>
            <div className="mt-4 space-y-3">
              <Input
                label="Road distance (km)"
                inputMode="decimal"
                value={previewDistance}
                onChange={(e) => setPreviewDistance(e.target.value)}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label="Base rate (KES/km)"
                  optional
                  inputMode="decimal"
                  placeholder={active ? rate(active.baseRatePerKm) : "e.g. 50"}
                  value={previewBase}
                  onChange={(e) => setPreviewBase(e.target.value)}
                />
                <Input
                  label="Fuel adjustment (%)"
                  optional
                  inputMode="decimal"
                  placeholder={
                    active ? rate(active.fuelAdjustmentPercent) : "e.g. 10"
                  }
                  value={previewFuel}
                  onChange={(e) => setPreviewFuel(e.target.value)}
                />
              </div>
              <Button
                className="w-full"
                loading={previewMutation.isPending}
                disabled={!previewDistance.trim()}
                onClick={() => previewMutation.mutate()}
              >
                Preview price
              </Button>
            </div>

            {preview && (
              <div
                aria-live="polite"
                className="mt-4 space-y-3 rounded-md border border-line bg-canvas/60 p-4"
              >
                {preview.priced ? (
                  <>
                    <div className="flex items-end justify-between gap-3">
                      <div>
                        <p className="text-small text-muted">Total charge</p>
                        <p className="mono text-h1 font-semibold text-ink">
                          KES {Number(preview.total ?? 0).toFixed(2)}
                        </p>
                      </div>
                      <p className="mono text-right text-small text-muted">
                        KES {rate(preview.effectiveRatePerKm)}/km
                      </p>
                    </div>
                    <dl className="space-y-1.5 border-t border-line pt-3 text-small">
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted">Road distance</dt>
                        <dd className="mono">{preview.distanceKm} km</dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted">Base rate</dt>
                        <dd className="mono">
                          KES {rate(preview.baseRatePerKm)}/km
                        </dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted">Fuel adjustment</dt>
                        <dd className="mono">
                          {rate(preview.fuelAdjustmentPercent)}%
                        </dd>
                      </div>
                      {preview.adjustments?.map((adj) => (
                        <div
                          key={adj.label}
                          className="flex justify-between gap-4"
                        >
                          <dt className="text-muted">{adj.label}</dt>
                          <dd className="mono">
                            + KES {Number(adj.amount).toFixed(2)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <p className="text-small text-muted">
                      {preview.configLabel
                        ? `Priced with “${preview.configLabel}”`
                        : "Unsaved preview"}
                    </p>
                  </>
                ) : (
                  <p className="text-small text-warn">
                    {preview.message ??
                      "No distance rate is configured, so nothing was priced."}
                  </p>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      <Drawer
        open={newDrawer}
        onClose={() => setNewDrawer(false)}
        title="New distance rate"
        footer={
          <div className="flex w-full justify-end gap-3">
            <Button variant="secondary" onClick={() => setNewDrawer(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              form="rate-form"
              loading={createMutation.isPending}
            >
              Save as draft
            </Button>
          </div>
        }
      >
        <form
          id="rate-form"
          className="space-y-4"
          onSubmit={form.handleSubmit((v) => createMutation.mutate(v))}
        >
          <p className="text-small text-muted">
            A draft changes nothing. An administrator activates it, and until
            then quotes keep using the current rate.
          </p>
          <Input
            label="Label"
            placeholder="e.g. November 2026 distance rate"
            required
            {...form.register("label", { required: true })}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Base rate (KES per km)"
              inputMode="decimal"
              placeholder="50"
              required
              {...form.register("baseRatePerKm", { required: true })}
            />
            <Input
              label="Fuel adjustment (%)"
              inputMode="decimal"
              placeholder="10"
              hint="Added to the base rate. Use a negative number to reduce it."
              {...form.register("fuelAdjustmentPercent")}
            />
          </div>
          <Input
            label="Minimum charge (KES)"
            optional
            inputMode="decimal"
            hint="A short delivery is never quoted below this amount."
            {...form.register("minCharge")}
          />
          <Input
            label="Notes"
            optional
            placeholder="Why this rate was set"
            {...form.register("notes")}
          />
        </form>
      </Drawer>
    </>
  );
}
