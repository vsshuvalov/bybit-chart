# Makefile for Bybit Chart Platform
# Common development tasks

.PHONY: help test test-fast test-watch lint format benchmark clean install

# Python interpreter
PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff

help:
	@echo "Bybit Chart Platform - Development Tasks"
	@echo ""
	@echo "Available targets:"
	@echo "  make install       - Install dependencies"
	@echo "  make test          - Run all tests"
	@echo "  make test-fast     - Run tests without slow ones"
	@echo "  make test-watch    - Run tests in watch mode"
	@echo "  make lint          - Run linting checks"
	@echo "  make format        - Format code"
	@echo "  make benchmark     - Run analytics benchmarks"
	@echo "  make clean         - Remove build artifacts"
	@echo ""

install:
	@echo "Installing dependencies..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		pip install -r deploy/dependencies/darwin-arm64/requirements.lock; \
	else \
		pip install -r deploy/dependencies/linux-x86_64/requirements.lock; \
	fi
	@echo "✅ Dependencies installed"

test:
	@echo "Running all tests..."
	$(PYTEST) tests/ -v
	@echo "✅ Tests passed"

test-fast:
	@echo "Running fast tests..."
	$(PYTEST) tests/ -v -m "not slow"
	@echo "✅ Fast tests passed"

test-watch:
	@echo "Running tests in watch mode..."
	$(PYTEST) tests/ -v --looponfail

test-coverage:
	@echo "Running tests with coverage..."
	$(PYTEST) tests/ --cov=packages --cov=contracts --cov-report=html --cov-report=term
	@echo "✅ Coverage report generated in htmlcov/"

lint:
	@echo "Running linting checks..."
	$(RUFF) check .
	@echo "✅ No linting issues"

format:
	@echo "Formatting code..."
	$(RUFF) format .
	@echo "✅ Code formatted"

format-check:
	@echo "Checking code format..."
	$(RUFF) format --check .
	@echo "✅ Code format OK"

benchmark:
	@echo "Running analytics benchmarks..."
	@$(PYTHON) -c "import sys; sys.path.insert(0, '.'); from packages.analytics.benchmark import main; main()"

clean:
	@echo "Cleaning build artifacts..."
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "✅ Clean complete"

# Git shortcuts
git-status:
	@git status --short

git-log:
	@git log --oneline -10

# ADR shortcuts
adr-list:
	@echo "Architecture Decision Records:"
	@ls -1 docs/adr/ADR-*.md | sed 's/docs\/adr\//  /'

# CI simulation
ci:
	@echo "Simulating CI pipeline..."
	@make format-check
	@make lint
	@make test
	@echo "✅ CI checks passed"

# Quick validation before commit
pre-commit: format lint test-fast
	@echo "✅ Ready to commit"

# Development server (if applicable)
run-api:
	@echo "Starting API server..."
	@$(PYTHON) -m packages.api.app

# Database commands (if needed)
db-init:
	@echo "Initializing database..."
	@psql -U postgres -f deploy/postgres/init_schema.sql

# Deployment helpers
deploy-check:
	@echo "Checking deployment readiness..."
	@make format-check
	@make lint
	@make test
	@echo "✅ Deployment checks passed"

# Analytics specific
analytics-readme:
	@cat packages/analytics/README.md

# Show project stats
stats:
	@echo "Project Statistics"
	@echo "=================="
	@echo "Python files:"
	@find . -name "*.py" -not -path "./.venv/*" | wc -l | xargs echo "  "
	@echo "Lines of code:"
	@find . -name "*.py" -not -path "./.venv/*" | xargs wc -l | tail -1
	@echo "Test files:"
	@find tests -name "test_*.py" | wc -l | xargs echo "  "
	@echo "ADR files:"
	@ls -1 docs/adr/ADR-*.md 2>/dev/null | wc -l | xargs echo "  "
	@echo ""
	@echo "Git status:"
	@git log --oneline -1
	@echo ""
