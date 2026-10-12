import { forwardRef, type InputHTMLAttributes } from "react";
import { Field, controlClass, type FieldProps } from "./Field";
import { cn } from "@/utils/cn";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & FieldProps
>(function Input({ label, hint, error, optional, className, ...rest }, ref) {
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      optional={optional}
      className={className}
    >
      {({ id, describedBy, invalid }) => (
        <input
          ref={ref}
          id={id}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={controlClass(invalid)}
          {...rest}
        />
      )}
    </Field>
  );
});

export const Checkbox = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & { label: string }
>(function Checkbox({ label, className, ...rest }, ref) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-center gap-2.5 text-body",
        className,
      )}
    >
      <input
        ref={ref}
        type="checkbox"
        className="h-4 w-4 rounded border-line accent-[rgb(var(--brand))]"
        {...rest}
      />
      {label}
    </label>
  );
});
