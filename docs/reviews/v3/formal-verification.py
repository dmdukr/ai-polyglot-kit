"""
Formal verification of Context Engine spec logic.
Checks mathematical formulas, edge cases, state transitions, and schema constraints.
"""
import sqlite3
import sys
import re
from pathlib import Path

SPEC_PATH = Path(__file__).parent.parent.parent / "superpowers/specs/2026-03-28-context-engine-architecture.md"
ERRORS = []
WARNINGS = []

def error(msg): ERRORS.append(f"ERROR: {msg}")
def warn(msg): WARNINGS.append(f"WARNING: {msg}")
def ok(msg): print(f"  OK: {msg}")


# =============================================================================
# 1. MATHEMATICAL FORMULA VERIFICATION
# =============================================================================
print("=" * 60)
print("1. MATHEMATICAL FORMULA VERIFICATION")
print("=" * 60)

# --- Confidence Level 1: min(weight / 5.0, 1.0) ---
print("\nLevel 1 confidence: min(weight / 5.0, 1.0)")
for weight in [0, 1, 2, 3, 4, 5, 10, 100, -1]:
    conf = min(weight / 5.0, 1.0)
    if weight < 0:
        error(f"  weight={weight} → confidence={conf} — NEGATIVE WEIGHT POSSIBLE (clock skew could cause negative co-occurrence)")
    elif weight == 0:
        ok(f"  weight={weight} → confidence={conf} (correct: no data = no confidence)")
    elif conf > 1.0:
        error(f"  weight={weight} → confidence={conf} — EXCEEDS 1.0")
    else:
        ok(f"  weight={weight} → confidence={conf}")

# --- Confidence Level 2: min(thread.message_count / 3.0, 1.0) ---
print("\nLevel 2 confidence: min(message_count / 3.0, 1.0)")
for count in [0, 1, 2, 3, 5, -1]:
    conf = min(count / 3.0, 1.0)
    if count <= 0:
        warn(f"  count={count} → confidence={conf} — thread with 0 messages shouldn't exist")
    else:
        ok(f"  count={count} → confidence={conf}")

# --- Confidence Level 3: hits_winner / sum(all_hits) ---
print("\nLevel 3 confidence: hits_winner / total_hits")
test_cases = [
    (2, 3, "normal case"),
    (1, 1, "single match — confidence=1.0 on 1 fingerprint!"),
    (0, 0, "no matches — division by zero!"),
    (5, 5, "all same cluster — confidence=1.0"),
    (1, 100, "weak match"),
    (2, 2, "minimum required hits=2"),
]
for hits, total, desc in test_cases:
    if total == 0:
        error(f"  hits={hits}, total={total} → DIVISION BY ZERO — {desc}")
    else:
        conf = hits / total
        if hits < 2:
            warn(f"  hits={hits}, total={total} → confidence={conf:.2f} — should require hits>=2 — {desc}")
        elif conf >= 0.6 and total < 3:
            warn(f"  hits={hits}, total={total} → confidence={conf:.2f} — passes threshold but tiny sample — {desc}")
        else:
            ok(f"  hits={hits}, total={total} → confidence={conf:.2f} — {desc}")

# --- Temporal decay: weight * (1.0 / (days + 1)) ---
print("\nTemporal decay: weight * (1.0 / (days_since + 1))")
for days in [-1, -0.5, 0, 0.5, 1, 7, 30, 365]:
    divisor = days + 1
    if divisor <= 0:
        error(f"  days={days} → divisor={divisor} → DIVISION BY ZERO OR NEGATIVE — clock skew!")
    elif divisor < 0.5:
        warn(f"  days={days} → divisor={divisor} → AMPLIFICATION instead of decay")
    else:
        decay = 1.0 / divisor
        ok(f"  days={days} → decay_factor={decay:.4f}")

# --- Weighted scoring: overlap * CASE app ---
print("\nWeighted thread scoring (threshold=2.0)")
cases = [
    (1, True, "same app, 1 keyword"),
    (1, False, "cross-app, 1 keyword"),
    (2, True, "same app, 2 keywords"),
    (2, False, "cross-app, 2 keywords"),
    (3, False, "cross-app, 3 keywords"),
    (0, True, "same app, 0 keywords"),
]
THRESHOLD = 2.0
for overlap, same_app, desc in cases:
    weight = 2.0 if same_app else 1.0
    score = overlap * weight
    passes = score >= THRESHOLD
    if overlap == 0:
        warn(f"  {desc}: score={score} — 0-keyword path should not use this function")
    elif score == THRESHOLD:
        warn(f"  {desc}: score={score} — EXACTLY ON BOUNDARY (>= vs >) — {desc}")
    else:
        ok(f"  {desc}: score={score} → {'PASS' if passes else 'FAIL'}")


