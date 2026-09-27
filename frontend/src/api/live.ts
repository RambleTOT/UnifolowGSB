/**
 * Живая часть: метаданные кадра и пульс сервера.
 *
 * Связь может пропасть, и это отдельное состояние: значения на экране
 * помечаются устаревшими, а переподключение идёт с нарастающей паузой
 * (ТЗ, раздел 4.3 и 6.9).
 */

import { useEffect, useMemo, useRef, useState } from "react";

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
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const disposedRef = useRef(false);

  useEffect(() => {
    if (!path || !enabled) {
      setState((previous) => ({ ...previous, link: "closed" }));
      return;
    }

    disposedRef.current = false;
    attemptRef.current = 0;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const connect = () => {
      if (disposedRef.current) return;
      setState((previous) => ({
        ...previous,
        link: attemptRef.current === 0 ? "connecting" : "reconnecting",
        attempt: attemptRef.current,
      }));

      const socket = new WebSocket(websocketUrl(path));
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        setState((previous) => ({ ...previous, link: "live", attempt: 0, nextRetrySeconds: 0 }));
      };

      socket.onmessage = (event) => {
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

      socket.onclose = () => {
        if (disposedRef.current) return;
        const delay = RETRY_STEPS_MS[Math.min(attemptRef.current, RETRY_STEPS_MS.length - 1)];
        attemptRef.current += 1;
        setState((previous) => ({
          ...previous,
          link: "reconnecting",
          attempt: attemptRef.current,
          nextRetrySeconds: Math.round(delay / 1000),
        }));
        timerRef.current = window.setTimeout(connect, delay);
      };

      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      disposedRef.current = true;
      clearTimer();
      socketRef.current?.close();
      socketRef.current = null;
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
