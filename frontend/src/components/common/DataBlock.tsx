import type { ReactNode } from "react";

import { ApiError } from "../../api/client";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

/**
 * Единая обёртка блока данных.
 *
 * Все состояния из ТЗ (раздел 6) живут в одном месте, поэтому «загрузка»,
 * «пусто по данным» и «пусто по фильтру» выглядят одинаково во всех разделах,
 * а каждый блок грузится и падает независимо от соседей.
 */
export type BlockState =
  | "loading"
  | "refreshing"
  | "ready"
  | "empty"
  | "not-enough-history"
  | "empty-by-filter"
  | "not-applicable"
  | "error";

interface DataBlockProps {
  state: BlockState;
  error?: unknown;
  onRetry?: () => void;
  /** Тексты состояний: у каждого блока причина своя. */
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  historyTitle?: string;
  historyDescription?: string;
  filterDescription?: string;
  onResetFilters?: () => void;
  notApplicableTitle?: string;
  notApplicableDescription?: string;
  notApplicableAction?: ReactNode;
  /** Данные неполные: часть источников не учтена. */
  incomplete?: { counted: number; total: number; names?: string[] } | null;
  children: ReactNode;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Неизвестная ошибка.";
}

export function DataBlock({
  state,
  error,
  onRetry,
  emptyTitle = "Данных пока нет",
  emptyDescription,
  emptyAction,
  historyTitle = "Недостаточно истории",
  historyDescription,
  filterDescription = "По выбранным фильтрам ничего не нашлось.",
  onResetFilters,
  notApplicableTitle = "Неприменимо к выборке",
  notApplicableDescription,
  notApplicableAction,
  incomplete,
  children,
}: DataBlockProps) {
  if (state === "loading") {
    return (
      <div className="block-state" role="status" aria-live="polite">
        <span className="block-state__spinner" aria-hidden="true" />
        Загружаем данные…
      </div>
    );
  }

  if (state === "error") {
    return (
      <EmptyState
        tone="danger"
        title="Не удалось загрузить данные"
        description={errorMessage(error)}
        action={onRetry && <Button onClick={onRetry}>Повторить</Button>}
      />
    );
  }

  if (state === "empty") {
    return <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />;
  }

  if (state === "not-enough-history") {
    return <EmptyState title={historyTitle} description={historyDescription} />;
  }

  if (state === "empty-by-filter") {
    return (
      <EmptyState
        title="Ничего не найдено"
        description={filterDescription}
        action={
          onResetFilters && (
            <Button onClick={onResetFilters}>Сбросить фильтры</Button>
          )
        }
      />
    );
  }

  if (state === "not-applicable") {
    return (
      <EmptyState
        tone="warn"
        title={notApplicableTitle}
        description={notApplicableDescription}
        action={notApplicableAction}
      />
    );
  }

  return (
    <div className={state === "refreshing" ? "block block--refreshing" : "block"}>
      {incomplete && (
        <p className="block__incomplete" title={incomplete.names?.join(", ")}>
          Учтено {incomplete.counted} из {incomplete.total} источников
          {incomplete.names?.length ? `: не хватает ${incomplete.names.join(", ")}` : ""}
        </p>
      )}
      {children}
    </div>
  );
}

/** Состояние блока по типовым признакам запроса. */
export function blockState(options: {
  isLoading: boolean;
  isFetching?: boolean;
  isError: boolean;
  isEmpty?: boolean;
}): BlockState {
  if (options.isError) return "error";
  if (options.isLoading) return "loading";
  if (options.isEmpty) return "empty";
  if (options.isFetching) return "refreshing";
  return "ready";
}
