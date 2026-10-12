import { api } from "./client";
import type { Page } from "@/types";

export type ListParams = Record<
  string,
  string | number | boolean | null | undefined
>;

/** Generic admin resource client. Records are deactivated, not deleted, to preserve the audit trail. */
export function createCrudApi<T extends { id: string }, I>(path: string) {
  return {
    list: (params?: ListParams) => api.get<Page<T>>(path, params),
    get: (id: string) => api.get<T>(`${path}/${id}`),
    create: (body: I) => api.post<T>(path, body),
    update: (id: string, body: Partial<I>) =>
      api.patch<T>(`${path}/${id}`, body),
  };
}
