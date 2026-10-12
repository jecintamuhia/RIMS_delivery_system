import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Route } from "lucide-react";
import { roadsApi } from "@/services/api";
import { useResource } from "@/features/crud";
import { ResourceTable } from "@/features/ResourceTable";
import { Drawer } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Checkbox } from "@/components/ui/Input";
import { ActiveBadge } from "@/components/ui/StatusBadge";
import { roadTypeSchema, type RoadTypeForm } from "@/schemas";
import type { RoadType } from "@/types";

const blank: RoadTypeForm = {
  name: "",
  code: "",
  description: "",
  active: true,
};

export default function RoadTypesPage() {
  const { list, save, toggle } = useResource(
    "road-types",
    roadsApi,
    { pageSize: 100 },
    "Road type",
  );
  const [editing, setEditing] = useState<RoadType | "new" | null>(null);
  const f = useForm<RoadTypeForm>({
    resolver: zodResolver(roadTypeSchema),
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
              description: editing.description ?? "",
              active: editing.active,
            },
      );
  }, [editing]); // eslint-disable-line
  return (
    <>
      <ResourceTable<RoadType>
        title="Road Types"
        noun="road type"
        icon={Route}
        description="RIMs’ own road classifications. The pricing engine can price by road type once rules reference it."
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
            header: "Name",
            cell: (r) => <span className="font-medium">{r.name}</span>,
          },
          { key: "code", header: "Code", cell: (r) => r.code },
          {
            key: "desc",
            header: "Description",
            cell: (r) => (
              <span className="text-muted">{r.description || "—"}</span>
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
        title={editing === "new" ? "New road type" : "Edit road type"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="submit" form="road-form" loading={save.isPending}>
              Save road type
            </Button>
          </>
        }
      >
        <form
          id="road-form"
          noValidate
          className="space-y-4"
          onSubmit={f.handleSubmit((v) =>
            save.mutate(
              {
                id: editing !== "new" ? editing?.id : undefined,
                body: { ...v, description: v.description || null },
              },
              { onSuccess: () => setEditing(null) },
            ),
          )}
        >
          <Input
            label="Name"
            error={f.formState.errors.name?.message}
            {...f.register("name")}
          />
          <Input
            label="Code"
            hint="Short unique code used by the pricing engine."
            error={f.formState.errors.code?.message}
            {...f.register("code")}
          />
          <Input label="Description" optional {...f.register("description")} />
          <Checkbox label="Active" {...f.register("active")} />
        </form>
      </Drawer>
    </>
  );
}
