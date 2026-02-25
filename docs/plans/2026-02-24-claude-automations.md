# Claude Automations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 5 Claude Code automations to the eToro trading toolkit: two protective/quality hooks, a SQLite MCP server, a performance-report skill, and a trade-journal subagent.

**Architecture:** Project-level `.claude/settings.json` drives hooks via shell scripts in `.claude/hooks/`. Skills live in `.claude/skills/`. SQLite MCP registered via CLI. All config is project-scoped (not global).

**Tech Stack:** Claude Code hooks (PreToolUse/PostToolUse), bash shell scripts, uvx/mcp-server-sqlite, Python 3.12.2, pytest

---

### Task 1: protect-env.sh hook script

**Files:**
- Create: `.claude/hooks/protect-env.sh`

**Step 1: Create the hook script**

```bash
#!/usr/bin/env bash
# Claude Code PreToolUse hook — blocks edits to .env files
# Receives tool input as JSON on stdin
# Exit 0 = allow, exit 2 = block

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null)

# Allow if no file_path detected
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Block edits to .env (but not .env.example or .env.sample)
if [[ "$FILE_PATH" == *".env" ]] || [[ "$FILE_PATH" == *"/.env" ]]; then
    echo "BLOCKED: .env edits are protected to guard API keys and trading mode." >&2
    echo "Edit .env manually in your terminal." >&2
    exit 2
fi

exit 0
```

**Step 2: Make executable**

```bash
chmod +x .claude/hooks/protect-env.sh
```

**Step 3: Manual test — should block**

```bash
echo '{"file_path": "/Users/michalprusek/PycharmProjects/etoro/.env"}' | .claude/hooks/protect-env.sh
# Expected: exit code 2, stderr shows BLOCKED message
```

**Step 4: Manual test — should allow**

```bash
echo '{"file_path": "/Users/michalprusek/PycharmProjects/etoro/.env.example"}' | .claude/hooks/protect-env.sh
# Expected: exit code 0, no output
echo '{"file_path": "/Users/michalprusek/PycharmProjects/etoro/src/api/client.py"}' | .claude/hooks/protect-env.sh
# Expected: exit code 0
```

---

### Task 2: run-tests.sh hook script

**Files:**
- Create: `.claude/hooks/run-tests.sh`

**Step 1: Create the hook script**

```bash
#!/usr/bin/env bash
# Claude Code PostToolUse hook — runs pytest after edits to Python files
# Receives tool input as JSON on stdin
# Always exits 0 (PostToolUse hooks should not block)

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null)

# Only trigger for Python files in src/ or tests/
if [[ "$FILE_PATH" != *.py ]]; then
    exit 0
fi

if [[ "$FILE_PATH" != *"/src/"* ]] && [[ "$FILE_PATH" != *"/tests/"* ]]; then
    exit 0
fi

echo "🧪 Auto-running tests after edit to $(basename "$FILE_PATH")..."
cd "$PROJECT_ROOT" && python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -25

exit 0
```

**Step 2: Make executable**

```bash
chmod +x .claude/hooks/run-tests.sh
```

**Step 3: Manual test — should run tests**

```bash
echo '{"file_path": "/Users/michalprusek/PycharmProjects/etoro/src/trading/risk.py"}' | .claude/hooks/run-tests.sh
# Expected: pytest output, exit 0
```

**Step 4: Manual test — should skip**

```bash
echo '{"file_path": "/Users/michalprusek/PycharmProjects/etoro/README.md"}' | .claude/hooks/run-tests.sh
# Expected: no output, exit 0
```

---

### Task 3: .claude/settings.json with hooks wired up

**Files:**
- Create: `.claude/settings.json`

**Step 1: Create settings file**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/protect-env.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/run-tests.sh"
          }
        ]
      }
    ]
  }
}
```

**Step 2: Validate JSON**

```bash
python3 -c "import json; json.load(open('.claude/settings.json')); print('JSON valid')"
# Expected: JSON valid
```

---

### Task 4: SQLite MCP server

**Files:** None (CLI registration, stored in `~/.claude/`)

**Step 1: Register SQLite MCP**

```bash
claude mcp add sqlite -s project -- uvx mcp-server-sqlite --db-path /Users/michalprusek/PycharmProjects/etoro/data/etoro.db
```

The `-s project` flag scopes it to this project only.

**Step 2: Verify registration**

```bash
claude mcp list
# Expected: sqlite listed with project scope
```

**Step 3: Smoke-test (next Claude session)**

In a new Claude session, ask: "List all tables in the SQLite database" — Claude should use the MCP tool and return the 6 table names from `etoro.db`.

---

### Task 5: performance-report skill

**Files:**
- Create: `.claude/skills/performance-report/SKILL.md`

**Step 1: Create skill file**

```markdown
---
name: performance-report
description: >
  Generate a trading performance report from the SQLite trade log.
  Calculates win rate, average realized R:R, best/worst trades by symbol,
  total fees paid, and flags CFD positions held >14 days (fee drag risk).
  Use when the user asks for a performance review, P&L summary, or trade stats.
---

# Performance Report

Generate a comprehensive trading performance report using the local SQLite database.

## Step 1 — Check trade history

```bash
python3 cli.py history
```

## Step 2 — Query key metrics from the DB

Run this Python snippet to compute the report:

