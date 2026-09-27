import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
  /** Следующий шаг: у пустого состояния не должно быть тупика (ТЗ, 1.6). */
  action?: ReactNode;
  tone?: "neutral" | "warn" | "danger";
}

export function EmptyState({ title, description, action, tone = "neutral" }: EmptyStateProps) {
  return (
    <div className={`empty empty--${tone}`}>
      <div className="empty__title">{title}</div>
      {description && <p className="empty__text">{description}</p>}
      {action && <div className="empty__action">{action}</div>}
    </div>
  );
}
