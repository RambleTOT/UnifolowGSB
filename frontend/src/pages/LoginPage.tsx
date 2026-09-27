import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useLogin } from "../api/queries";
import { Button } from "../components/common/Button";
import { Field } from "../components/common/Field";
import { useSession } from "../state/session";

const START_SECTIONS: Record<string, string> = {
  home: "/",
  monitor: "/monitor",
  sources: "/sources",
};

export function LoginPage() {
  const navigate = useNavigate();
  const login = useLogin();
  const { user, returnTo, expired, clearExpired } = useSession();
  const [form, setForm] = useState({ login: "", password: "" });

  // Уже вошедшего пользователя на форме входа держать незачем.
  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  const error = login.error;
  const serverDown = error instanceof ApiError && error.code === "network_error";

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    clearExpired();
    login.mutate(form, {
      onSuccess: (data) => {
        const start = START_SECTIONS[data.user.start.section] ?? "/";
        const scope = data.user.start.scope;
        const target = returnTo ?? `${start}${scope && scope !== "all" ? `?scope=${scope}` : ""}`;
        navigate(target, { replace: true });
      },
    });
  };

  return (
    <div className="login">
      <form className="login__form" onSubmit={submit}>
        <div className="login__brand">
          <span className="sidebar__mark" aria-hidden="true">UF</span>
          <span>
            <strong>UniFlow</strong>
            <small>Analytics</small>
          </span>
        </div>

        <h1 className="login__title">Вход в систему</h1>
        <p className="login__hint">
          Учётные записи создаёт администратор системы. Регистрации и восстановления пароля нет.
        </p>

        {expired && (
          <div className="login__notice login__notice--warn" role="status">
            Сессия истекла. Войдите заново — вы вернётесь туда, где остановились.
          </div>
        )}

        <Field label="Логин" htmlFor="login-field" required>
          <input
            id="login-field"
            className="input"
            autoComplete="username"
            value={form.login}
            onChange={(event) => setForm({ ...form, login: event.target.value })}
            required
          />
        </Field>

        <Field label="Пароль" htmlFor="password-field" required>
          <input
            id="password-field"
            className="input"
            type="password"
            autoComplete="current-password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            required
          />
        </Field>

        {error && (
          <div className="login__notice login__notice--error" role="alert">
            {serverDown
              ? "Сервер недоступен. Проверьте, запущен ли он, и повторите."
              : (error as ApiError).message}
          </div>
        )}

        <Button type="submit" variant="primary" loading={login.isPending}>
          Войти
        </Button>
      </form>

      <aside className="login__side">
        <p className="login__side-label">Операционная видеоаналитика</p>
        <h2 className="login__side-title">
          Сколько людей вошло, вышло, сколько внутри и где очередь
        </h2>
        <p className="login__side-text">
          Система считает людей как обезличенные объекты: без распознавания лиц и любой привязки к
          личности.
        </p>
      </aside>
    </div>
  );
}
