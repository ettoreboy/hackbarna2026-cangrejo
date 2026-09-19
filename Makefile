# Unfold — task runner.
#
#   make            list every target
#   make setup      venv + deps + .env
#   make e2e        boot the backend in fake mode and analyse a post, offline
#
# Every target uses .venv directly; no `source activate` needed.

VENV    ?= .venv
PY      := $(VENV)/bin/python
PIP     := uv pip install --python $(PY)
PYTEST  := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn

HOST     ?= 127.0.0.1
PORT     ?= 8000
BASE     := http://$(HOST):$(PORT)
POST     ?= weidel_immigration
PROVIDER ?= nebius
MODEL    ?=
VARIANTS ?= nebius:v1,nebius:v0
# Two models of one provider. Both are priced in backend/services/pricing.py, so the cost row
# in the side-by-side is a real number rather than "unpriced".
MODELS   ?= nebius/openai/gpt-oss-120b:v1,nebius/Qwen/Qwen3-235B-A22B-Instruct-2507:v1
LIMIT    ?=

MODEL_ARG := $(if $(MODEL),--model $(MODEL),)
LIMIT_ARG := $(if $(LIMIT),--limit $(LIMIT),)

# One line per block the client renders, out of an /analyze response on stdin.
SUMMARIZE := $(PY) -c 'import json,sys; d=json.load(sys.stdin); a=d["analysis"]; print("schema  ", d["schema_version"], "\u00b7", d["provider"], d["model"] or "-", str(d["latency_ms"])+" ms"); print("claim   ", a["main_claim"]["text"] or "(none found)"); print("verdict ", a["claim_check"]["verdict"]); print("signals ", ", ".join(s["name"] for s in a["rhetorical_signals"]) or "none")'

.DEFAULT_GOAL := help
SHELL := /bin/bash

## ---------------------------------------------------------------- setup

.PHONY: help
help: ## List targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  vars: POST=$(POST) PROVIDER=$(PROVIDER) PORT=$(PORT) VARIANTS=$(VARIANTS)"

.PHONY: setup
setup: $(VENV) .env ## Create the venv, install deps, seed .env
	@echo
	@echo "  next:  make run-fake      backend, offline, no keys"
	@echo "         make extension     load the extension in Chrome (make firefox for Firefox)"

$(VENV):
	uv venv $(VENV) --python 3.11
	$(PIP) -r requirements.txt

.env:
	cp .env.example .env
	@echo "wrote .env — add NEBIUS_API_KEY and BRAVE_API_KEY, or run the fake targets"

.PHONY: deps
deps: ## Reinstall requirements.txt into the venv
	$(PIP) -r requirements.txt

.PHONY: env
env: ## Show which keys are set (never prints a value)
	@$(PY) -c 'from dotenv import dotenv_values; import os; v={**dotenv_values(".env"), **os.environ}; [print(("  set    " if (v.get(k) or "").strip() else "  EMPTY  ")+k) for k in ("NEBIUS_API_KEY","GEMINI_API_KEY","BRAVE_API_KEY","GALTEA_API_KEY","SLNG_API_KEY")]; [print("  "+(v.get(k) or "(default)")+"\t"+k) for k in ("ANALYZER_PROVIDER","NEBIUS_MODEL","BRAVE_BUDGET")]'

## ---------------------------------------------------------------- run

.PHONY: run
run: ## Run the API with reload (uses ANALYZER_PROVIDER from .env)
	$(UVICORN) backend.main:app --reload --host $(HOST) --port $(PORT)

.PHONY: run-fake
run-fake: ## Run the API offline, deterministic, no keys
	ANALYZER_PROVIDER=fake $(UVICORN) backend.main:app --reload --host $(HOST) --port $(PORT)

.PHONY: health
health: ## Curl /api/v1/health on a running server
	@curl -sf $(BASE)/api/v1/health | $(PY) -m json.tool

.PHONY: docs-open
docs-open: ## Open the live OpenAPI page
	open $(BASE)/docs

