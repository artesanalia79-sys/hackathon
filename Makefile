# Control Tower — one command per thing you actually need to do.
PORT ?= 8000

ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
.SHELLFLAGS := /C
PY_LAUNCHER ?= py
UV := $(PY_LAUNCHER) -m uv
NPM := npm.cmd
POWERSHELL := powershell.exe -NoProfile -ExecutionPolicy Bypass -Command
else
UV := $(shell command -v uv 2>/dev/null || echo "$$HOME/.local/bin/uv")
NPM := npm
endif

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
ifeq ($(OS),Windows_NT)
	$(PY_LAUNCHER) -m pip install --user uv
	$(UV) python install 3.12
	$(UV) sync
	cd ui && $(NPM) install && $(NPM) run build
	@$(POWERSHELL) "if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }"
	@$(POWERSHELL) "Write-Host ''; Write-Host '  ready - ''make run'', then http://localhost:$(PORT)'; Write-Host '  the agent stays off until you put an OPENAI_API_KEY in .env;'; Write-Host '  everything else works without it.'; Write-Host ''"
else
	$(UV) python install 3.12
	$(UV) sync
	cd ui && $(NPM) install && $(NPM) run build
	@test -f .env || cp .env.example .env
	@echo "\n  ready — 'make run', then http://localhost:$(PORT)"
	@echo "  the agent stays off until you put an OPENAI_API_KEY in .env;"
	@echo "  everything else works without it.\n"
endif

ui:
	cd ui && $(NPM) run build

run: ui
	$(UV) run uvicorn api.main:app --host 0.0.0.0 --port $(PORT)

dev:
ifeq ($(OS),Windows_NT)
	$(POWERSHELL) "$$api = Start-Process -FilePath '$(PY_LAUNCHER)' -ArgumentList @('-m','uv','run','uvicorn','api.main:app','--reload','--port','$(PORT)') -WorkingDirectory '$(CURDIR)' -WindowStyle Hidden -PassThru; try { Set-Location -LiteralPath '$(CURDIR)/ui'; & '$(NPM)' run dev } finally { Stop-Process -Id $$api.Id -Force -ErrorAction SilentlyContinue }"
else
	$(UV) run uvicorn api.main:app --reload --port $(PORT) & \
	cd ui && $(NPM) run dev; kill %1
endif

eval:
	$(UV) run python -m eval.run_eval --agent

smoke:
	$(UV) run python -m eval.smoke --port $(PORT)

reset:
ifeq ($(OS),Windows_NT)
	@$(POWERSHELL) "Invoke-RestMethod -Method Post -Uri 'http://localhost:$(PORT)/api/reset' | Out-Null; Write-Host '  reset'"
else
	@curl -s -X POST http://localhost:$(PORT)/api/reset && echo "  reset"
endif

lint:
	$(UV) run ruff check api eval

clean:
ifeq ($(OS),Windows_NT)
	$(POWERSHELL) "$$root = [IO.Path]::GetFullPath('$(CURDIR)'); $$targets = @('.venv','ui/node_modules','ui/dist','data','__pycache__','.pytest_cache','.ruff_cache'); foreach ($$target in $$targets) { $$resolved = [IO.Path]::GetFullPath((Join-Path $$root $$target)); if ($$resolved.StartsWith($$root + [IO.Path]::DirectorySeparatorChar) -and (Test-Path -LiteralPath $$resolved)) { Remove-Item -LiteralPath $$resolved -Recurse -Force } }; Get-ChildItem -LiteralPath $$root -Directory -Filter '__pycache__' -Recurse -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $$_.FullName -Recurse -Force }"
else
	rm -rf .venv ui/node_modules ui/dist data __pycache__ .pytest_cache .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
endif
