import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import type { ReportParams } from "../api/queries";
import { downloadReport, useReportPreview, useSources } from "../api/queries";
import type { ReportView } from "../api/types";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { Field } from "../components/common/Field";
import { Panel } from "../components/common/Panel";
import { useToasts } from "../components/common/Toasts";
import { MetricsRow } from "../components/analytics/MetricsRow";
import { EventCard } from "../components/events/EventCard";
import { label } from "../lib/dictionary";
import { formatDateTime, formatNumber } from "../lib/format";
import { useSession } from "../state/session";

const STEPS = [
  { value: "minute", label: "1 минута" },
  { value: "quarter", label: "15 минут" },
  { value: "hour", label: "1 час" },
  { value: "day", label: "1 сутки" },
];

const PERIODS = ["hour", "day", "week", "month", "custom"];

function formatCell(value: number | string | null, unit: string): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return `${formatNumber(value)}${unit ? ` ${unit}` : ""}`;
  return String(value);
}

export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const { user } = useSession();
  const toasts = useToasts();
  const sourcesQuery = useSources();
  const preview = useReportPreview();

  // Параметры отчёта свои: глобальный период на раздел не влияет (ТЗ, 4.4),
  // но при переходе из аналитики он подставляется ссылкой.
  const [form, setForm] = useState<ReportParams>(() => ({
    scope: (params.get("scope") as ReportParams["scope"]) ?? "canteen",
    source_id: params.get("source") ? Number(params.get("source")) : null,
    period: params.get("period") ?? "day",
    date_from: params.get("from"),
    date_to: params.get("to"),
    step: params.get("step"),
  }));

  const [report, setReport] = useState<ReportView | null>(null);
  const [builtFrom, setBuiltFrom] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);

  const signature = useMemo(() => JSON.stringify(form), [form]);
  // Если параметры изменились после сборки, файл уже не совпадёт с экраном.
  const stale = report !== null && builtFrom !== signature;

  const build = () => {
    preview.mutate(form, {
      onSuccess: (data) => {
        setReport(data.report);
        setBuiltFrom(JSON.stringify(form));
      },
      onError: (error) => toasts.error("Не удалось собрать отчёт", (error as Error).message),
    });
  };

  // Переход из аналитики «Отчёт по этому срезу» сразу собирает предпросмотр.
  useEffect(() => {
    if (params.get("auto") === "1" && !report && !preview.isPending) build();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (changes: Partial<ReportParams>) => {
    setForm((current: ReportParams) => ({ ...current, ...changes }));
    const next = new URLSearchParams(params);
    next.delete("auto");
    setParams(next, { replace: true });
  };

  const exportAs = async (format: "csv" | "xlsx" | "pdf") => {
    setExporting(format);
    try {
      const name = await downloadReport({ ...form, format });
      toasts.success("Файл сформирован", name);
    } catch (error) {
      toasts.error(
        "Выгрузка не удалась",
        error instanceof ApiError ? error.message : (error as Error).message,
      );
    } finally {
      setExporting(null);
    }
  };

  const exportDisabledReason = !report
    ? "Сначала соберите предпросмотр: файл должен совпадать с тем, что вы видите"
    : stale
      ? "Параметры изменились — обновите предпросмотр, иначе файл будет другим"
      : undefined;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Отчёты</h1>
          <p className="page__subtitle">
            Выгрузка по контуру или источнику. У отчёта собственный период — глобальный фильтр на
            него не влияет.
            {user?.dataset === "demo" && " Сейчас включены демо-данные, файл будет помечен."}
          </p>
        </div>
      </header>

      <Panel title="Параметры отчёта">
        <div className="form-grid">
          <Field label="Тип отчёта" htmlFor="scope">
            <select
              id="scope"
              className="input"
              value={form.scope}
              onChange={(event) =>
                patch({ scope: event.target.value as ReportParams["scope"] })
              }
            >
              <option value="canteen">По контуру «Столовая»</option>
              <option value="gate">По контуру «КПП»</option>
              <option value="source">По источнику</option>
            </select>
          </Field>

          <Field
            label="Источник"
            htmlFor="source"
            hint={form.scope === "source" ? undefined : "Доступен для отчёта по источнику"}
          >
            <select
              id="source"
              className="input"
              value={form.source_id ?? ""}
              disabled={form.scope !== "source"}
              onChange={(event) =>
                patch({ source_id: event.target.value ? Number(event.target.value) : null })
              }
            >
              <option value="">Не выбран</option>
              {sourcesQuery.data?.sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Период" htmlFor="period">
            <select
              id="period"
              className="input"
              value={form.period}
              onChange={(event) => patch({ period: event.target.value })}
            >
              {PERIODS.map((period) => (
                <option key={period} value={period}>
                  {label("period", period)}
                </option>
              ))}
            </select>
          </Field>

          {form.period === "custom" && (
            <>
              <Field label="От" htmlFor="from">
                <input
                  id="from"
                  className="input"
                  type="date"
                  value={form.date_from ?? ""}
                  onChange={(event) => patch({ date_from: event.target.value })}
                />
              </Field>
              <Field label="До" htmlFor="to">
                <input
                  id="to"
                  className="input"
                  type="date"
                  value={form.date_to ?? ""}
                  onChange={(event) => patch({ date_to: event.target.value })}
                />
              </Field>
            </>
          )}

          <Field
            label="Детализация"
            htmlFor="step"
            hint="Шаг строк таблицы. Мельче интервала агрегации быть не может"
          >
            <select
              id="step"
              className="input"
              value={form.step ?? ""}
              onChange={(event) => patch({ step: event.target.value || null })}
            >
              <option value="">Подобрать по периоду</option>
              {STEPS.map((step) => (
                <option key={step.value} value={step.value}>
                  {step.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="form-actions">
          <Button variant="primary" onClick={build} loading={preview.isPending}>
            {report ? "Обновить предпросмотр" : "Собрать предпросмотр"}
          </Button>
          <span className="muted">
            {stale
              ? "Параметры изменились — предпросмотр устарел"
              : report
                ? "Предпросмотр готов, файл совпадёт с ним"
                : "Файл можно выгрузить после предпросмотра"}
          </span>
        </div>
      </Panel>

      {!report ? (
        <Panel>
          <EmptyState
            title="Предпросмотр ещё не собран"
            description="Выберите объект отчёта и период, затем соберите предпросмотр. Так вы увидите ровно то, что попадёт в файл."
          />
        </Panel>
      ) : (
        <div className={stale ? "page__stack report--stale" : "page__stack"}>
          <Panel
            title={report.title}
            meta={
              <>
                <span>
                  {formatDateTime(report.parameters.from)} — {formatDateTime(report.parameters.to)}
                </span>
                <span>шаг {report.parameters.stepTitle}</span>
                <span>строк: {report.totals.rows}</span>
                <span>
                  сформирован {formatDateTime(report.generatedAt)} · {report.author}
                </span>
                {report.demo && <span className="report__demo">Демо-данные</span>}
              </>
            }
            actions={
              <div className="row-actions">
                <Button
                  onClick={() => exportAs("pdf")}
                  disabled={Boolean(exportDisabledReason)}
                  disabledReason={exportDisabledReason}
                  loading={exporting === "pdf"}
                >
                  PDF
                </Button>
                <Button
                  onClick={() => exportAs("xlsx")}
                  disabled={Boolean(exportDisabledReason)}
                  disabledReason={exportDisabledReason}
                  loading={exporting === "xlsx"}
                >
                  Excel
                </Button>
                <Button
                  onClick={() => exportAs("csv")}
                  disabled={Boolean(exportDisabledReason)}
                  disabledReason={exportDisabledReason}
                  loading={exporting === "csv"}
                >
                  CSV
                </Button>
              </div>
            }
          >
            {stale && (
              <p className="notice notice--warn">
                Параметры изменились после сборки. Обновите предпросмотр — иначе файл не совпадёт с
                тем, что на экране.
              </p>
            )}
            {report.stepHint && <p className="notice">{report.stepHint}</p>}
            <MetricsRow metrics={report.summary} />
          </Panel>

          <Panel title="Табличная часть" meta={`${report.totals.rows} строк · шаг ${report.parameters.stepTitle}`}>
            {report.rows.length === 0 ? (
              <EmptyState
                title="За выбранные параметры данных нет"
                description="Смените период или объект отчёта."
              />
            ) : (
              <div className="table-wrap table-wrap--tall">
                <table className="table">
                  <thead>
                    <tr>
                      {report.columns.map((column) => (
                        <th key={column.key}>
                          {column.title}
                          {column.unit && <span className="muted">, {column.unit}</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((row, index) => (
                      <tr key={index}>
                        {report.columns.map((column) => (
                          <td key={column.key} className="tabular">
                            {column.key === "slot"
                              ? formatDateTime(String(row.slot))
                              : formatCell(row[column.key], "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Приложение: события за период" meta={`${report.events.length} событий`}>
            {report.events.length > 0 ? (
              <div className="event-grid">
                {report.events.slice(0, 9).map((event) => (
                  <EventCard key={event.id} event={event} compact />
                ))}
              </div>
            ) : (
              <p className="ok-note">За период событий не было.</p>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
