import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { useSystemPulse } from "../../api/live";
import { formatTime } from "../../lib/format";
import { useLayoutState, useNarrowScreen } from "../../state/layout";
import { useSession } from "../../state/session";
import { CriticalBanner } from "./Notifications";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell() {
  const { collapsed } = useLayoutState();
  const { liveUpdates, user } = useSession();
  const pulse = useSystemPulse(liveUpdates);

  const disconnected = liveUpdates && pulse.link === "reconnecting";

  // На узком экране меню выезжает поверх по кнопке; свёрнутый вид — только на широком.
  const narrow = useNarrowScreen();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuShown = narrow && menuOpen;
  const shellCollapsed = collapsed && !narrow;

  useEffect(() => {
    if (!menuShown) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuShown]);

  return (
    <div className={`shell ${shellCollapsed ? "shell--collapsed" : ""} ${menuShown ? "shell--menu" : ""}`}>
      <Sidebar
        collapsed={shellCollapsed}
        hidden={narrow && !menuOpen}
        onNavigate={() => setMenuOpen(false)}
      />
      <div className="shell__backdrop" onClick={() => setMenuOpen(false)} aria-hidden="true" />
      <div className="shell__main">
        <Topbar
          onMenu={() => setMenuOpen(true)}
          dataStatus={pulse.data?.dataStatus ?? null}
          disconnected={disconnected}
          staleSince={pulse.data ? formatTime(pulse.data.at) : null}
        />
        <CriticalBanner enabled={Boolean(user)} />
        {disconnected && (
          <div className="shell__offline" role="status">
            Нет связи с сервером. Значения на экране получены
            {pulse.data ? ` в ${formatTime(pulse.data.at)}` : " ранее"}; переподключение
            {pulse.nextRetrySeconds ? ` через ${pulse.nextRetrySeconds} с` : "…"} (попытка {pulse.attempt}).
          </div>
        )}
        <main className="shell__content">
          <Outlet context={{ pulse }} />
        </main>
      </div>
    </div>
  );
}
