import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Tag } from "lucide-react";
import {
  destinationsApi,
  pricingApi,
  roadsApi,
  vehiclesApi,
} from "@/services/api";
import { useOptions, useResource } from "@/features/crud";
import { ResourceTable } from "@/features/ResourceTable";
import { Drawer } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Checkbox } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { ActiveBadge } from "@/components/ui/StatusBadge";
import {
  pricingRuleSchema,
  numberOrNull,
  type PricingRuleForm,
} from "@/schemas";
import { formatDate, formatKES } from "@/utils/format";
import type { PricingRule } from "@/types";

const today = () => new Date().toISOString().slice(0, 10);
const blank = (destinationId = ""): PricingRuleForm => ({
  destinationId,
  roadTypeId: null,
  vehicleId: null,
  basePrice: undefined as unknown as number,
  adjustmentType: "none",
  adjustmentValue: null,
  effectiveFrom: today(),
  effectiveTo: null,
  priority: 0,
  active: true,
});
const nullIfEmpty = (v: string) => (v === "" ? null : v);

export default function PricingRulesPage() {
  const [sp, setSp] = useSearchParams();
  const destinationId = sp.get("destinationId") ?? "";
  const { list, save, toggle } = useResource(
    "pricing-rules",
    pricingApi,
    { pageSize: 200, destinationId },
    "Pricing rule",
  );
  const dests = useOptions("destinations", destinationsApi);
  const roads = useOptions("road-types", roadsApi);
  const vehicles = useOptions("vehicles", vehiclesApi);
  const [editing, setEditing] = useState<PricingRule | "new" | null>(null);
  const f = useForm<PricingRuleForm>({
    resolver: zodResolver(pricingRuleSchema),
    defaultValues: blank(),
  });
  const adjType = f.watch("adjustmentType");
  useEffect(() => {
    if (!editing) return;
    f.reset(
      editing === "new"
        ? blank(destinationId)
        : {
            destinationId: editing.destinationId,
            roadTypeId: editing.roadTypeId ?? null,
            vehicleId: editing.vehicleId ?? null,
            basePrice: editing.basePrice,
            adjustmentType: editing.adjustmentType,
            adjustmentValue: editing.adjustmentValue ?? null,
            effectiveFrom: editing.effectiveFrom.slice(0, 10),
            effectiveTo: editing.effectiveTo?.slice(0, 10) ?? null,
            priority: editing.priority,
            active: editing.active,
          },
    );
  }, [editing]); // eslint-disable-line
  const e = f.formState.errors;
  const opts = (items?: { id: string; name: string }[]) =>
    (items ?? []).map((i) => ({ value: i.id, label: i.name }));
  const adj = (r: PricingRule) =>
    r.adjustmentType === "none"
      ? "—"
      : r.adjustmentType === "percent"
        ? `${r.adjustmentValue}%`
        : `KES ${formatKES(r.adjustmentValue ?? 0)}`;
  return (
    <>
      <ResourceTable<PricingRule & { name?: string }>
        title="Pricing Rules"
        noun="pricing rule"
        icon={Tag}
        description="The rules the pricing engine applies. A more specific rule (road type or vehicle set) with higher priority wins."
        filters={
          <Select
            label="Destination"
            className="w-64"
            placeholder="All destinations"
            value={destinationId}
            options={opts(dests.data?.items)}
            onChange={(ev) =>
              setSp(ev.target.value ? { destinationId: ev.target.value } : {})
            }
          />
        }
        emptyHint="Add a rule to give a destination a delivery price. Destinations without an active rule can’t be priced."
        data={list.data}
        loading={list.isLoading}
        error={list.error}
        onRetry={() => list.refetch()}
        onCreate={() => setEditing("new")}
        onEdit={setEditing}
        onToggle={(r) => toggle.mutate({ id: r.id, active: !r.active })}
        toggling={toggle.isPending}
        columns={[
          {
            key: "dest",
            header: "Destination",
            cell: (r) => (
              <span className="font-medium">
                {r.destinationName ?? r.destinationId}
              </span>
            ),
          },
          {
            key: "road",
            header: "Road type",
            cell: (r) =>
              r.roadTypeName ?? <span className="text-muted">Any</span>,
          },
          {
            key: "veh",
            header: "Vehicle",
            cell: (r) =>
              r.vehicleName ?? <span className="text-muted">Any</span>,
          },
          {
            key: "base",
            header: "Base price",
            align: "right",
            cell: (r) => `KES ${formatKES(r.basePrice)}`,
          },
          { key: "adj", header: "Adjustment", align: "right", cell: adj },
          {
            key: "dates",
            header: "Effective",
            cell: (r) => (
              <span className="whitespace-nowrap">
                {formatDate(r.effectiveFrom)} →{" "}
                {r.effectiveTo ? formatDate(r.effectiveTo) : "No expiry"}
              </span>
            ),
          },
          {
            key: "prio",
            header: "Priority",
            align: "right",
            cell: (r) => r.priority,
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
        title={editing === "new" ? "New pricing rule" : "Edit pricing rule"}
        description="Saved changes create a new pricing version on the server."
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="submit" form="rule-form" loading={save.isPending}>
              Save rule
            </Button>
          </>
        }
      >
        <form
          id="rule-form"
          noValidate
          className="space-y-4"
          onSubmit={f.handleSubmit((v) =>
            save.mutate(
              {
                id: editing !== "new" ? editing?.id : undefined,
                body: {
                  ...v,
                  adjustmentValue:
                    v.adjustmentType === "none" ? null : v.adjustmentValue,
                  effectiveTo: v.effectiveTo || null,
                },
              },
              { onSuccess: () => setEditing(null) },
            ),
          )}
        >
          <Select
            label="Destination"
            placeholder="Choose a destination"
            options={opts(dests.data?.items)}
            error={e.destinationId?.message}
            {...f.register("destinationId")}
          />
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Road type"
              optional
              placeholder="Any road type"
              options={opts(roads.data?.items)}
              {...f.register("roadTypeId", { setValueAs: nullIfEmpty })}
            />
            <Select
              label="Vehicle"
              optional
              placeholder="Any vehicle"
              options={opts(vehicles.data?.items)}
              {...f.register("vehicleId", { setValueAs: nullIfEmpty })}
            />
          </div>
          <Input
            label="Base price (KES)"
            type="number"
            step="any"
            inputMode="decimal"
            error={e.basePrice?.message}
            {...f.register("basePrice", { valueAsNumber: true })}
          />
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Adjustment"
              options={[
                { value: "none", label: "None" },
                { value: "fixed", label: "Fixed amount (KES)" },
                { value: "percent", label: "Percentage" },
              ]}
              {...f.register("adjustmentType")}
            />
            <Input
              label="Adjustment value"
              type="number"
              step="any"
              inputMode="decimal"
              disabled={adjType === "none"}
              error={e.adjustmentValue?.message}
              {...f.register("adjustmentValue", { setValueAs: numberOrNull })}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Effective from"
              type="date"
              error={e.effectiveFrom?.message}
              {...f.register("effectiveFrom")}
            />
            <Input
              label="Expires"
              optional
              type="date"
              error={e.effectiveTo?.message}
              {...f.register("effectiveTo", { setValueAs: nullIfEmpty })}
            />
          </div>
          <Input
            label="Priority"
            type="number"
            hint="Higher numbers are checked first when several rules match."
            error={e.priority?.message}
            {...f.register("priority", { valueAsNumber: true })}
          />
          <Checkbox label="Active" {...f.register("active")} />
        </form>
      </Drawer>
    </>
  );
}
