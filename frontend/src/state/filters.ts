/**
 * Глобальные фильтры живут в адресе страницы.
 *
 * Ссылкой можно поделиться с коллегой, и он увидит то же самое, а «назад»
 * возвращает в то же место с теми же фильтрами (ТЗ, раздел 4.5).
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

export type Period = "hour" | "day" | "week" | "month" | "custom";
export type ScopeFilter = "all" | "canteen" | "gate";

export interface Filters {
  period: Period;
  scope: ScopeFilter;
  from: string | null;
  to: string | null;
  sourceId: number | null;
}

const PERIODS: Period[] = ["hour", "day", "week", "month", "custom"];
const SCOPES: ScopeFilter[] = ["all", "canteen", "gate"];

export function useFilters() {
  const [params, setParams] = useSearchParams();

  const filters = useMemo<Filters>(() => {
    const period = params.get("period");
    const scope = params.get("scope");
    const sourceId = params.get("source");
    return {
      period: PERIODS.includes(period as Period) ? (period as Period) : "day",
      scope: SCOPES.includes(scope as ScopeFilter) ? (scope as ScopeFilter) : "all",
      from: params.get("from"),
      to: params.get("to"),
      sourceId: sourceId ? Number(sourceId) : null,
    };
  }, [params]);

  const update = useCallback(
    (patch: Partial<Filters>, options?: { replace?: boolean }) => {
      const next = new URLSearchParams(params);
      const apply = (key: string, value: string | number | null | undefined) => {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, String(value));
      };

      if ("period" in patch) apply("period", patch.period ?? null);
      if ("scope" in patch) apply("scope", patch.scope ?? null);
      if ("from" in patch) apply("from", patch.from ?? null);
      if ("to" in patch) apply("to", patch.to ?? null);
      if ("sourceId" in patch) apply("source", patch.sourceId ?? null);

      setParams(next, { replace: options?.replace ?? false });
    },
    [params, setParams],
  );

  return { filters, update };
}

/** Диапазон дат обязателен и должен быть осмысленным (ТЗ, 3.6). */
export function validateRange(from: string | null, to: string | null): string | null {
  if (!from || !to) return "Укажите обе даты диапазона.";
  const start = new Date(from);
  const end = new Date(to);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Дата указана неверно.";
  if (end < start) return "Дата «до» не может быть раньше даты «от».";
  if (end > new Date()) return "Дата «до» не может быть в будущем.";
  return null;
}
