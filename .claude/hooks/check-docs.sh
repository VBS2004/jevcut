#!/usr/bin/env bash
# Stop hook: before Claude ends a turn, check that the docs still describe the code.
# Exit 2 hands stderr back to Claude and keeps the turn going. It fires once per stop:
# when stop_hook_active is set Claude is already answering a nudge, and a problem it
# can't fix must not loop forever.
input=$(cat)
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -x .venv/bin/python ] || exit 0
out=$(.venv/bin/python scripts/check_docs.py 2>&1) && exit 0
printf 'The docs no longer match the code. Update them before finishing, or tell the user why not:\n%s\n' "$out" >&2
exit 2