.PHONY: analyze
analyze: ## POST a fixture post to a running server (POST=<fixture>)
	@curl -sf -X POST $(BASE)/api/v1/analyze -H 'content-type: application/json' \
	  -d "$$($(PY) -c 'import json,sys;print(json.dumps(json.load(open("tests/fixtures/posts.json"))["$(POST)"]["request"]))')" \
	  | $(PY) -m json.tool

## ---------------------------------------------------------------- test

.PHONY: test
test: ## Offline test suite (~0.3 s)
	$(PYTEST) -q

.PHONY: test-live
test-live: ## Tests that hit the real providers; needs keys
	$(PYTEST) -q -m live -s

.PHONY: check
check: ## Full pipeline against Nebius on one post (POST=, MODEL=)
	$(PY) scripts/check_nebius.py --post $(POST) $(MODEL_ARG)

.PHONY: check-fake
check-fake: ## Same pipeline offline, no keys, no Brave spend
	ANALYZER_PROVIDER=fake $(PY) scripts/check_nebius.py --post $(POST)

.PHONY: models
models: ## List the models Token Factory exposes
	$(PY) scripts/check_nebius.py --list-models

.PHONY: compare
compare: ## Prompt v1 vs v0 on one model (VARIANTS=provider[/model][:prompt],...)
	$(PY) scripts/compare.py --post $(POST) --variants $(VARIANTS)

.PHONY: compare-models
compare-models: ## Two Nebius models on one prompt (MODELS=...)
	$(PY) scripts/compare.py --post $(POST) --variants $(MODELS)

## ---------------------------------------------------------------- end to end

.PHONY: e2e
e2e: ## Boot the API in fake mode, run both paths end to end, tear down
	@# Two paths, because they are different code: /analyze is the one-shot pipeline, and
	@# /claims + /analyze-claim is what the extension actually calls on a click.
	@# BRAVE_API_KEY is blanked on purpose: this target must not spend paid search queries.
	@# Refuse to run against a server we did not start. Without this the uvicorn below fails
	@# to bind, the failure scrolls past, and the curls silently hit whatever is on the port --
	@# which on a dev machine is a live-key server, so the "offline, no spend" promise is void.
	@if curl -sf $(BASE)/api/v1/health >/dev/null 2>&1; then \
	  echo "e2e: something is already serving $(BASE). Stop it, or re-run with PORT=8010."; \
	  exit 1; \
	fi
	@set -euo pipefail; \
	ANALYZER_PROVIDER=fake BRAVE_API_KEY= $(UVICORN) backend.main:app --host $(HOST) --port $(PORT) --log-level warning & \
	pid=$$!; trap "kill $$pid 2>/dev/null || true" EXIT; \
	for i in $$(seq 1 40); do curl -sf $(BASE)/api/v1/health >/dev/null && break || sleep 0.25; done; \
	echo "health   $$(curl -sf $(BASE)/api/v1/health)"; \
	curl -sf -X POST $(BASE)/api/v1/analyze -H 'content-type: application/json' \
	  -d "$$($(PY) -c 'import json;print(json.dumps(json.load(open("tests/fixtures/posts.json"))["$(POST)"]["request"]))')" \
	  | $(SUMMARIZE); \
	$(PY) scripts/e2e_twostage.py --base $(BASE) --post $(POST); \
	$(PY) -c 'import json;m=json.load(open("extension/manifest.json"));print("manifest", m["name"], "v"+m["version"])'; \
	echo "e2e OK"

.PHONY: smoke
smoke: test extension-check e2e ## Tests, extension contract, then the offline end-to-end run

## ---------------------------------------------------------------- eval

.PHONY: eval
eval: ## Run the eval set (PROVIDER=, MODEL=, LIMIT=)
	$(PY) -m backend.eval.run_eval --provider $(PROVIDER) $(MODEL_ARG) $(LIMIT_ARG)

