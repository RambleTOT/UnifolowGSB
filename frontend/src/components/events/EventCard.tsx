import { Link } from "react-router-dom";

import type { EventView } from "../../api/types";
import { label, severityTone } from "../../lib/dictionary";
import { formatDateTime, formatDurationSeconds, formatNumber } from "../../lib/format";
import { StatusPill } from "../common/StatusPill";

interface EventCardProps {
  event: EventView;
  compact?: boolean;
}

/** Событие выглядит одинаково всюду: на Главной, в аналитике и в журнале. */
export function EventCard({ event, compact = false }: EventCardProps) {
  return (
    <article className={`event ${compact ? "event--compact" : ""} event--${event.severity}`}>
      <div className="event__head">
        <StatusPill
          status={event.severity}
          dictionary="severity"
          tone={severityTone(event.severity)}
        />
        {event.ongoing ? (
          <span className="event__ongoing">Идёт сейчас</span>
        ) : (
          <span className="muted">Завершилось · {formatDurationSeconds(event.durationSeconds)}</span>
        )}
        <StatusPill
          status={event.status}
          dictionary="eventStatus"
          tone={event.status === "resolved" ? "ok" : event.status === "investigating" ? "accent" : "warn"}
        />
      </div>

      <Link className="event__title" to={`/events/${event.id}`}>
        {event.title}
      </Link>
      {!compact && <p className="event__text">{event.description}</p>}

      <div className="event__meta">
        <span>{formatDateTime(event.startedAt)}</span>
        <Link to={`/monitor?source=${event.sourceId}`}>{event.sourceName}</Link>
        {event.sourceDeleted && <span className="muted">источник удалён</span>}
        {event.type !== "camera_drop" && (
          <span className="tabular">
            {formatNumber(event.peakValue)} / {formatNumber(event.threshold)}
            {event.exceedPercent !== null && ` · превышение ${event.exceedPercent} %`}
          </span>
        )}
        <span className="muted">{label("eventType", event.type)}</span>
      </div>
    </article>
  );
}
