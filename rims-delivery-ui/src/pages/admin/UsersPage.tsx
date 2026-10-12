import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Plus, Users as UsersIcon } from "lucide-react";
import { usersApi, type ApiError } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Dialog";
import { Input, Checkbox } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/features/auth/AuthProvider";
import { formatDateTime } from "@/utils/format";
import type { Role, StaffUser } from "@/types";

interface UserFormValues {
  fullName: string;
  email: string;
  password?: string;
  role: Role;
  active: boolean;
}

export default function UsersPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user: currentUser } = useAuth();
  const [editingUser, setEditingUser] = useState<StaffUser | "new" | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => usersApi.list({ pageSize: 100 }),
  });

  const form = useForm<UserFormValues>({
    defaultValues: {
      fullName: "",
      email: "",
      password: "",
      role: "editor",
      active: true,
    },
  });

  const openDrawer = (u: StaffUser | "new") => {
    setEditingUser(u);
    if (u === "new") {
      form.reset({
        fullName: "",
        email: "",
        password: "",
        role: "editor",
        active: true,
      });
    } else {
      form.reset({
        fullName: u.name,
        email: u.email,
        password: "",
        role: u.role,
        active: u.active,
      });
    }
  };

  const createMutation = useMutation({
    mutationFn: (v: UserFormValues) =>
      usersApi.create({
        fullName: v.fullName,
        email: v.email,
        password: v.password || "",
        role: v.role,
        active: v.active,
      }),
    onSuccess: (newUser) => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setEditingUser(null);
      toast.success(`Account created for ${newUser.email}`);
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to create account"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, v }: { id: string; v: UserFormValues }) =>
      usersApi.update(id, {
        fullName: v.fullName,
        password: v.password ? v.password : undefined,
        role: v.role,
        active: v.active,
      }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setEditingUser(null);
      toast.success(`Updated account for ${updated.email}`);
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to update account"),
  });

  const onSubmit = (v: UserFormValues) => {
    if (editingUser === "new") {
      createMutation.mutate(v);
    } else if (editingUser) {
      updateMutation.mutate({ id: editingUser.id, v });
    }
  };

  const roleTone = (role: Role) => {
    if (role === "admin") return "ok";
    if (role === "editor") return "neutral";
    return "warn";
  };

  return (
    <>
      <PageHeader
        title="Users & Roles"
        description="Manage staff access and permissions for RIMs delivery pricing operations."
        actions={
          <Button size="sm" onClick={() => openDrawer("new")}>
            <Plus className="h-4 w-4" aria-hidden />
            New Staff Account
          </Button>
        }
      />

      {error ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-72 w-full rounded-lg" />
      ) : (
        <div className="space-y-6">
          <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-sm">
            <div className="border-b border-line px-5 py-4">
              <h3 className="text-h2 font-medium">Staff Accounts</h3>
              <p className="text-small text-muted">
                Admin accounts have full control. Editors can configure destinations and rules. Viewers have read-only access.
              </p>
            </div>
            {!data?.items.length ? (
              <div className="p-8 text-center text-muted">
                <UsersIcon className="mx-auto h-8 w-8 text-muted/60" aria-hidden />
                <p className="mt-2 font-medium">No users found</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-small">
                  <thead className="border-b border-line bg-canvas/40 text-muted">
                    <tr>
                      <th className="px-5 py-3 font-medium">Staff Member</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Last Login</th>
                      <th className="px-5 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.items.map((u) => (
                      <tr key={u.id} className="hover:bg-canvas/30">
                        <td className="px-5 py-4">
                          <p className="font-medium text-ink">{u.name}</p>
                          <p className="text-small text-muted">{u.email}</p>
                        </td>
                        <td className="px-4 py-4">
                          <StatusBadge tone={roleTone(u.role)}>
                            {u.role.toUpperCase()}
                          </StatusBadge>
                        </td>
                        <td className="px-4 py-4">
                          <span
                            className={`inline-flex items-center gap-1.5 text-small font-medium ${
                              u.active ? "text-brand-strong" : "text-muted"
                            }`}
                          >
                            <span
                              className={`h-2 w-2 rounded-full ${
                                u.active ? "bg-brand" : "bg-muted"
                              }`}
                            />
                            {u.active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-small text-muted">
                          {u.lastLoginAt ? formatDateTime(u.lastLoginAt) : "Never"}
                        </td>
                        <td className="px-5 py-4 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openDrawer(u)}
                          >
                            Edit
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* User Drawer */}
      <Drawer
        open={!!editingUser}
        onClose={() => setEditingUser(null)}
        title={
          editingUser === "new"
            ? "Create Staff Account"
            : `Edit Account: ${editingUser?.name}`
        }
        footer={
          <div className="flex justify-end gap-3 w-full">
            <Button variant="secondary" onClick={() => setEditingUser(null)}>
              Cancel
            </Button>
            <Button
              type="submit"
              form="user-form"
              loading={createMutation.isPending || updateMutation.isPending}
            >
              Save Account
            </Button>
          </div>
        }
      >
        <form
          id="user-form"
          className="space-y-4"
          onSubmit={form.handleSubmit(onSubmit)}
        >
          <Input
            label="Full name"
            placeholder="Jane Doe"
            required
            {...form.register("fullName", { required: true })}
          />
          <Input
            label="Email address"
            type="email"
            placeholder="staff@rims.example"
            disabled={editingUser !== "new"}
            required
            {...form.register("email", { required: true })}
          />
          <Input
            label={editingUser === "new" ? "Initial password" : "New password"}
            type="password"
            optional={editingUser !== "new"}
            placeholder={
              editingUser === "new"
                ? "At least 8 characters"
                : "Leave blank to keep current password"
            }
            {...form.register("password", {
              required: editingUser === "new",
              minLength: editingUser === "new" ? 8 : 0,
            })}
          />
          <Select
            label="Role permissions"
            value={form.watch("role")}
            onChange={(e) => form.setValue("role", e.target.value as Role)}
            options={[
              { value: "admin", label: "Admin — Full permissions (Pricing, Relocation, Staff)" },
              { value: "editor", label: "Editor — Destinations & Rule Management" },
              { value: "viewer", label: "Viewer — Read-only access to quotes and logs" },
            ]}
          />
          {editingUser !== "new" && editingUser?.id !== currentUser?.id && (
            <Checkbox
              label="Account active"
              checked={form.watch("active")}
              onChange={(e) => form.setValue("active", e.target.checked)}
            />
          )}
        </form>
      </Drawer>
    </>
  );
}
