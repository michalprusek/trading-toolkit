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
