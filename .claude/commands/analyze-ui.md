# UI/UX Analysis Pipeline

Run after ANY changes to UI code (settings_ui.py, recording_overlay.py, tray_app.py, tk_host.py).
This pipeline has TWO parts: automated (on Linux) and manual (on Windows VM).

## Part 1: Automated Checks (Linux VM)

### 1. Code Review for UI Patterns
Verify all UI code follows these rules:
- All user-visible strings use `i18n.t()` — no hardcoded text
- All colors defined as constants (not inline hex)
- Dark/light theme: every custom color has both variants
- Widget naming: all interactive widgets have descriptive variable names
- Layout: consistent padding/margins (use 4/8/12/16 spacing scale)

### 2. Aqua Voice Design Compliance
Check that new UI elements match Aqua Voice style:
- **Color palette dark:** Background #1a1a2e → #16213e, Cards #0f3460, Accent #e94560/#533483
- **Color palette light:** Background #f8f9fa, Cards #ffffff, Accent #007AFF
- **Typography:** Clean sans-serif, hierarchy via weight not size (400/500/600)
- **Spacing:** 8px grid system, 16px section gaps, 12px inner padding
- **Components:** Rounded corners (8px), subtle shadows, toggle switches not checkboxes
- **Animations:** Subtle transitions for state changes (if applicable in tkinter)

### 3. Accessibility Code Check
- Tab order: widgets added in logical order (top→bottom, left→right)
- Focus indicators: visible focus ring on all interactive elements
- Contrast: text colors meet WCAG AA (4.5:1 for normal, 3:1 for large)
- No information conveyed by color alone (use icons/text too)

## Part 2: Windows VM Manual Testing (after build)

SSH to 192.168.12.6 and run these checks:

### 4. Microsoft Accessibility Insights
```
# On Windows VM — run Accessibility Insights for Windows
# Select AI Polyglot Kit window → FastPass → review results
```
- All controls must have Name property
- Tab order must be logical
- No errors in FastPass scan

### 5. Colour Contrast Analyser (CCA)
Test every text/background combination in:
- Dark theme
- Light theme
- High Contrast mode (Windows Settings → Accessibility → Contrast themes)

### 6. DPI Scaling
Test at 100%, 125%, 150%:
- No clipped text
- No overlapping controls
- Proper window resizing

### 7. Visual Regression
Take screenshots of all dialogs/states, compare with baseline.

## Report Format
- PASS/FAIL for each check
- Screenshots of any issues (save to /tmp/share/AI/ui-review/)
- Accessibility Insights summary
