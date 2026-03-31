# Pre-Commit Check Pipeline

MANDATORY before every git commit. Quick subset of full analysis — catches obvious issues.

## Steps (ALL must pass)

```bash
cd /home/claude/projects/AI_Polyglot_Kit

# 1. Format check (no auto-fix — just verify)
ruff format --check src/ tests/

# 2. Lint (errors only, no warnings)
ruff check src/ tests/ --select E,F,W --output-format=concise

# 3. Type check (strict)
mypy --strict src/ --ignore-missing-imports 2>&1 | tail -5

# 4. Security scan (high severity only)
bandit -r src/ -ll -ii --quiet

# 5. Secrets scan
detect-secrets scan --all-files --exclude-files '\.git|__pycache__|\.pyc|\.wav|\.png' 2>&1 | grep -c '"is_secret": true' || echo "0 secrets found"

# 6. Tests (fast — unit only)
pytest tests/unit/ -v --tb=short -q 2>&1 | tail -10
```

## Decision
- ALL 6 checks pass → OK to commit
- ANY check fails → FIX before committing, re-run pipeline
- Never use `--no-verify` to skip hooks
