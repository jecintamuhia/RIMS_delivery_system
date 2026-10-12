import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Truck } from "lucide-react";
import { vehiclesApi } from "@/services/api";
import { useResource } from "@/features/crud";
import { ResourceTable } from "@/features/ResourceTable";
import { Drawer } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Checkbox } from "@/components/ui/Input";
import { ActiveBadge } from "@/components/ui/StatusBadge";
import { vehicleSchema, numberOrNull, type VehicleForm } from "@/schemas";
import type { VehicleCategory } from "@/types";

const blank: VehicleForm = {
  name: "",
  code: "",
  maxWeightKg: null,
  maxVolumeM3: null,
  active: true,
};

export default function VehiclesPage() {
  const { list, save, toggle } = useResource(
    "vehicles",
    vehiclesApi,
    { pageSize: 100 },
    "Vehicle",
  );
  const [editing, setEditing] = useState<VehicleCategory | "new" | null>(null);
  const f = useForm<VehicleForm>({
    resolver: zodResolver(vehicleSchema),
    defaultValues: blank,
  });
  useEffect(() => {
    if (editing)
      f.reset(
        editing === "new"
          ? blank
          : {
              name: editing.name,
              code: editing.code,
              maxWeightKg: editing.maxWeightKg ?? null,
              maxVolumeM3: editing.maxVolumeM3 ?? null,
              active: editing.active,
            },
      );
  }, [editing]); // eslint-disable-line
  const e = f.formState.errors;
  return (
    <>
      <ResourceTable<VehicleCategory>
        title="Vehicles"
        noun="vehicle"
        icon={Truck}
        description="Vehicle categories and their capacity. Add the categories RIMs prices by; none are assumed."
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
            key: "name",
            header: "Vehicle",
            cell: (r) => <span className="font-medium">{r.name}</span>,
          },
          { key: "code", header: "Code", cell: (r) => r.code },
          {
            key: "w",
            header: "Max weight",
            align: "right",
            cell: (r) =>
              r.maxWeightKg != null
                ? `${r.maxWeightKg.toLocaleString()} kg`
                : "—",
          },
          {
            key: "v",
            header: "Max volume",
            align: "right",
            cell: (r) => (r.maxVolumeM3 != null ? `${r.maxVolumeM3} m³` : "—"),
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
        title={editing === "new" ? "New vehicle" : "Edit vehicle"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="submit" form="veh-form" loading={save.isPending}>
              Save vehicle
            </Button>
          </>
        }
      >
        <form
          id="veh-form"
          noValidate
          className="space-y-4"
          onSubmit={f.handleSubmit((v) =>
            save.mutate(
              { id: editing !== "new" ? editing?.id : undefined, body: v },
              { onSuccess: () => setEditing(null) },
            ),
          )}
        >
          <Input
            label="Vehicle name"
            error={e.name?.message}
            {...f.register("name")}
          />
          <Input label="Code" error={e.code?.message} {...f.register("code")} />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Max weight (kg)"
              optional
              type="number"
              step="any"
              inputMode="decimal"
              error={e.maxWeightKg?.message}
              {...f.register("maxWeightKg", { setValueAs: numberOrNull })}
            />
            <Input
              label="Max volume (m³)"
              optional
              type="number"
              step="any"
              inputMode="decimal"
              error={e.maxVolumeM3?.message}
              {...f.register("maxVolumeM3", { setValueAs: numberOrNull })}
            />
          </div>
          <Checkbox label="Active" {...f.register("active")} />
        </form>
      </Drawer>
    </>
  );
}
