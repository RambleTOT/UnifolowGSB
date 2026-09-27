#!/usr/bin/env bash
# Выкладка на сервер: код — rsync, сборка и запуск — Docker Compose.
#
#   scripts/deploy.sh root@<адрес-сервера>
#
# Повторный запуск обновляет код и пересобирает образ; база, загруженные через
# интерфейс видео, .env и сертификат на сервере не трогаются.
set -euo pipefail

HOST="${1:?Укажите сервер: scripts/deploy.sh root@адрес}"
REMOTE_DIR="${UNIFLOW_REMOTE_DIR:-/opt/uniflow}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADDRESS="${HOST#*@}"

echo "Код → $HOST:$REMOTE_DIR"
# Скрытые каталоги (.git, .venv, настройки редакторов) на сервер не нужны.
rsync -az --delete \
  --exclude '.*/' --exclude apps \
  --exclude node_modules --exclude frontend/dist \
  --exclude '__pycache__' --exclude .pytest_cache \
  --exclude .env --exclude data/ --exclude deploy/certs/ \
  "$ROOT_DIR/" "$HOST:$REMOTE_DIR/"

# Демо-ролики, описания потоков, веса модели и готовые кэши предрасчёта — только то, чего на
# сервере ещё нет. Время изменения сохраняется: по нему узнаётся кэш, и
# сервер не пересчитывает ролики на процессоре заново.
echo "Демо-данные → $HOST (без перезаписи)"
ssh "$HOST" "mkdir -p '$REMOTE_DIR/data'"
# Порядок правил важен: rsync берёт первое совпавшее, поэтому размеченные
# копии роликов (для ручной сверки, серверу не нужны) исключаются первыми.
rsync -az --ignore-existing \
  --exclude '*.annotated.mp4' \
  --include 'videos/' --include 'videos/*.mp4' --include 'videos/*.markup.json' \
  --include 'videos/*.stream.json' \
  --include 'cache/' --include 'cache/weights/***' --include 'cache/tracks/***' \
  --exclude '*' \
  "$ROOT_DIR/data/" "$HOST:$REMOTE_DIR/data/"

ssh "$HOST" "REMOTE_DIR='$REMOTE_DIR' ADDRESS='$ADDRESS' bash -s" <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  secret="$(openssl rand -hex 32)"
  sed -i "s|^UNIFLOW_SECRET_KEY=.*|UNIFLOW_SECRET_KEY=$secret|" .env
  echo "Создан .env с новым ключом подписи"
fi

if [ ! -f deploy/certs/server.crt ]; then
  mkdir -p deploy/certs
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout deploy/certs/server.key -out deploy/certs/server.crt \
    -subj "/CN=$ADDRESS" -addext "subjectAltName=IP:$ADDRESS" 2>/dev/null
  echo "Выпущен самоподписанный сертификат для $ADDRESS"
fi

# Сборка идёт на сервере отдельно от SSH: оборвётся соединение — она доработает.
setsid nohup docker compose up -d --build > deploy.log 2>&1 < /dev/null &
echo "Сборка и запуск идут на сервере, журнал: $REMOTE_DIR/deploy.log"
REMOTE

# Ждём по публичному адресу, а не по SSH: долгая сессия через нестабильную
# сеть рвётся, а HTTPS-запросы короткие.
echo "Жду, пока приложение ответит (первая сборка — 5–10 минут)..."
for _ in $(seq 1 90); do
  if curl -fsSk -m 8 -o /dev/null "https://$ADDRESS/api/health"; then
    echo "Готово: https://$ADDRESS"
    exit 0
  fi
  sleep 10
done
echo "Приложение не ответило за 15 минут. Журнал сборки: ssh $HOST tail -50 $REMOTE_DIR/deploy.log"
exit 1
