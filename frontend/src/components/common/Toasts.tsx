import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

/**
 * Отклик на действия.
 *
 * Системные окна браузера не используются (ТЗ, раздел 4.7): у каждого действия
 * есть встроенное подтверждение — получилось или нет и что именно произошло.
 */
export type ToastTone = "success" | "error" | "info";

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
  details?: string;
}

interface ToastContextValue {
  show: (message: string, tone?: ToastTone, details?: string) => void;
  success: (message: string, details?: string) => void;
  error: (message: string, details?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((message: string, tone: ToastTone = "info", details?: string) => {
    const id = Date.now() + Math.random();
    setToasts((previous) => [...previous, { id, tone, message, details }]);
    window.setTimeout(() => {
      setToasts((previous) => previous.filter((toast) => toast.id !== id));
    }, tone === "error" ? 9000 : 5000);
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({
      show,
      success: (message, details) => show(message, "success", details),
      error: (message, details) => show(message, "error", details),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.tone}`}>
            <strong>{toast.message}</strong>
            {toast.details && <span>{toast.details}</span>}
            <button
              type="button"
              className="toast__close"
              onClick={() => setToasts((previous) => previous.filter((item) => item.id !== toast.id))}
              aria-label="Закрыть сообщение"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToasts вызван вне ToastProvider");
  return context;
}