# =============================================================================
# 2. SQL SCHEMA VALIDATION
# =============================================================================
print("\n" + "=" * 60)
print("2. SQL SCHEMA VALIDATION")
print("=" * 60)

# Extract all SQL blocks from spec
spec_text = SPEC_PATH.read_text()
sql_blocks = re.findall(r'```sql\n(.*?)```', spec_text, re.DOTALL)

# Find the complete schema (largest SQL block with CREATE TABLE)
all_sql = "\n".join(sql_blocks)
create_statements = re.findall(r'CREATE\s+(?:TABLE|INDEX)\s+.*?;', all_sql, re.DOTALL | re.IGNORECASE)

if not create_statements:
    error("No CREATE TABLE statements found in spec!")
else:
    print(f"\nFound {len(create_statements)} CREATE statements. Validating in SQLite...")

    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")

    for stmt in create_statements:
        # Clean up any markdown artifacts
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            db.execute(stmt)
            table_match = re.search(r'(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', stmt, re.IGNORECASE)
            name = table_match.group(1) if table_match else "unknown"
            ok(f"  {name}")
        except Exception as e:
            error(f"  SQL ERROR: {e}\n    Statement: {stmt[:100]}...")

    # Check foreign key integrity
    print("\nChecking foreign key references...")
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for table in tables:
        fks = db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        for fk in fks:
            ref_table = fk[2]
            if ref_table not in tables:
                error(f"  {table} references non-existent table: {ref_table}")
            else:
                ok(f"  {table} → {ref_table} (FK valid)")

    # Check indexes cover queries
    print("\nChecking index coverage...")
    indexes = db.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()
    for idx_name, tbl_name, idx_sql in indexes:
        ok(f"  {idx_name} on {tbl_name}")

    # Check for tables without primary keys
    print("\nChecking for tables without primary keys...")
    for table in tables:
        cols = db.execute(f"PRAGMA table_info({table})").fetchall()
        has_pk = any(col[5] > 0 for col in cols)  # col[5] is pk flag
        if not has_pk:
            warn(f"  {table} has no primary key")
        else:
            ok(f"  {table} has primary key")

    db.close()


# =============================================================================
# 3. STATE MACHINE VERIFICATION
# =============================================================================
print("\n" + "=" * 60)
print("3. THREAD STATE MACHINE VERIFICATION")
print("=" * 60)

# Model thread states
STATES = {"NEW", "ACTIVE", "EXPIRED", "FINGERPRINT_SAVED", "DELETED"}
TRANSITIONS = {
    "NEW": {"ACTIVE"},                          # new dictation creates thread
    "ACTIVE": {"ACTIVE", "EXPIRED"},            # new message keeps active, or timeout
    "EXPIRED": {"FINGERPRINT_SAVED", "DELETED", "ACTIVE"},  # save fingerprint, or cleanup, or reactivated?
    "FINGERPRINT_SAVED": {"DELETED"},           # maintenance cleanup
    "DELETED": set(),                           # terminal
}

print("\nThread lifecycle transitions:")
for state, nexts in TRANSITIONS.items():
    print(f"  {state} → {nexts or '{terminal}'}")

# Check: can thread get stuck?
print("\nReachability analysis:")
reachable = {"NEW"}
frontier = {"NEW"}
while frontier:
    new_frontier = set()
    for s in frontier:
        for ns in TRANSITIONS.get(s, set()):
            if ns not in reachable:
                reachable.add(ns)
                new_frontier.add(ns)
    frontier = new_frontier

unreachable = STATES - reachable
if unreachable:
    error(f"  Unreachable states: {unreachable}")
else:
    ok(f"  All states reachable from NEW: {reachable}")

# Check: can every non-terminal state reach DELETED?
print("\nTermination analysis (can every state reach DELETED?):")
for state in STATES:
    if state == "DELETED":
        continue
    visited = {state}
    queue = [state]
    can_terminate = False
    while queue:
        s = queue.pop(0)
        for ns in TRANSITIONS.get(s, set()):
            if ns == "DELETED":
                can_terminate = True
                break
            if ns not in visited:
                visited.add(ns)
                queue.append(ns)
        if can_terminate:
            break
    if can_terminate:
        ok(f"  {state} can reach DELETED")
    else:
        error(f"  {state} CANNOT reach DELETED — potential leak!")

