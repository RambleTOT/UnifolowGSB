import { useState } from "react";
import { Link } from "react-router-dom";

import { useMarkNotificationsSeen, useNotifications } from "../../api/queries";
import { label, severityTone } from "../../lib/dictionary";
import { formatFreshness } from "../../lib/format";
import { StatusPill } from "../common/StatusPill";

/**
 * Уведомления: счётчик новых событий и список последних.
 * Критическое событие должно быть замечено из любого раздела, даже если список
 * закрыт (ТЗ, раздел 4.3), поэтому оно показывается отдельной строкой.
 */
export function Notifications({ enabled }: { enabled: boolean }) {
  const [open, setOpen] = useState(false);
  const notifications = useNotifications(enabled);
  const markSeen = useMarkNotificationsSeen();

  const data = notifications.data;
  const unseen = data?.unseen ?? 0;

  const toggle = () => {
    setOpen((value) => {
      if (!value && unseen > 0) markSeen.mutate();
      return !value;
    });
  };

  return (
    <div className="notifications">
      <button
        type="button"
        className="icon-button notifications__button"
        onClick={toggle}
        aria-expanded={open}
        title="Уведомления о новых событиях"
      >
        🔔
        {unseen > 0 && <span className="notifications__badge">{unseen > 99 ? "99+" : unseen}</span>}
      </button>

      {open && (
        <div className="notifications__list">
          <div className="notifications__head">
            <strong>Последние события</strong>
            <Link to="/events" onClick={() => setOpen(false)}>
              Весь журнал
            </Link>
          </div>

          {data && data.events.length > 0 ? (
            data.events.map((event) => (
              <Link
                key={event.id}
                to={`/events/${event.id}`}
                className="notifications__item"
                onClick={() => setOpen(false)}
              >
                <StatusPill
                  status={event.severity}
                  dictionary="severity"
                  tone={severityTone(event.severity)}
                />
                <span className="notifications__title">{event.title}</span>
                <small>
                  {formatFreshness(event.startedAt)} · {label("eventStatus", event.status)}
                </small>
              </Link>
            ))
          ) : (
            <p className="muted notifications__empty">
              Событий пока нет. Они появятся, когда очередь, поток или источник выйдут за пороги.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** Отдельная строка для критического события: его нельзя пропустить. */
export function CriticalBanner({ enabled }: { enabled: boolean }) {
  const notifications = useNotifications(enabled);
  const critical = notifications.data?.critical?.[0];
  if (!critical) return null;

  return (
    <div className="critical-banner" role="alert">
      <strong>Критическое событие:</strong> {critical.title}
      <Link to={`/events/${critical.id}`}>Разобрать</Link>
    </div>
  );
}
