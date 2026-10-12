import { LogOut, Menu } from "lucide-react";
import { useAuth } from "@/features/auth/AuthProvider";
import { Button } from "@/components/ui/Button";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { user, signOut } = useAuth();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-surface/95 px-4 backdrop-blur lg:px-8">
      <button
        onClick={onMenu}
        aria-label="Open navigation"
        className="-ml-2 rounded p-2 text-muted hover:bg-ink/5 lg:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>
      <div className="hidden lg:block" />
      <div className="flex items-center gap-3">
        <div className="text-right text-small leading-tight">
          <p className="font-medium">{user?.name}</p>
          <p className="capitalize text-muted">{user?.role}</p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => signOut()}
          aria-label="Sign out"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">Sign out</span>
        </Button>
      </div>
    </header>
  );
}
