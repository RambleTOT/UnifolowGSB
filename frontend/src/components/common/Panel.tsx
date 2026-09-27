import type { ReactNode } from "react";

import { formatFreshness } from "../../lib/format";

interface PanelProps {
  title?: ReactNode;
  /** За какой период и с каким шагом построен блок. */
  meta?: ReactNode;
  updatedAt?: string | null;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}

export function Panel({
  title,
  meta,
  updatedAt,
  actions,
  children,
  className = "",
  padded = true,
}: PanelProps) {
  const hasHeader = title || meta || actions || updatedAt;
  return (
    <section className={`panel ${className}`}>
      {hasHeader && (
        <header className="panel__head">
          <div className="panel__titles">
            {title && <h2 className="panel__title">{title}</h2>}
            {(meta || updatedAt) && (
              <div className="panel__meta">
                {meta}
                {updatedAt && (
                  <span title={updatedAt}>обновлено {formatFreshness(updatedAt)}</span>
                )}
              </div>
            )}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      <div className={padded ? "panel__body" : "panel__body panel__body--flush"}>{children}</div>
    </section>
  );
}