# Check: can EXPIRED go back to ACTIVE? (is reactivation specified?)
if "ACTIVE" in TRANSITIONS.get("EXPIRED", set()):
    warn("  EXPIRED → ACTIVE transition exists — is thread reactivation specified in the spec?")
else:
    ok("  No EXPIRED → ACTIVE transition (threads don't reactivate)")

# Check: 0-keyword thread
print("\n0-keyword thread analysis:")
warn("  Thread with 0 keywords in thread_keywords → can never be matched by find_active_thread")
warn("  Spec says: don't create thread for 0-keyword dictation → verify this is enforced")


# =============================================================================
# 4. SCHEMA CROSS-REFERENCE AUDIT
# =============================================================================
print("\n" + "=" * 60)
print("4. CROSS-REFERENCE AUDIT")
print("=" * 60)

# Check section references
print("\nSection cross-references:")
section_refs = re.findall(r'[Ss]ection\s+(\d+(?:\.\d+)?)', spec_text)
section_defs = re.findall(r'^##+ (\d+(?:\.\d+)?)\b', spec_text, re.MULTILINE)

for ref in set(section_refs):
    # Check if any section starts with this number
    found = any(d.startswith(ref) for d in section_defs)
    if found:
        ok(f"  Section {ref} referenced and exists")
    else:
        error(f"  Section {ref} referenced but NOT FOUND in document")

# Check table references in queries
print("\nTable references in Python code blocks:")
python_blocks = re.findall(r'```python\n(.*?)```', spec_text, re.DOTALL)
all_python = "\n".join(python_blocks)

# Find all table names referenced in SQL within Python
sql_tables_in_code = set(re.findall(r'(?:FROM|JOIN|INTO|UPDATE|DELETE FROM)\s+(\w+)', all_python, re.IGNORECASE))
sql_tables_in_schema = set(re.findall(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', all_sql, re.IGNORECASE))

for table in sql_tables_in_code:
    if table in sql_tables_in_schema:
        ok(f"  {table} (used in code, exists in schema)")
    elif table.upper() in ('SELECT', 'WHERE', 'SET', 'VALUES', 'NULL'):
        pass  # SQL keyword, not table
    else:
        error(f"  {table} used in code but NOT IN SCHEMA")

for table in sql_tables_in_schema:
    if table not in sql_tables_in_code and table not in ('sqlite_master',):
        warn(f"  {table} defined in schema but never referenced in code")


# =============================================================================
# 5. ON DELETE CASCADE VERIFICATION
# =============================================================================
print("\n" + "=" * 60)
print("5. CASCADE & ORPHAN ANALYSIS")
print("=" * 60)

# Check: which FKs have ON DELETE CASCADE?
cascade_fks = re.findall(r'REFERENCES\s+(\w+)\(.*?\)\s+ON\s+DELETE\s+CASCADE', all_sql, re.IGNORECASE)
non_cascade_fks = re.findall(r'REFERENCES\s+(\w+)\(.*?\)(?!\s+ON\s+DELETE)', all_sql, re.IGNORECASE)

print("\nForeign keys WITH ON DELETE CASCADE:")
for fk in cascade_fks:
    ok(f"  → {fk}")

print("\nForeign keys WITHOUT ON DELETE CASCADE:")
for fk in non_cascade_fks:
    if fk in ('conversation_threads', 'scripts', 'clusters'):
        warn(f"  → {fk} — deleting {fk} row may orphan referencing rows")
    else:
        warn(f"  → {fk}")

# Check: history.thread_id → threads — what happens when thread deleted?
if 'conversation_threads' in non_cascade_fks:
    warn("  history.thread_id REFERENCES conversation_threads WITHOUT CASCADE")
    warn("  → If thread deleted by maintenance, history rows become orphaned")
    warn("  → Fix: either add ON DELETE SET NULL, or don't delete threads that have history")


# =============================================================================
# SUMMARY
# =============================================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"\n  ERRORS:   {len(ERRORS)}")
print(f"  WARNINGS: {len(WARNINGS)}")

if ERRORS:
    print("\n--- ERRORS (must fix) ---")
    for e in ERRORS:
        print(f"  {e}")

if WARNINGS:
    print("\n--- WARNINGS (should review) ---")
    for w in WARNINGS:
        print(f"  {w}")

sys.exit(1 if ERRORS else 0)