.PHONY: eval-smoke
eval-smoke: ## Five items, offline provider, no Brave
	$(PY) -m backend.eval.run_eval --provider fake --limit 5 --no-evidence

.PHONY: eval-set
eval-set: ## Regenerate tests/eval/eval_set.jsonl
	$(PY) -m backend.eval.make_eval_set

.PHONY: galtea-dry
galtea-dry: ## Score a results file and print it, send nothing (RESULTS=, VERSION=)
	$(PY) -m backend.eval.galtea_sync --results $(RESULTS) --version $(VERSION) --dry-run

.PHONY: galtea
galtea: ## Push a scored results file to Galtea (RESULTS=, VERSION=)
	$(PY) -m backend.eval.galtea_sync --results $(RESULTS) --version $(VERSION)

.PHONY: ft-set
ft-set: ## Build the fine-tune train/valid split
	$(PY) -m backend.eval.make_ft_set

.PHONY: finetune
finetune: ## Launch the LoRA job on Token Factory
	$(PY) -m backend.eval.finetune

## ---------------------------------------------------------------- docker

.PHONY: docker-build
docker-build: ## Build the backend image
	docker build -t unfold:local .

.PHONY: docker-up
docker-up: ## Run the container in fake mode, no keys needed
	docker compose up -d --build api
	@for i in $$(seq 1 60); do curl -sf $(BASE)/api/v1/health >/dev/null && break || sleep 0.5; done
	@echo "up   $(BASE)/docs"

.PHONY: docker-up-live
docker-up-live: ## Run the container with the keys from .env
	docker compose --profile live up -d --build api-live
	@for i in $$(seq 1 60); do curl -sf $(BASE)/api/v1/health >/dev/null && break || sleep 0.5; done
	@echo "up   $(BASE)/docs"

.PHONY: docker-logs
docker-logs: ## Tail the container logs
	docker compose logs -f

.PHONY: docker-down
docker-down: ## Stop the containers (keeps the Brave cache volume)
	docker compose --profile live down

.PHONY: docker-clean
docker-clean: ## Stop and delete the image and the cache volume
	docker compose --profile live down -v --rmi local

.PHONY: docker-e2e
docker-e2e: ## Build, boot the container, analyse one post, tear down
	@$(MAKE) --no-print-directory docker-up
	@curl -sf -X POST $(BASE)/api/v1/analyze -H 'content-type: application/json' \
	  -d "$$($(PY) -c 'import json;print(json.dumps(json.load(open("tests/fixtures/posts.json"))["$(POST)"]["request"]))')" \
	  | $(SUMMARIZE) || { $(MAKE) --no-print-directory docker-down; exit 1; }
	@$(MAKE) --no-print-directory docker-down
	@echo "docker e2e OK"

## ---------------------------------------------------------------- project

.PHONY: status
status: ## Branch, dirty files, schema version, last commits
	@echo "branch   $$(git rev-parse --abbrev-ref HEAD)"
	@echo "schema   $$(grep -m1 SCHEMA_VERSION backend/schemas/analysis_schema.py)"
	@echo "dirty    $$(git status --porcelain | wc -l | tr -d ' ') file(s)"
	@echo "cached   $$($(PY) -c 'import sqlite3,pathlib; p=pathlib.Path(".cache/responses.sqlite"); print(sqlite3.connect(p).execute("select count(*) from responses").fetchone()[0] if p.exists() else 0)') analysed post(s)"
	@git status --short
	@echo
	@git log --oneline -5

.PHONY: extension
extension: extension-check ## Install the extension in Chrome: copies the path, opens chrome://extensions
	@# Chrome 137+ ignores --load-extension, so loading unpacked is a manual four clicks.
	@printf '%s' "$(CURDIR)/extension" | pbcopy 2>/dev/null && copied="(path copied to clipboard)" || copied=""; \
	echo; \
	echo "  Load unpacked  $$copied"; \
	echo "    1. chrome://extensions  (opening now)"; \
	echo "    2. turn on Developer mode, top right"; \
	echo "    3. Load unpacked  →  paste  $(CURDIR)/extension"; \
	echo "    4. open x.com and click Unfold on any post"; \
	echo; \
	echo "  Backend must be running: make run-fake  (or make docker-up)"; \
	echo
	@open -a "Google Chrome" "chrome://extensions" 2>/dev/null || echo "  open chrome://extensions by hand"

