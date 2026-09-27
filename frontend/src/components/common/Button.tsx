import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  /** Почему кнопка недоступна: заблокированный элемент всегда объясняет причину. */
  disabledReason?: string;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    disabledReason,
    disabled,
    children,
    className = "",
    ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading;
  return (
    <button
      {...rest}
      ref={ref}
      className={`btn btn--${variant} btn--${size} ${className}`}
      disabled={isDisabled}
      title={isDisabled && disabledReason ? disabledReason : rest.title}
      aria-disabled={isDisabled}
    >
      {loading && <span className="btn__spinner" aria-hidden="true" />}
      {children}
    </button>
  );
});
