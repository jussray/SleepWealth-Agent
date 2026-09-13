.PHONY: help setup test lint format validate run-paper run-paper-blocked run-live clean

help:
	@echo "sleepwealth-agent - governed market observation + local simulation"
	@echo ""
	@echo "  make setup       install package + dev deps (editable)"
	@echo "  make test        run pytest"
	@echo "  make lint        ruff static checks"
	@echo "  make format      black formatting"
	@echo "  make validate    validate rules.json against schema"
	@echo "  make run-paper   one local simulation cycle against the mock broker"
	@echo "  make run-paper-blocked  show the ceiling refusing an oversized simulation"
	@echo "  make run-live    show the live-mode refusal (always fails)"
	@echo "  make clean       remove caches and build artifacts"

setup:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

lint:
	ruff check .

format:
	black . --line-length=100

validate:
	python -m cli.main validate

run-paper:
	python -m cli.main run --mode paper --broker mock --symbol AAPL --qty 0.04 --side buy --auto-approve

run-paper-blocked:
	-python -m cli.main run --mode paper --broker mock --symbol AAPL --qty 1 --side buy --auto-approve

run-live:
	@echo "LIVE MODE DISABLED. SleepWealth execution is simulation-only."
	@false

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -f audit.log

# ---- race harness ----------------------------------------------------
.PHONY: race race-series race-long gate modes

race:
	python -m cli.race run --duration 1h

race-series:
	python -m cli.race series --races 4 --duration 30m

race-long:
	python -m cli.race run --duration 1d

gate:
	python -m cli.race gate

modes:
	python -m cli.race modes
