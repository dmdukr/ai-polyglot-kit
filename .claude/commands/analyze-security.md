# Security Analysis Pipeline

Run after security-sensitive changes: auth, tokens, API keys, file I/O, network, user input handling.

## Steps

### 1. Bandit (Python SAST)
```bash
cd /home/claude/projects/AI_Polyglot_Kit && bandit -r src/ -f json -o /tmp/bandit-report.json -ll
cat /tmp/bandit-report.json | python3 -m json.tool | head -100
```
Zero tolerance for HIGH severity. MEDIUM requires documented justification.

### 2. Dependency Audit
```bash
pip-audit -r requirements.txt --desc
```
No known CVEs in dependencies. If unavoidable — document in SECURITY.md with mitigation.

### 3. Secrets Detection
```bash
detect-secrets scan --all-files --exclude-files '\.git|__pycache__|\.pyc|\.wav|\.png'
```
Zero secrets in code. API keys must come from .env or config.yaml (not committed).

### 4. OWASP Review (manual checklist)
Check modified code against:
- [ ] **Injection:** No string formatting in SQL/commands/shell exec
- [ ] **Auth:** Tokens stored securely (not in logs, not in plain config)
- [ ] **Sensitive data:** No PII in logs, telemetry anonymized
- [ ] **Input validation:** All external input (HTTP, config, clipboard) validated
- [ ] **Error handling:** Errors don't leak stack traces to users
- [ ] **Dependencies:** No unnecessary network calls, minimal permissions
- [ ] **File I/O:** Path traversal prevention, safe temp file handling
- [ ] **Crypto:** No custom crypto, use standard libraries

### 5. Silent Failure Hunting
Use superpowers:silent-failure-hunter agent to scan for:
- Empty catch blocks
- Exceptions caught and not logged
- Fallback values hiding errors
- Status codes ignored

## Report Format
- Severity/confidence for each finding
- Remediation action taken or justification for accept
