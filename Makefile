SHELL := /bin/bash

RUN_DIR := .run
SCRAPER_PID := $(RUN_DIR)/scraper.pid
UI_PID := $(RUN_DIR)/ui.pid
SCRAPER_LOG := $(RUN_DIR)/scraper.log
UI_LOG := $(RUN_DIR)/ui.log

.PHONY: setup run-scraper run-ui run-all run-all-bg stop-all status logs

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip
	. .venv/bin/activate && pip install fastapi uvicorn httpx beautifulsoup4 cachetools jinja2

run-scraper:
	cd apps/scraper-service && ../../.venv/bin/uvicorn app.main:app --reload --port 8080

run-ui:
	cd apps/tier-ui && SCRAPER_BASE_URL=http://127.0.0.1:8080 ../../.venv/bin/uvicorn app.main:app --reload --port 8090

run-all:
	@if lsof -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "port 8080 already in use. stop existing process first."; \
		exit 1; \
	fi
	@if lsof -iTCP:8090 -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "port 8090 already in use. stop existing process first."; \
		exit 1; \
	fi
	@echo "starting scraper (:8080) + ui (:8090) in one terminal"
	@set -e; \
	.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --app-dir apps/scraper-service & \
	SCRAPER_PID=$$!; \
	sleep 1; \
	SCRAPER_BASE_URL=http://127.0.0.1:8080 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090 --app-dir apps/tier-ui & \
	UI_PID=$$!; \
	trap 'kill $$SCRAPER_PID $$UI_PID >/dev/null 2>&1 || true' INT TERM; \
	wait $$SCRAPER_PID $$UI_PID || true

run-all-bg:
	@mkdir -p $(RUN_DIR)
	@if lsof -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "scraper already running on :8080"; \
	else \
		echo "starting scraper on :8080"; \
		nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 \
			--app-dir apps/scraper-service > $(SCRAPER_LOG) 2>&1 & \
		echo $$! > $(SCRAPER_PID); \
	fi
	@if lsof -iTCP:8090 -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "ui already running on :8090"; \
	else \
		echo "starting ui on :8090"; \
		SCRAPER_BASE_URL=http://127.0.0.1:8080 nohup .venv/bin/uvicorn app.main:app \
			--host 127.0.0.1 --port 8090 --app-dir apps/tier-ui > $(UI_LOG) 2>&1 & \
		echo $$! > $(UI_PID); \
	fi
	@$(MAKE) status

stop-all:
	@if [ -f $(SCRAPER_PID) ]; then \
		kill "$$(cat $(SCRAPER_PID))" >/dev/null 2>&1 || true; \
		rm -f $(SCRAPER_PID); \
		echo "stopped scraper"; \
	fi
	@if [ -f $(UI_PID) ]; then \
		kill "$$(cat $(UI_PID))" >/dev/null 2>&1 || true; \
		rm -f $(UI_PID); \
		echo "stopped ui"; \
	fi

status:
	@echo "scraper : $$(curl -sS http://127.0.0.1:8080/health 2>/dev/null || echo down)"
	@echo "ui      : $$(curl -sS http://127.0.0.1:8090/health 2>/dev/null || echo down)"

logs:
	@echo "== scraper log =="
	@tail -n 30 $(SCRAPER_LOG) 2>/dev/null || true
	@echo "== ui log =="
	@tail -n 30 $(UI_LOG) 2>/dev/null || true