.PHONY: extension-firefox
firefox: extension-firefox
extension-firefox: extension-check ## Install the extension in Firefox (temporary add-on, gone on restart)
	@# Firefox release only takes unsigned add-ons as temporary ones, and its file picker
	@# wants manifest.json itself, not the folder — so that is what goes on the clipboard.
	@printf '%s' "$(CURDIR)/extension/manifest.json" | pbcopy 2>/dev/null && copied="(manifest path copied to clipboard)" || copied=""; \
	echo; \
	echo "  Load Temporary Add-on  $$copied"; \
	echo "    1. about:debugging#/runtime/this-firefox  (opening now)"; \
	echo "    2. Load Temporary Add-on…"; \
	echo "    3. paste  $(CURDIR)/extension/manifest.json   (the file, not the folder)"; \
	echo "    4. about:addons → Unfold → Permissions → allow 127.0.0.1"; \
	echo "       (Firefox MV3 leaves host permissions off until you say yes)"; \
	echo "    5. open x.com and click Unfold on any post"; \
	echo; \
	echo "  Gone on restart — rerun this target after every Firefox launch."; \
	echo "  Backend must be running: make run-fake  (or make docker-up)"; \
	echo
	@/Applications/Firefox.app/Contents/MacOS/firefox --new-tab "about:debugging#/runtime/this-firefox" >/dev/null 2>&1 \
	  || open -a Firefox "about:debugging#/runtime/this-firefox" 2>/dev/null \
	  || echo "  open about:debugging#/runtime/this-firefox by hand"

.PHONY: extension-check
extension-check: ## Verify the extension and the backend still agree (ports, verdicts, signals)
	@$(PY) scripts/check_extension.py --port $(PORT)

.PHONY: extension-reload
extension-reload: ## What to press after editing extension/ (no restart of the backend needed)
	@echo "  Chrome   chrome://extensions → ⟳ on the Unfold card, then reload the x.com tab"
	@echo "  Firefox  about:debugging#/runtime/this-firefox → Reload, then reload the x.com tab"
	@echo
	@echo "  Neither browser picks up an edit on its own; both keep serving the code they loaded."
	@open -a "Google Chrome" "chrome://extensions" 2>/dev/null || true

.PHONY: extension-zip
extension-zip: ## Package extension/ for the demo handoff
	@rm -f unfold-extension.zip
	@cd extension && zip -qr ../unfold-extension.zip . -x '*.DS_Store'
	@echo "wrote unfold-extension.zip"

.PHONY: brave-usage
brave-usage: ## Cached results and live calls counted against the budget
	@$(PY) -c 'import os,sqlite3; p=os.getenv("SEARCH_CACHE_PATH",".cache/brave.sqlite"); c=sqlite3.connect(p); print(p); print("  cached results", c.execute("select count(*) from results").fetchone()[0]); print("  live calls    ", c.execute("select count(*) from live_calls").fetchone()[0])' 2>/dev/null || echo "no cache at $${SEARCH_CACHE_PATH:-.cache/brave.sqlite} yet"

.PHONY: clean
clean: ## Remove caches and bytecode (keeps .venv, .env, results)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

.PHONY: clean-cache
clean-cache: ## Drop the Brave search cache — next run spends live queries
	rm -f .cache/brave.sqlite

.PHONY: clean-answers
clean-answers: ## Drop cached analyses — every post is re-analysed, and may answer differently
	rm -f .cache/responses.sqlite
	@echo "cleared. The model is not reproducible, so re-analysed posts can differ from before."

.PHONY: nuke
nuke: clean ## Also delete the venv
	rm -rf $(VENV)
