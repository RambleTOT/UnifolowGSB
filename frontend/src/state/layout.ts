/**
 * Состояние каркаса, которое запоминается в этом браузере (ТЗ, раздел 4.6).
 *
 * Свёрнутость меню нужна сразу в нескольких местах, поэтому это общий на всё
 * приложение маленький склад, а не состояние одного компонента.
 */

import { useCallback, useSyncExternalStore } from "react";

const COLLAPSED_KEY = "uniflow.sidebarCollapsed";

let collapsed = localStorage.getItem(COLLAPSED_KEY) === "1";
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLayoutState() {
  const value = useSyncExternalStore(
    subscribe,
    () => collapsed,
    () => collapsed,
  );

  const toggleCollapsed = useCallback(() => {
    collapsed = !collapsed;
    localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    emit();
  }, []);

  return { collapsed: value, toggleCollapsed };
}

/** Узкий экран: меню выезжает поверх содержимого, свёрнутого вида у него нет. */
const NARROW_QUERY = "(max-width: 860px)";

export function useNarrowScreen(): boolean {
  return useSyncExternalStore(
    (listener) => {
      const media = window.matchMedia(NARROW_QUERY);
      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    },
    () => window.matchMedia(NARROW_QUERY).matches,
    () => false,
  );
}
