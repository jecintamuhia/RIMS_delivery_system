export const env = {
  apiBase: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  useMocks: import.meta.env.VITE_USE_MOCKS === "true",
};
