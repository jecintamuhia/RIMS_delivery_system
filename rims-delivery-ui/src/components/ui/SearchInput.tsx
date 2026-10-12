import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Loader2, Search, X } from "lucide-react";
import { cn } from "@/utils/cn";

export interface SearchResult {
  id: string;
  label: string;
  secondary?: string;
}
interface Props<T extends SearchResult> {
  label: string;
  value: string;
  onChange: (v: string) => void;
  results?: T[];
  loading?: boolean;
  onSelect?: (r: T) => void;
  placeholder?: string;
  empty?: ReactNode;
  className?: string;
  hideLabel?: boolean;
  /** Increment to pull focus into the field (e.g. after the intro closes). */
  focusSignal?: number;
}

/** Combobox following the ARIA 1.2 pattern: arrow keys move, Enter selects, Escape closes. */
export function SearchInput<T extends SearchResult>({
  label,
  value,
  onChange,
  results,
  loading,
  onSelect,
  placeholder,
  empty,
  className,
  hideLabel,
  focusSignal,
}: Props<T>) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focusSignal) ref.current?.focus();
  }, [focusSignal]);

  const showList =
    open && value.trim().length >= 2 && (loading || results !== undefined);
  const pick = (r: T) => {
    setOpen(false);
    setActive(-1);
    onSelect?.(r);
  };

  return (
    <div className={cn("relative", className)}>
      <label
        htmlFor={id}
        className={
          hideLabel ? "sr-only" : "mb-1.5 block text-small font-medium"
        }
      >
        {label}
      </label>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          aria-hidden
        />
        <input
          ref={ref}
          id={id}
          role="combobox"
          aria-expanded={showList}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={
            active >= 0 ? `${id}-opt-${active}` : undefined
          }
          autoComplete="off"
          value={value}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            const n = results?.length ?? 0;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setActive((a) => (n ? (a + 1) % n : -1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => (n ? (a - 1 + n) % n : -1));
            } else if (e.key === "Enter" && active >= 0 && results?.[active]) {
              e.preventDefault();
              pick(results[active]);
            } else if (e.key === "Escape") setOpen(false);
          }}
          className="h-12 w-full rounded-md border border-line bg-surface pl-10 pr-10 text-body shadow-sm transition-colors placeholder:text-muted/70 hover:border-ink/30"
        />
        {loading ? (
          <Loader2
            className="absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted"
            aria-label="Searching"
          />
        ) : (
          value && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                onChange("");
                ref.current?.focus();
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-muted hover:bg-ink/5"
            >
              <X className="h-4 w-4" />
            </button>
          )
        )}
      </div>
      {showList && (
        <ul
          id={`${id}-list`}
          role="listbox"
          aria-label={`${label} results`}
          className="absolute z-20 mt-1.5 max-h-72 w-full overflow-auto rounded-md border border-line bg-surface py-1 shadow-pop"
        >
          {results?.map((r, i) => (
            <li
              key={r.id}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(r)}
              onMouseEnter={() => setActive(i)}
              className={cn(
                "cursor-pointer px-3.5 py-2.5",
                i === active && "bg-brand-soft",
              )}
            >
              <div className="font-medium">{r.label}</div>
              {r.secondary && (
                <div className="text-small text-muted">{r.secondary}</div>
              )}
            </li>
          ))}
          {!loading && results?.length === 0 && (
            <li
              role="presentation"
              className="px-3.5 py-3 text-small text-muted"
            >
              {empty ??
                "No places found. Try a nearby town or pin the spot on the map."}
            </li>
          )}
          {loading && !results?.length && (
            <li
              role="presentation"
              className="px-3.5 py-3 text-small text-muted"
            >
              Searching…
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
