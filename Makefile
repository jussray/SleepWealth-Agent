.PHONY: help setup test lint format validate run-paper run-paper-blocked run-live clean

help:
	@echo "trading-agent - governed trading agent"
	@echo ""
	@echo "  make setup       install package + dev deps (editable)"
	@echo "  make test        run pytest"
	@echo "  make lint        ruff static checks"
	@echo "  make format      black formatting"
	@echo "  make validate    validate rules.json against schema"
	@echo "  make run-paper   one paper cycle against the mock broker
	@echo "  make run-paper-blocked  show the ceiling refusing an oversized order""
	@echo "  make run-live    live mode (interactive confirm, no auto-approve)"
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
	@echo "Ceiling is \$$5, so qty is fractional. This is the ceiling working, not a bug."
	python -m cli.main run --mode paper --broker mock --symbol AAPL --qty 0.04 --side buy --auto-approve

run-paper-blocked:
	@echo "Demonstrates the ceiling refusing an oversized order (expected non-zero exit)."
	-python -m cli.main run --mode paper --broker mock --symbol AAPL --qty 1 --side buy --auto-approve

run-live:
	@echo "LIVE MODE DISABLED. SleepWealth is paper/simulation-only."
	@false
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -f audit.log

# ---- race harness ----------------------------------------------------
.PHONY: race race-series race-long gate modes

race:            ## one race, 1h window
	python -m cli.race run --duration 1h

race-series:     ## four races with cross-learning between each
	python -m cli.race series --races 4 --duration 30m

race-long:       ## one long race
	python -m cli.race run --duration 1d

gate:            ## evaluate the pre-live gate
	python -m cli.race gate

modes:           ## show the mode stack
	python -m cli.race modes
