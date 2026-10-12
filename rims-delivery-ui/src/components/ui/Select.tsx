import { forwardRef, type SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";
import { Field, controlClass, type FieldProps } from "./Field";

export interface Option {
  value: string;
  label: string;
}
export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement> &
    FieldProps & { options: Option[]; placeholder?: string }
>(function Select(
  { label, hint, error, optional, className, options, placeholder, ...rest },
  ref,
) {
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      optional={optional}
      className={className}
    >
      {({ id, describedBy, invalid }) => (
        <div className="relative">
          <select
            ref={ref}
            id={id}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className={`${controlClass(invalid)} appearance-none pr-9`}
            {...rest}
          >
            {placeholder !== undefined && (
              <option value="">{placeholder}</option>
            )}
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <ChevronDown
            className="pointer-events-none absolute right-3 top-3 h-4 w-4 text-muted"
            aria-hidden
          />
        </div>
      )}
    </Field>
  );
});
