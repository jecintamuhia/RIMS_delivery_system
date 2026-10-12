import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/hanken-grotesk";
import "./index.css";
import { queryClient } from "@/app/queryClient";
import { router } from "@/app/router";
import { ToastProvider } from "@/components/ui/Toast";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
