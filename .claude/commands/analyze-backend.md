# Backend Analysis Pipeline

Run the full Python backend analysis pipeline. MANDATORY after any changes to src/*.py files.

## Steps (run ALL, do not skip)

### 1. Formatting
```bash
cd /home/claude/projects/AI_Polyglot_Kit && ruff format --check src/ tests/
```
If fails: run `ruff format src/ tests/` to fix, then re-check.

### 2. Linting
```bash
ruff check src/ tests/ --output-format=concise
```
Fix ALL errors. No warnings allowed in new code.

### 3. Type Checking
```bash
mypy --strict src/ --ignore-missing-imports
```
Fix all type errors. Use `# type: ignore[specific-code]` ONLY for third-party library issues, never for own code.

### 4. Security Analysis
```bash
bandit -r src/ -ll -ii
```
No medium or high severity findings allowed. Fix or document with `# nosec B{code}` + justification comment.

### 5. Complexity Check
```bash
radon cc src/ -a -nc
```
No function/method above CC=10. Refactor complex functions.

### 6. Dead Code Detection
```bash
vulture src/ --min-confidence 80
```
Remove unused code. If false positive — add to vulture whitelist.

### 7. Tests
```bash
pytest tests/ -v --tb=short --cov=src --cov-report=term-missing
```
All tests must pass. Coverage target: >80% for new modules.

## Report Format
After running all steps, report:
- PASS/FAIL for each step
- Number of issues found and fixed
- Any remaining warnings with justification
