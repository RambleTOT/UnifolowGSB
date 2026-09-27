import type { ReactNode } from "react";

interface FieldProps {
  label: string;
  /** На что влияет параметр: у каждого поля есть пояснение (ТЗ, 5.8). */
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  htmlFor?: string;
}

export function Field({ label, hint, error, required, children, htmlFor }: FieldProps) {
  return (
    <label className={`field ${error ? "field--error" : ""}`} htmlFor={htmlFor}>
      <span className="field__label">
        {label}
        {required && <span className="field__required" aria-hidden="true"> *</span>}
      </span>
      {children}
      {hint && !error && <span className="field__hint">{hint}</span>}
      {error && <span className="field__error" role="alert">{error}</span>}
    </label>
  );
}
