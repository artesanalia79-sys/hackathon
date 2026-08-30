# Control Tower — one command per thing you actually need to do.
UV := $(shell command -v uv 2>/dev/null || echo "$$HOME/.local/bin/uv")
PORT ?= 8000

.PHONY: help setup run dev ui eval smoke reset clean lint

help:
	@echo ""
	@echo "  make setup   install Python 3.12 + deps + build the UI"
	@echo "  make run     serve API and UI on http://localhost:$(PORT)"
	@echo "  make dev     API with reload + Vite dev server (two terminals in one)"
	@echo "  make eval    run every ugly case in docs/UGLY_CASES.md"
	@echo "  make smoke   30-second end-to-end check against a running server"
	@echo "  make reset   clear injections, incidents and memory on a running server"
	@echo ""

setup:
	$(UV) python install 3.12
	$(UV) sync
	cd ui && npm install && npm run build
	@test -f .env || cp .env.example .env
	@echo "\n  ready — 'make run', then http://localhost:$(PORT)"
	@echo "  the agent stays off until you put an OPENAI_API_KEY in .env;"
	@echo "  everything else works without it.\n"

ui:
	cd ui && npm run build

run: ui
	$(UV) run uvicorn api.main:app --host 0.0.0.0 --port $(PORT)

dev:
	$(UV) run uvicorn api.main:app --reload --port $(PORT) & \
	cd ui && npm run dev; kill %1

eval:
	$(UV) run python -m eval.run_eval --agent

smoke:
	$(UV) run python -m eval.smoke --port $(PORT)

reset:
	@curl -s -X POST http://localhost:$(PORT)/api/reset && echo "  reset"

lint:
	$(UV) run ruff check api eval

clean:
	rm -rf .venv ui/node_modules ui/dist data __pycache__ .pytest_cache .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
