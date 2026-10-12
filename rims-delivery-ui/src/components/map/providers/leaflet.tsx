import { useEffect, useRef } from "react";
import L from "leaflet";
import type { MapCanvasProps } from "../types";

const DEFAULT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const DEFAULT_ATTRIBUTION = "&copy; OpenStreetMap contributors";
const dot = (cls: string) =>
  L.divIcon({
    className: "",
    html: `<div class="map-dot ${cls}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

export default function LeafletCanvas({
  center,
  zoom,
  marker,
  dispatch,
  route,
  interactive = true,
  onPick,
  tileUrl,
  attribution,
  label,
}: MapCanvasProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layers = useRef<{
    marker?: L.Marker;
    dispatch?: L.Marker;
    route?: L.Polyline;
  }>({});
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, {
      center: [center.lat, center.lng],
      zoom,
      zoomControl: interactive,
      dragging: interactive,
      scrollWheelZoom: false,
      attributionControl: true,
    });
    L.tileLayer(tileUrl ?? DEFAULT_TILES, {
      attribution: attribution ?? DEFAULT_ATTRIBUTION,
      maxZoom: 19,
    }).addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => {
      if (interactive) pick.current?.({ lat: e.latlng.lat, lng: e.latlng.lng });
    });
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    map.current = m;
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
      layers.current = {};
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const l = layers.current;
    l.marker?.remove();
    l.marker = undefined;
    if (marker) {
      l.marker = L.marker([marker.lat, marker.lng], {
        icon: dot(""),
        draggable: interactive,
        keyboard: false,
      }).addTo(m);
      l.marker.bindTooltip("Delivery location", { permanent: true, direction: "top", offset: [0, -10], className: "map-label" });
      l.marker.on("dragend", () => {
        const p = l.marker!.getLatLng();
        pick.current?.({ lat: p.lat, lng: p.lng });
      });
    }
    l.dispatch?.remove();
    l.dispatch = undefined;
    if (dispatch)
      l.dispatch = L.marker([dispatch.lat, dispatch.lng], {
        icon: dot("map-dot-depot"),
        title: dispatch.name,
        keyboard: false,
        interactive: false,
      }).addTo(m);
    l.dispatch?.bindTooltip("RIMs dispatch", { permanent: true, direction: "top", offset: [0, -9], className: "map-label map-label-depot" });
    l.route?.remove();
    l.route = undefined;
    if (route && route.length > 1)
      l.route = L.polyline(
        route.map((p) => [p.lat, p.lng] as [number, number]),
        { color: "rgb(12,79,196)", weight: 5, opacity: 0.9 },
      ).addTo(m);

    if (l.route) m.fitBounds(l.route.getBounds(), { padding: [48, 48] });
    else if (marker && dispatch)
      m.fitBounds(L.latLngBounds([[marker.lat, marker.lng], [dispatch.lat, dispatch.lng]]), { padding: [64, 64], maxZoom: 14 });
    else if (marker)
      m.setView([marker.lat, marker.lng], Math.max(m.getZoom(), 13), { animate: true });
    else if (dispatch && !marker) m.setView([center.lat, center.lng], zoom);
  }, [marker, dispatch, route, interactive, center.lat, center.lng, zoom]);

  return (
    <div
      ref={el}
      role="application"
      aria-label={label}
      className="h-full w-full"
    />
  );
}
