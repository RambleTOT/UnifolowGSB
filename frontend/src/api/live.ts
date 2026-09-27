/**
 * Живая часть: метаданные кадра и пульс сервера.
 *
 * Связь может пропасть, и это отдельное состояние: значения на экране
 * помечаются устаревшими, а переподключение идёт с нарастающей паузой
 * (ТЗ, раздел 4.3 и 6.9).
 */

import { useEffect, useMemo, useState } from "react";

import { websocketUrl } from "./client";
import type { LiveMessage, SystemPulse } from "./types";

export type LinkState = "connecting" | "live" | "reconnecting" | "closed";

interface Connection<T> {
  data: T | null;
  link: LinkState;
  attempt: number;
  nextRetrySeconds: number;
  receivedAt: number | null;
}

const RETRY_STEPS_MS = [1000, 2000, 5000, 10000, 20000];

function useSocket<T>(path: string | null, enabled = true): Connection<T> {
  const [state, setState] = useState<Connection<T>>({
    data: null,
    link: "connecting",
    attempt: 0,
    nextRetrySeconds: 0,
    receivedAt: null,
  });

  useEffect(() => {
    if (!path || !enabled) {
      setState((previous) => ({ ...previous, link: "closed" }));
      return;
    }

    // Всё состояние подключения — своё у каждого запуска эффекта. Раньше флаг
    // «закрыто» был общим: закрытое подключение сообщало о закрытии уже после
    // того, как новое сбросило флаг, решало, что связь оборвалась, и
    // переподключалось к старому источнику. В просмотр тогда шли кадры двух
    // источников вперемешку — разметка и рамки прыгали несколько раз в секунду.
    let disposed = false;
    let socket: WebSocket | null = null;
    let timer: number | null = null;
    let attempt = 0;

    // Новый источник — прежний кадр больше не его.
    setState({ data: null, link: "connecting", attempt: 0, nextRetrySeconds: 0, receivedAt: null });

    const connect = () => {
      if (disposed) return;
      setState((previous) => ({
        ...previous,
        link: attempt === 0 ? "connecting" : "reconnecting",
        attempt,
      }));

      const current = new WebSocket(websocketUrl(path));
      socket = current;

      current.onopen = () => {
        if (disposed) return;
        attempt = 0;
        setState((previous) => ({ ...previous, link: "live", attempt: 0, nextRetrySeconds: 0 }));
      };

      current.onmessage = (event) => {
        if (disposed) return;
        try {
          const parsed = JSON.parse(event.data) as T;
          setState((previous) => ({
            ...previous,
            data: parsed,
            link: "live",
            receivedAt: Date.now(),
          }));
        } catch {
          // Битое сообщение пропускаем: следующее придёт через доли секунды.
        }
      };

      current.onclose = () => {
        if (disposed) return;
        const delay = RETRY_STEPS_MS[Math.min(attempt, RETRY_STEPS_MS.length - 1)];
        attempt += 1;
        setState((previous) => ({
          ...previous,
          link: "reconnecting",
          attempt,
          nextRetrySeconds: Math.round(delay / 1000),
        }));
        timer = window.setTimeout(connect, delay);
      };

      current.onerror = () => current.close();
    };

    connect();

    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
      if (socket) {
        // Обработчики снимаются: закрытое подключение не должно ни писать в
        // состояние, ни переподключаться.
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      }
    };
  }, [path, enabled]);

  return state;
}

/** Метаданные кадра выбранного источника. */
export function useSourceLive(sourceId: number | null, enabled = true) {
  const path = sourceId === null ? null : `/ws/sources/${sourceId}`;
  return useSocket<LiveMessage>(path, enabled);
}

/** Пульс сервера: состояние источников и признак живой связи. */
export function useSystemPulse(enabled = true) {
  const connection = useSocket<SystemPulse>("/ws/system", enabled);

  // Данные считаются устаревшими, если пульс не приходил дольше двух интервалов.
  const stale = useMemo(() => {
    if (!connection.receivedAt) return connection.link !== "live";
    return Date.now() - connection.receivedAt > 15_000;
  }, [connection.receivedAt, connection.link]);

  return { ...connection, stale };
}
