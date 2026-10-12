import type { LatLng } from "@/types";


export interface MapCanvasProps {
  center: LatLng;
  zoom: number;
  marker?: LatLng | null;
  dispatch?: (LatLng & { name: string }) | null;
  route?: LatLng[] | null;
  interactive?: boolean;
  onPick?: (p: LatLng) => void;
  tileUrl?: string;
  attribution?: string;
  label: string;
}
