VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install install-web dev dev-api dev-web build-web demo-videos test test-web evaluate docker-up docker-down clean

help:
	@echo "make install      — окружение бэкенда и зависимости"
	@echo "make install-web  — зависимости фронтенда"
	@echo "make dev          — бэкенд и фронтенд одной командой"
	@echo "make build-web    — сборка интерфейса для сервера"
	@echo "make demo-videos  — скачать демонстрационные ролики в data/videos"
	@echo "make test         — тесты бэкенда"
	@echo "make test-web     — тесты фронтенда"
	@echo "make evaluate     — офлайн-проверка подсчёта: make evaluate VIDEO=... MARKUP=... OUT=..."
	@echo "make docker-up    — сборка и запуск в Docker"

install:
	python3.12 -m venv $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt

install-web:
	cd frontend && npm install

dev:
	@bash scripts/dev.sh

dev-api:
	cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload --timeout-graceful-shutdown 3 --host $${UNIFLOW_HOST:-127.0.0.1} --port $${UNIFLOW_PORT:-8000}

dev-web:
	cd frontend && npm run dev

build-web:
	cd frontend && npm run build

demo-videos:  ## Скачать демонстрационные ролики в data/videos
	./scripts/fetch_demo_videos.sh

test:
	cd backend && ../$(VENV)/bin/python -m pytest -q

test-web:
	cd frontend && npx vitest run

evaluate:
	$(PY) scripts/evaluate.py --video $(VIDEO) $(if $(MARKUP),--markup $(MARKUP),) $(if $(OUT),--output $(OUT),)

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf $(VENV) frontend/node_modules frontend/dist backend/.pytest_cache
