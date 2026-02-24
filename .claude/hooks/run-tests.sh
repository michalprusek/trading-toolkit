#!/usr/bin/env bash
# Claude Code PostToolUse hook — runs pytest after edits to Python files
# Receives tool input as JSON on stdin
# Always exits 0 (PostToolUse hooks must not block)

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tool_input = data.get('tool_input', {})
    print(tool_input.get('file_path', ''))
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
