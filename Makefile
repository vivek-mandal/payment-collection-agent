# Makefile — convenience shortcuts.
#
# Requires: uv (https://docs.astral.sh/uv/)
#   Windows: winget install astral-sh.uv
#   Mac/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
#
# On Windows without make, run the commands on the right-hand side directly.
#
# Usage:
#   make install       create venv + install all deps
#   make run           start the interactive CLI
#   make eval          run the full e2e test suite
#   make lint          check code style (ruff)
#   make fmt           auto-fix code style

.PHONY: install install-dev run eval lint fmt

install:
	uv sync

install-dev:
	uv sync --extra dev

run:
	uv run python -m apps.cli

eval:
	uv run pytest tests/e2e -v -s

lint:
	uv run ruff check src apps tests

fmt:
	uv run ruff format src apps tests && uv run ruff check --fix src apps tests

accounts:
	uv run python scripts/fetch_test_accounts.py
