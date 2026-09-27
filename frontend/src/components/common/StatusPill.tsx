import { label, statusTone } from "../../lib/dictionary";

interface StatusPillProps {
  status: string | null | undefined;
  dictionary?: "sourceStatus" | "connectionStatus" | "modelStatus" | "readiness" | "eventStatus" | "severity";
  /** Подпись вместо словарной: нужна там, где текст уже готов. */
  text?: string;
  tone?: "ok" | "warn" | "danger" | "muted" | "accent";
}

/**
 * Статус показывается не только цветом: у каждого тона своя форма значка,
 * иначе состояния неразличимы при нарушениях цветовосприятия (ТЗ, 4.8).
 */
export function StatusPill({ status, dictionary = "sourceStatus", text, tone }: StatusPillProps) {
  const resolved = tone ?? statusTone(status);
  return (
    <span className={`pill pill--${resolved}`}>
      <span className={`pill__dot pill__dot--${resolved}`} aria-hidden="true" />
      {text ?? label(dictionary, status)}
    </span>
  );
}
