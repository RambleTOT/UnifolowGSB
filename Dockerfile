# Сборка фронтенда
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Приложение
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UNIFLOW_ENV=server

# Системные библиотеки для OpenCV и работы со шрифтами
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# На сервере без видеокарты ставим torch из CPU-индекса: иначе в образ приедет
# несколько гигабайт библиотек CUDA, которые там никогда не понадобятся.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r backend/requirements.txt

COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=web /web/dist ./frontend/dist

RUN mkdir -p data/videos data/snapshots data/cache

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

WORKDIR /app/backend
# Видеопоток (MJPEG) бесконечный: без таймаута остановка контейнера ждала бы,
# пока зрители сами закроют страницы с видео.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "3"]
