import { useState } from "react";

import { ApiError } from "../../api/client";
import { useChangeEventStatus } from "../../api/queries";
import type { EventView } from "../../api/types";
import { Button } from "../common/Button";
import { useToasts } from "../common/Toasts";

const NEXT: Record<string, Array<{ status: string; label: string }>> = {
  open: [
    { status: "investigating", label: "Взять в работу" },
    { status: "resolved", label: "Решено" },
  ],
  investigating: [{ status: "resolved", label: "Решено" }],
  resolved: [{ status: "open", label: "Открыть заново" }],
};

/** Смена статуса обработки: её делает человек, и она пишется в историю. */
export function StatusControls({ event }: { event: EventView }) {
  const change = useChangeEventStatus();
  const toasts = useToasts();
  const [comment, setComment] = useState("");

  const apply = (status: string) => {
    change.mutate(
      { id: event.id, status, comment, expectedStatus: event.status },
      {
        onSuccess: () => {
          setComment("");
          toasts.success("Статус изменён");
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "event_changed") {
            toasts.error("Событие уже изменили", error.message);
            return;
          }
          toasts.error("Не удалось изменить статус", (error as Error).message);
        },
      },
    );
  };

  return (
    <div className="status-controls">
      <input
        className="input"
        placeholder="Комментарий (необязательно)"
        value={comment}
        onChange={(input) => setComment(input.target.value)}
        maxLength={500}
      />
      <div className="row-actions">
        {(NEXT[event.status] ?? []).map((action) => (
          <Button
            key={action.status}
            variant={action.status === "resolved" ? "primary" : "secondary"}
            size="sm"
            onClick={() => apply(action.status)}
            loading={change.isPending}
          >
            {action.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
