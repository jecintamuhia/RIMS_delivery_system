import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/utils/cn";

type Variant = "modal" | "right" | "left";
interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  variant?: Variant;
  children: ReactNode;
  footer?: ReactNode;
  hideTitle?: boolean;
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  variant = "modal",
  children,
  footer,
  hideTitle,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cn(
        "dlg",
        variant === "modal"
          ? "dlg-modal"
          : variant === "right"
            ? "dlg-right"
            : "dlg-left",
      )}
    >
      {open && (
        <div className="flex max-h-dvh flex-col">
          <header
            className={cn(
              "flex items-start justify-between gap-4 border-b border-line px-5 py-4",
              hideTitle && "sr-only",
            )}
          >
            <div>
              <h2 id={titleId} className="text-h2">
                {title}
              </h2>
              {description && (
                <p className="mt-0.5 text-small text-muted">{description}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="-mr-1.5 rounded p-1.5 text-muted hover:bg-ink/5"
            >
              <X className="h-4 w-4" />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
            {children}
          </div>
          {footer && (
            <footer className="flex justify-end gap-2.5 border-t border-line bg-canvas/60 px-5 py-3.5">
              {footer}
            </footer>
          )}
        </div>
      )}
    </dialog>
  );
}
export const Modal = (p: Omit<Props, "variant">) => (
  <Dialog {...p} variant="modal" />
);
export const Drawer = (
  p: Omit<Props, "variant"> & { side?: "right" | "left" },
) => <Dialog {...p} variant={p.side ?? "right"} />;
