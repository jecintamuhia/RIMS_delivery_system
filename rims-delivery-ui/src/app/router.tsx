import { lazy, Suspense } from "react";
import { createBrowserRouter, Outlet } from "react-router-dom";
import { CustomerLayout } from "@/layouts/CustomerLayout";
import LocatePage from "@/pages/customer/LocatePage";
import QuotePage from "@/pages/customer/QuotePage";
import NotFoundPage from "@/pages/NotFoundPage";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { LoadingState } from "@/components/ui/LoadingState";

// The admin application is code-split: customers never download it.
const l = <T,>(f: () => Promise<{ default: T }>) => lazy(f as never);
const AdminLayout = lazy(() =>
  import("@/layouts/AdminLayout").then((m) => ({ default: m.AdminLayout })),
);
const Login = l(() => import("@/pages/admin/LoginPage"));
const Dashboard = l(() => import("@/pages/admin/DashboardPage"));
const Quotes = l(() => import("@/pages/admin/QuotesPage"));
const QuoteDetail = l(() => import("@/pages/admin/QuoteDetailPage"));
const Destinations = l(() => import("@/pages/admin/DestinationsPage"));
const Rules = l(() => import("@/pages/admin/PricingRulesPage"));
const PricingVersions = l(() => import("@/pages/admin/PricingVersionsPage"));
const DynamicPricing = l(() => import("@/pages/admin/DynamicPricingPage"));
const Roads = l(() => import("@/pages/admin/RoadTypesPage"));
const Vehicles = l(() => import("@/pages/admin/VehiclesPage"));
const Users = l(() => import("@/pages/admin/UsersPage"));
const Audit = l(() => import("@/pages/admin/AuditLogPage"));
const Settings = l(() => import("@/pages/admin/SettingsPage"));

const AdminRoot = () => (
  <AuthProvider>
    <Suspense fallback={<LoadingState className="min-h-dvh" />}>
      <Outlet />
    </Suspense>
  </AuthProvider>
);

export const router = createBrowserRouter([
  {
    element: <CustomerLayout />,
    children: [
      { path: "/", element: <LocatePage /> },
      { path: "/quote/:id", element: <QuotePage /> },
    ],
  },
  {
    path: "/admin",
    element: <AdminRoot />,
    children: [
      { path: "login", element: <Login /> },
      {
        element: <RequireAuth />,
        children: [
          {
            element: <AdminLayout />,
            children: [
              { index: true, element: <Dashboard /> },
              { path: "quotes", element: <Quotes /> },
              { path: "quotes/:id", element: <QuoteDetail /> },
              { path: "destinations", element: <Destinations /> },
              { path: "pricing-versions", element: <PricingVersions /> },
              { path: "dynamic-pricing", element: <DynamicPricing /> },
              { path: "pricing-rules", element: <Rules /> },
              { path: "road-types", element: <Roads /> },
              { path: "vehicles", element: <Vehicles /> },
              { path: "users", element: <Users /> },
              { path: "audit-log", element: <Audit /> },
              { path: "settings", element: <Settings /> },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
