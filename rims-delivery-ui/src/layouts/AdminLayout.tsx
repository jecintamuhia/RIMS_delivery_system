import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { CinematicIntro } from "@/components/intro/CinematicIntro";
import { useIdleSplash } from "@/components/intro/useIntro";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";
import { Drawer, Modal } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/features/auth/AuthProvider";
import { env } from "@/config/env";

export function AdminLayout() {
  const [menu, setMenu] = useState(false);
  const { sessionExpired, signOut } = useAuth();
  const idle = useIdleSplash();
  const nav = useNavigate();
  const loc = useLocation();
  return (
    <div className="min-h-dvh">
      <div
        className="min-h-dvh lg:grid lg:grid-cols-[232px_1fr]"
        inert={idle.visible ? true : undefined}
      >
        <a
          href="#admin-main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <aside className="sticky top-0 hidden h-dvh border-r border-line bg-surface lg:block">
          <Sidebar />
        </aside>
        <Drawer
          side="left"
          open={menu}
          onClose={() => setMenu(false)}
          title="Navigation"
          hideTitle
        >
          <div className="-mx-5 -my-5 h-dvh">
            <Sidebar onNavigate={() => setMenu(false)} />
          </div>
        </Drawer>
        <div className="min-w-0">
          <Topbar onMenu={() => setMenu(true)} />
          {env.useMocks && (
            <p className="bg-warn-soft px-4 py-1.5 text-center text-small text-warn lg:px-8">
              <strong>Mock API.</strong> Data shown is test data. Sign in with
              any email and password.
            </p>
          )}
          <main
            id="admin-main"
            className="mx-auto max-w-[1200px] px-4 py-6 lg:px-8 lg:py-8"
          >
            <Outlet />
          </main>
        </div>
        <Modal
          open={sessionExpired}
          onClose={() => {}}
          title="Your session has expired"
          footer={
            <Button
              onClick={async () => {
                await signOut();
                nav("/admin/login", {
                  state: { from: loc.pathname + loc.search },
                });
              }}
            >
              Sign in again
            </Button>
          }
        >
          <p className="text-muted">
            For security you were signed out. Sign in again to carry on.
            Nothing you were viewing has been lost.
          </p>
        </Modal>
      </div>
      {idle.visible && <CinematicIntro onDone={() => idle.dismiss()} />}
    </div>
  );
}
