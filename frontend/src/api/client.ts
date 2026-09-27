/**
 * Обращение к серверу.
 *
 * Ошибка приходит в едином формате и уже на русском, поэтому клиент её не
 * придумывает, а доносит (задание, раздел 8). Истечение сессии — отдельное
 * событие: интерфейс возвращает на вход и потом на то же место (ТЗ, 4.5).
 */

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** Ошибки по конкретным полям формы, если сервер их прислал. */
  get fields(): Record<string, string> {
    const fields = this.details.fields;
    return typeof fields === "object" && fields !== null ? (fields as Record<string, string>) : {};
  }

  /** Замечания по объектам разметки. */
  get objects(): Array<{ id: string; code: string; message: string }> {
    const objects = this.details.objects;
    return Array.isArray(objects) ? (objects as Array<{ id: string; code: string; message: string }>) : [];
  }
}

export const SESSION_EXPIRED_EVENT = "uniflow:session-expired";

function notifySessionExpired(): void {
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    const error = body?.error;
    if (error?.code) {
      return new ApiError(error.code, error.message, response.status, error.details ?? {});
    }
  } catch {
    // Тело не разобралось — ниже вернём общее сообщение.
  }
  return new ApiError(
    "network_error",
    `Сервер ответил с ошибкой ${response.status}.`,
    response.status,
  );
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  /** Не уводить на вход при 401: нужно самой странице входа. */
  allowUnauthorized?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, allowUnauthorized } = options;

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      signal,
      credentials: "include",
      headers: body instanceof FormData || body === undefined
        ? undefined
        : { "Content-Type": "application/json" },
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(
      "network_error",
      "Нет связи с сервером. Проверьте, запущен ли он, и повторите.",
      0,
    );
  }

  if (response.status === 401 && !allowUnauthorized) {
    notifySessionExpired();
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** Загрузка файла с ходом выполнения и возможностью отмены (ТЗ, 5.7.1). */
export function upload<T>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
): { promise: Promise<T>; cancel: () => void } {
  const xhr = new XMLHttpRequest();
  const form = new FormData();
  form.append("file", file);

  const promise = new Promise<T>((resolve, reject) => {
    xhr.open("POST", path);
    xhr.withCredentials = true;

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let body: any = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as T);
        return;
      }
      if (xhr.status === 401) notifySessionExpired();
      const error = body?.error;
      reject(
        new ApiError(
          error?.code ?? "upload_failed",
          error?.message ?? "Загрузка не удалась.",
          xhr.status,
          error?.details ?? {},
        ),
      );
    };

    xhr.onerror = () =>
      reject(new ApiError("network_error", "Загрузка прервалась: нет связи с сервером.", 0));
    xhr.onabort = () => reject(new ApiError("cancelled", "Загрузка отменена.", 0));

    xhr.send(form);
  });

  return { promise, cancel: () => xhr.abort() };
}

/** Адрес веб-сокета рядом с текущим адресом страницы. */
export function websocketUrl(path: string): string {
  const url = new URL(path, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
