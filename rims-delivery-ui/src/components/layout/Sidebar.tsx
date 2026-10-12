import { NavLink } from "react-router-dom";
import {
  Activity,
  FileText,
  Gauge,
  Layers,
  LayoutDashboard,
  MapPin,
  Receipt,
  Route,
  Settings,
  Tag,
  Truck,
  Users,
} from "lucide-react";
import { Brand } from "@/layouts/CustomerLayout";

export const adminNav = [
  { to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/quotes", label: "Quotes", icon: Receipt },
  { to: "/admin/destinations", label: "Destinations", icon: MapPin },
  { to: "/admin/pricing-versions", label: "Pricing Versions", icon: Layers },
  { to: "/admin/pricing-rules", label: "Pricing Rules", icon: Tag },
  { to: "/admin/dynamic-pricing", label: "Distance Pricing", icon: Gauge },
  { to: "/admin/road-types", label: "Road Types", icon: Route },
  { to: "/admin/vehicles", label: "Vehicles", icon: Truck },
  { to: "/admin/users", label: "Users & Roles", icon: Users },
  { to: "/admin/audit-log", label: "Audit Log", icon: FileText },
  { to: "/admin/settings", label: "Dispatch & Settings", icon: Settings },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center border-b border-line px-4">
        <Brand />
      </div>
      <nav
        aria-label="Admin"
        className="flex-1 space-y-0.5 overflow-y-auto p-3"
      >
        {adminNav.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded px-3 py-2 text-body transition-colors ${isActive ? "bg-brand-soft font-medium text-brand-strong" : "text-muted hover:bg-ink/5 hover:text-ink"}`
            }
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
      <p className="flex items-center gap-1.5 border-t border-line px-4 py-3 text-small text-muted">
        <Activity className="h-3.5 w-3.5" aria-hidden />
        Pricing engine runs on the server
      </p>
    </div>
  );
}
