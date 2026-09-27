import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useDemoStatus, useLogout, useUpdateProfile } from "../../api/queries";
import type { DataStatus } from "../../api/types";
import { label } from "../../lib/dictionary";
import { useFilters, validateRange } from "../../state/filters";
import { useSession } from "../../state/session";
import { Button } from "../common/Button";
import { DataStatusBadge } from "./DataStatusBadge";
import { Notifications } from "./Notifications";
import { Search } from "./Search";

/** Разделы, на которые глобальные фильтры не влияют (ТЗ, раздел 4.4). */
const WITHOUT_FILTERS = ["/sources", "/settings", "/reports"];

interface TopbarProps {
  /** Открыть меню на узком экране. */
  onMenu: () => void;
  dataStatus: DataStatus | null;
  disconnected: boolean;
  staleSince: string | null;
}

export function Topbar({ onMenu, dataStatus, disconnected, staleSince }: TopbarProps) {
  const { filters, update } = useFilters();
  const { user, liveUpdates, setLiveUpdates } = useSession();
  const logout = useLogout();
  const updateProfile = useUpdateProfile();
  const navigate = useNavigate();
  const location = useLocation();
  const [userMenu, setUserMenu] = useState(false);

  const filtersApply = !WITHOUT_FILTERS.some((path) => location.pathname.startsWith(path));
  const rangeError = filters.period === "custom" ? validateRange(filters.from, filters.to) : null;
  const demo = user?.dataset === "demo";
  const demoStatus = useDemoStatus(demo);

  return (
    <header className="topbar">
      <button type="button" className="icon-button topbar__menu" onClick={onMenu} aria-label="Открыть меню">
        ☰
      </button>
      <Search />

      <div className="topbar__filters">
        {filtersApply ? (
          <>
            <div className="segmented" role="group" aria-label="Период данных">
              {(["hour", "day", "week", "month", "custom"] as const).map((period) => (
                <button
                  key={period}
                  type="button"
                  className={`segmented__item ${filters.period === period ? "segmented__item--active" : ""}`}
                  onClick={() => update({ period })}
                >
                  {label("period", period)}
                </button>
              ))}
            </div>

            {filters.period === "custom" && (
              <div className="topbar__range">
                <input
                  type="date"
                  value={filters.from ?? ""}
                  onChange={(event) => update({ from: event.target.value })}
                  aria-label="Дата от"
                />
                <span aria-hidden="true">—</span>
                <input
                  type="date"
                  value={filters.to ?? ""}
                  onChange={(event) => update({ to: event.target.value })}
                  aria-label="Дата до"
                />
                {rangeError && <span className="topbar__range-error">{rangeError}</span>}
              </div>
            )}

            <div className="segmented" role="group" aria-label="Контур">
              {(["all", "canteen", "gate"] as const).map((scope) => (
                <button
                  key={scope}
                  type="button"
                  className={`segmented__item ${filters.scope === scope ? "segmented__item--active" : ""}`}
                  onClick={() => update({ scope })}
                >
                  {label("scope", scope)}
                </button>
              ))}
            </div>
          </>
        ) : (
          <span className="topbar__no-filters">
            Период и контур на этот раздел не влияют
          </span>
        )}
      </div>

      <div className="topbar__tools">
        {demo && (
          <button
            type="button"
            className="demo-badge"
            onClick={() => updateProfile.mutate({ dataset: "real" })}
            title="Выключить демо-режим и вернуться к реальным данным"
            disabled={demoStatus.data?.running}
          >
            {demoStatus.data?.running
              ? "Собираем демо-историю…"
              : "Демо-данные · выключить"}
          </button>
        )}

        <DataStatusBadge
          status={dataStatus}
          disconnected={disconnected}
          paused={!liveUpdates}
          staleSince={staleSince}
        />

        <Notifications enabled={Boolean(user)} />

        <button
          type="button"
          className="icon-button"
          onClick={() => setLiveUpdates(!liveUpdates)}
          title={liveUpdates ? "Выключить обновление в реальном времени" : "Включить обновление в реальном времени"}
        >
          {liveUpdates ? "⏸" : "▶"}
        </button>

        <div className="user-menu">
          <button
            type="button"
            className="user-menu__button"
            onClick={() => setUserMenu((value) => !value)}
            aria-expanded={userMenu}
          >
            <span className="user-menu__avatar" aria-hidden="true">
              {(user?.displayName ?? "?").slice(0, 1)}
            </span>
            <span className="user-menu__name">{user?.displayName}</span>
          </button>

          {userMenu && (
            <div className="user-menu__list">
              <div className="user-menu__info">
                <strong>{user?.displayName}</strong>
                <span>{user?.profileTitle}</span>
              </div>
              <Button
                variant="ghost"
                onClick={() => {
                  setUserMenu(false);
                  navigate("/settings");
                }}
              >
                Настройки
              </Button>
              <Button
                variant="ghost"
                onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
                loading={logout.isPending}
              >
                Выйти
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
