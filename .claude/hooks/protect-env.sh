#!/usr/bin/env bash
# Claude Code PreToolUse hook — blocks edits to .env files
# Receives tool input as JSON on stdin
# Exit 0 = allow, exit 2 = block

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

# Allow if no file_path detected
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Block edits to .env and common variants (.env.local, .env.production, etc.)
# Allow: .env.example, .env.sample, .env.template
BASENAME=$(basename "$FILE_PATH")
if [[ "$BASENAME" == ".env" ]] || [[ "$BASENAME" == .env.* ]] && [[ "$BASENAME" != ".env.example" ]] && [[ "$BASENAME" != ".env.sample" ]] && [[ "$BASENAME" != ".env.template" ]]; then
    echo "BLOCKED: .env edits are protected to guard API keys and trading mode." >&2
    echo "Edit .env manually in your terminal." >&2
    exit 2
fi

exit 0
