#!/usr/bin/env bash
# Запуск бэкенда и фронтенда одной командой. Ctrl+C останавливает оба.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV="${VENV:-.venv}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан .env из .env.example — проверьте параметры."
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "Нет окружения бэкенда. Выполните: make install"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

HOST="${UNIFLOW_HOST:-127.0.0.1}"
PORT="${UNIFLOW_PORT:-8000}"

pids=()
cleanup() {
  echo
  echo "Останавливаю..."
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Бэкенд: http://$HOST:$PORT"
# Видеопоток (MJPEG) бесконечный: без таймаута перезапуск ждал бы, пока
# зритель сам закроет страницу с видео.
(cd backend && "../$VENV/bin/uvicorn" app.main:app --reload --timeout-graceful-shutdown 3 \
  --host "$HOST" --port "$PORT") &
pids+=($!)

if [ -f frontend/package.json ]; then
  if [ ! -d frontend/node_modules ]; then
    echo "Ставлю зависимости фронтенда..."
    (cd frontend && npm install)
  fi
  echo "Фронтенд: http://localhost:5173"
  (cd frontend && npm run dev) &
  pids+=($!)
else
  echo "Фронтенд ещё не собран (этап M3) — запускаю только бэкенд."
fi

wait
