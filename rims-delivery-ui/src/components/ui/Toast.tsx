import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, XCircle, X } from "lucide-react";

interface ToastItem {
  id: number;
  kind: "success" | "error";
  message: string;
}
const Ctx = createContext<{
  success: (m: string) => void;
  error: (m: string) => void;
} | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback(
    (id: number) => setItems((s) => s.filter((t) => t.id !== id)),
    [],
  );
  const push = useCallback(
    (kind: ToastItem["kind"], message: string) => {
      const id = Date.now() + Math.random();
      setItems((s) => [...s, { id, kind, message }]);
      setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
  );
  const api = useMemo(
    () => ({
      success: (m: string) => push("success", m),
      error: (m: string) => push("error", m),
    }),
    [push],
  );
  return (
    <Ctx.Provider value={api}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex max-w-md items-center gap-2.5 rounded-md bg-ink px-4 py-3 text-small text-white shadow-pop"
          >
            {t.kind === "success" ? (
              <CheckCircle2
                className="h-4 w-4 shrink-0 text-brand-soft"
                aria-hidden
              />
            ) : (
              <XCircle
                className="h-4 w-4 shrink-0 text-danger-soft"
                aria-hidden
              />
            )}
            <span>{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
              className="-mr-1 ml-1 rounded p-1 hover:bg-white/10"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
export const useToast = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("ToastProvider missing");
  return c;
};
