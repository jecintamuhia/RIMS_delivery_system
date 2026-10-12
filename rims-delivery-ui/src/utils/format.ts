const kes = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });
export const formatKES = (amount: number) => kes.format(amount);
export const formatKm = (km: number) =>
  `${km.toLocaleString("en-KE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
/** Travel time as a person would say it: "25 min", "1 hr 10 min". */
export const formatMinutes = (minutes: number) => {
  if (minutes < 60) return `${Math.max(1, Math.round(minutes))} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest ? `${hours} hr ${rest} min` : `${hours} hr`;
};
export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-KE", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-KE", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
export const formatCoords = (p: { lat: number; lng: number }) =>
  `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}`;
