import { NavLink } from "react-router-dom";

import { useEvents } from "../../api/queries";
import { useLayoutState } from "../../state/layout";
import { useSession } from "../../state/session";

interface NavItem {
  to: string;
  label: string;
  /** Короткая подпись для свёрнутого меню: разделы должны остаться различимы. */
  short: string;
  badge?: number;
}

const NAVIGATION: NavItem[] = [
  { to: "/", label: "Главная", short: "Гл" },
  { to: "/monitor", label: "Оперативный мониторинг", short: "Мон" },
  { to: "/queues", label: "Анализ очередей", short: "Оч" },
  { to: "/checkpoints", label: "Анализ КПП", short: "КПП" },
  { to: "/events", label: "История и события", short: "Соб" },
  { to: "/reports", label: "Отчёты", short: "Отч" },
  { to: "/sources", label: "Источники видео", short: "Ист" },
  { to: "/settings", label: "Настройки", short: "Наст" },
];

interface SidebarProps {
  collapsed: boolean;
  /** Меню спрятано за краем экрана: его ссылки не должны ловить фокус. */
  hidden: boolean;
  onNavigate: () => void;
}

export function Sidebar({ collapsed, hidden, onNavigate }: SidebarProps) {
  const { toggleCollapsed } = useLayoutState();
  const { user } = useSession();
  // Счётчик неразобранных событий высокого и критического приоритета.
  const events = useEvents(
    { period: "month", scope: "all", pageSize: 5 },
    user?.dataset ?? "real",
  );
  const attention = events.data?.attentionCount ?? 0;

  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`} inert={hidden}>
      <div className="sidebar__brand">
        <span className="sidebar__mark" aria-hidden="true">
          UF
        </span>
        {!collapsed && (
          <span className="sidebar__name">
            <strong>UniFlow</strong>
            <small>Analytics</small>
          </span>
        )}
      </div>

      <nav className="sidebar__nav" aria-label="Разделы">
        {NAVIGATION.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) => `sidebar__link ${isActive ? "sidebar__link--active" : ""}`}
            title={collapsed ? item.label : undefined}
            onClick={onNavigate}
          >
            <span className="sidebar__short" aria-hidden="true">
              {item.short}
            </span>
            {!collapsed && <span className="sidebar__label">{item.label}</span>}
            {item.to === "/events" && attention > 0 && (
              <span className="sidebar__badge" title="Неразобранные события высокого и критического приоритета">
                {attention}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <button type="button" className="sidebar__collapse" onClick={toggleCollapsed}>
        {collapsed ? "»" : "« Свернуть меню"}
      </button>
    </aside>
  );
}
