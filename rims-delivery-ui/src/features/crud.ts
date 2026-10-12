import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ListParams } from "@/services/api/crud";
import type { Page } from "@/types";
import { useToast } from "@/components/ui/Toast";
import type { ApiError } from "@/services/api";

interface Api<T, I> {
  list: (p?: ListParams) => Promise<Page<T>>;
  create: (b: I) => Promise<T>;
  update: (id: string, b: Partial<I>) => Promise<T>;
}

/** Shared list + save hooks for admin resources. */
export function useResource<T extends { id: string }, I>(
  key: string,
  api: Api<T, I>,
  params?: ListParams,
  noun = "Record",
) {
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({
    queryKey: [key, params],
    queryFn: () => api.list(params),
  });
  const save = useMutation({
    mutationFn: ({ id, body }: { id?: string; body: I }) =>
      id ? api.update(id, body) : api.create(body),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: [key] });
      toast.success(v.id ? `${noun} saved` : `${noun} created`);
    },
    onError: (e) =>
      toast.error(
        (e as ApiError).message || `Couldn’t save ${noun.toLowerCase()}`,
      ),
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      api.update(id, { active } as unknown as Partial<I>),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: [key] });
      toast.success(v.active ? `${noun} activated` : `${noun} deactivated`);
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Couldn’t update status"),
  });
  return { list, save, toggle };
}

/** All records for use in select inputs. */
export function useOptions<T extends { id: string }>(
  key: string,
  api: { list: (p?: ListParams) => Promise<Page<T>> },
) {
  return useQuery({
    queryKey: [key, "options"],
    queryFn: () => api.list({ pageSize: 500 }),
    staleTime: 60_000,
  });
}
