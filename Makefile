.PHONY: test test-all test-unit test-integration test-llm lint format typecheck security complexity dead-code audit secrets check-all clean

# === TESTING ===
test:             ## Run tests (exclude real LLM calls)
	pytest tests/ -m "not llm_real" --cov=src/context --cov-fail-under=80

test-all:         ## Run ALL tests including real LLM calls
	pytest tests/ --cov=src/context

test-unit:        ## Run unit tests only
	pytest tests/unit/ -m "not llm_real"

test-integration: ## Run integration tests only
	pytest tests/integration/ -m "not llm_real"

test-llm:         ## Run real LLM API tests (manual, costs tokens)
	pytest tests/ -m llm_real -v

# === CODE QUALITY ===
lint:             ## Check code style
	ruff check src/context/ tests/

format:           ## Auto-format code
	ruff format src/context/ tests/

typecheck:        ## Type check with mypy
	mypy --strict src/context/

# === SECURITY ===
security:         ## Run bandit security scan
	bandit -r src/context/ -ll

audit:            ## Check dependencies for CVEs
	pip-audit

secrets:          ## Scan for leaked secrets
	detect-secrets scan --list-all-secrets

# === CODE METRICS ===
complexity:       ## Check cyclomatic complexity (max CC=10)
	radon cc src/context/ -a -nc

dead-code:        ## Find unused code
	vulture src/context/ --min-confidence 80

# === COMBINED ===
check-all: lint typecheck security complexity test  ## Run ALL checks (pre-commit equivalent)
	@echo "All checks passed!"

clean:            ## Clean build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help:             ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
