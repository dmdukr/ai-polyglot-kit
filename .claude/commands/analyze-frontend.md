# Frontend Analysis Pipeline (Chrome Extension)

Run the full JavaScript analysis pipeline. MANDATORY after any changes to extension/*.js files.

## Steps

### 1. ESLint
```bash
cd /home/claude/projects/AI_Polyglot_Kit && npx eslint extension/*.js --no-error-on-unmatched-pattern
```
Fix all errors and warnings.

### 2. Manifest Validation
Read `extension/manifest.json` and verify:
- manifest_version is 3
- All referenced files exist (js, icons)
- Permissions are minimal (no unnecessary permissions)
- host_permissions match only required origins

### 3. Security Review (manual)
Check for:
- No dynamic code execution (no string-to-code patterns)
- All fetch() calls use proper error handling
- No hardcoded secrets or tokens
- Content script: no XSS vectors (text-only DOM manipulation)
- Background: proper message validation (check msg.action before processing)

### 4. Consistency Check
- All console.log use `[APK:xx]` prefix (bg/cs/popup)
- All chrome API calls have proper error handling
- sendResponse is always called (no hanging promises)
- `return true` for async message handlers

## Report Format
- PASS/FAIL for each step
- List of issues found and fixed
