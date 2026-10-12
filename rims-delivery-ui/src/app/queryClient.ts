import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/services/api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (n, e) =>
        e instanceof ApiError && (e.code === "NETWORK" || e.code === "SERVER")
          ? n < 2
          : false,
    },
  },
});
