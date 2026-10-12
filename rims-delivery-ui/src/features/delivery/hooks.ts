import { useQuery } from "@tanstack/react-query";
import { ApiError, deliveryApi, quotesApi } from "@/services/api";
import { useDebounced } from "@/utils/useDebounced";
import type { LatLng } from "@/types";

export const usePublicConfig = () =>
  useQuery({
    queryKey: ["public-config"],
    queryFn: deliveryApi.config,
    staleTime: Infinity,
  });

export function useLocationSearch(text: string) {
  const q = useDebounced(text.trim(), 300);
  return useQuery({
    queryKey: ["location-search", q],
    queryFn: ({ signal }) => deliveryApi.searchLocations(q, signal),
    enabled: q.length >= 2,
    staleTime: 60_000,
    // keep the list visible while the next query loads
    placeholderData: (prev) => prev,
  });
}

/** How far the pinned point is from RIMs' dispatch, before a quote exists.
 *  Debounced so dragging the pin does not hammer the routing provider, and it
 *  never returns a price - pricing happens once, in the quote pipeline. */
export function useRoutePreview(position: LatLng | null) {
  const debounced = useDebounced(position, 350);
  return useQuery({
    queryKey: ["route-preview", debounced?.lat, debounced?.lng],
    queryFn: ({ signal }) => deliveryApi.routePreview(debounced!, signal),
    enabled: debounced != null,
    staleTime: 60_000,
    retry: 1,
  });
}

/** Polls while the backend reports `processing`; steps come straight from the API. */
export function useQuote(id: string) {
  return useQuery({
    queryKey: ["quote", id],
    queryFn: () => quotesApi.get(id),
    refetchInterval: (q) =>
      q.state.data?.status === "processing" ? 1000 : false,
    retry: (n, e) =>
      !(
        e instanceof ApiError &&
        (e.code === "NOT_FOUND" || e.status === 404)
      ) && n < 2,
  });
}
