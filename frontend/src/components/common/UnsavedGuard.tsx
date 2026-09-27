import { useEffect } from "react";

/**
 * Предупреждение о несохранённых изменениях при уходе со страницы
 * (ТЗ, раздел 4.7). Браузерное окно здесь уместно: другого способа перехватить
 * закрытие вкладки нет.
 */
export function useUnsavedGuard(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}