```python
import sqlite3, os
from datetime import datetime, timedelta

os.environ.setdefault('TRADING_MODE', 'real')
db_path = 'data/etoro.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Trade log summary
trades = conn.execute("""
    SELECT symbol, direction, amount, open_rate, created_at, status
    FROM trade_log
    ORDER BY created_at DESC
    LIMIT 100
""").fetchall()

# Position closes (realized P&L)
closes = conn.execute("""
    SELECT symbol, net_profit, close_reason, closed_at
    FROM position_closes
    ORDER BY closed_at DESC
""").fetchall()

# Daily P&L
daily = conn.execute("""
    SELECT date, daily_pnl, cumulative_pnl
    FROM daily_pnl
    ORDER BY date DESC
    LIMIT 30
""").fetchall()

conn.close()

# Compute stats
if closes:
    profits = [c['net_profit'] for c in closes if c['net_profit'] is not None]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    win_rate = len(wins) / len(profits) * 100 if profits else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    total_pnl = sum(profits)
    best = max(profits) if profits else 0
    worst = min(profits) if profits else 0
    print(f"Closed trades: {len(profits)}")
    print(f"Win rate:      {win_rate:.1f}%")
    print(f"Avg win:       ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}")
    print(f"Total P&L:     ${total_pnl:.2f}")
    print(f"Best trade:    ${best:.2f} | Worst: ${worst:.2f}")
else:
    print("No closed trades found in position_closes table.")

print(f"\nRecent opens (trade_log): {len(trades)}")
for t in trades[:5]:
    print(f"  {t['symbol']} {t['direction']} ${t['amount']} @ {t['open_rate']} [{t['created_at'][:10]}]")
```

## Step 3 — Live portfolio P&L

```bash
python3 cli.py portfolio
```

## Step 4 — Present report

Format the output as a Rich table or markdown summary:

| Metric | Value |
|--------|-------|
| Win Rate | X% |
| Avg Win | $X |
| Avg Loss | $X |
| Total Realized P&L | $X |
| Open Positions | X |

Flag any CFD positions open >14 days as ⚠️ (overnight fee drag risk per CLAUDE.md).

Flag any position without SL/TSL — give the exact Chandelier stop value from:
```bash
python3 cli.py market analyze SYMBOL
```
```

**Step 2: Verify skill file is valid**

```bash
python3 -c "
import re
content = open('.claude/skills/performance-report/SKILL.md').read()
assert 'name: performance-report' in content
assert 'performance-report' in content
print('Skill file OK')
"
```

---

### Task 6: trade-journal subagent

**Files:**
- Create: `.claude/agents/trade-journal.md`

**Step 1: Create agent file**

```markdown
---
name: trade-journal
description: >
  Use this agent after closing a position to record outcome analysis.
  Compares planned vs actual exit, classifies outcome type (target hit /
  SL hit / manual close), and saves a lesson to the memories table.
  Triggered by close confirmations or when the user asks to journal a trade.
model: haiku
color: purple
tools: ["Bash", "Read", "Grep"]
---

You are a Trade Journal agent for an eToro portfolio. After a position closes,
your job is to analyze the trade outcome and record a lesson to the memories table.

## Your Process

### Step 1 — Identify the closed trade

Ask the user for the symbol if not provided. Then query the trade log:

```bash
python3 cli.py history
```

Look for recent entries matching the symbol.

### Step 2 — Query the position_closes table

```python
import sqlite3
conn = sqlite3.connect('data/etoro.db')
conn.row_factory = sqlite3.Row
closes = conn.execute("""
    SELECT symbol, net_profit, close_reason, closed_at, position_id
    FROM position_closes
    WHERE symbol = ?
    ORDER BY closed_at DESC
    LIMIT 3
""", (symbol.upper(),)).fetchall()
for c in closes:
    print(dict(c))
conn.close()
```

### Step 3 — Classify the outcome

| Outcome | Criteria |
|---------|----------|
| **Target hit** | net_profit > 0, close_reason = "manual" or "TP" |
| **SL hit** | net_profit < 0, close_reason = "SL" or "TSL" |
| **Manual close (profit)** | net_profit > 0, user-initiated |
| **Manual close (loss)** | net_profit < 0, user-initiated |
| **Time exit** | Held >30 days, fee drag |

### Step 4 — Save lesson to memories

```bash
python3 cli.py memory add lesson "SYMBOL: [Outcome type]. Entry $X → Exit $X. Net P&L $X ([+/-]%). Setup: [what worked or failed]. Lesson: [one actionable takeaway]."
```

Example:
```bash
python3 cli.py memory add lesson "NVDA: Target hit. Entry $890 → Exit $940. Net +$120 (+5.3%). Setup: GOLDEN MA alignment + RVOL 2.1. Lesson: High RVOL + golden cross entries work well on momentum stocks."
```

### Step 5 — Output a 3-line trade card

```
📋 Trade Journal — SYMBOL [DATE]
Entry: $X → Exit: $X | Net: +/-$X (+/-X%) | Outcome: [type]
Lesson saved: "[first 80 chars of lesson]"
```

## Notes

- If no close data found in DB, use the information the user provides directly
- Keep lessons concise and actionable (1-2 sentences)
- Always save the lesson — even for losses, especially for losses
```

**Step 2: Verify agent file is valid YAML header**

```bash
python3 -c "
content = open('.claude/agents/trade-journal.md').read()
assert 'name: trade-journal' in content
assert 'model: haiku' in content
print('Agent file OK')
"
```

---

### Task 7: Commit everything

**Step 1: Stage all new files**

```bash
git add .claude/settings.json .claude/hooks/ .claude/skills/ .claude/agents/trade-journal.md docs/
```

**Step 2: Verify staged files**

```bash
git status
# Expected: 6-7 new files staged
```

**Step 3: Commit**

```bash
git commit -m "feat: add Claude Code automations — hooks, SQLite MCP, performance skill, trade journal agent"
```
