#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend"

if [[ ! -x venv/bin/python ]]; then
  echo "Error: backend/venv not found. Run scripts/setup-python.sh first." >&2
  exit 1
fi

read -e -r -p "Drag the song file here (or paste path), then Enter: " RAW_PATH

# Trim surrounding whitespace and strip wrapping quotes (Terminal drag often
# wraps paths in single quotes when they contain spaces or parens).
SONG="${RAW_PATH#"${RAW_PATH%%[![:space:]]*}"}"
SONG="${SONG%"${SONG##*[![:space:]]}"}"
if [[ ${#SONG} -ge 2 ]]; then
  first="${SONG:0:1}"
  last="${SONG: -1}"
  if { [[ $first == "'" && $last == "'" ]] || [[ $first == '"' && $last == '"' ]]; }; then
    SONG="${SONG:1:${#SONG}-2}"
  fi
fi

# Terminal drag-and-drop backslash-escapes spaces/parens; un-escape so the
# resulting path is a real filesystem path rather than a literal-with-backslashes.
SONG="${SONG//\\ / }"
SONG="${SONG//\\(/(}"
SONG="${SONG//\\)/)}"
SONG="${SONG//\\&/&}"
SONG="${SONG//\\\'/\'}"

if [[ ! -f $SONG ]]; then
  echo "Error: file not found: $SONG" >&2
  exit 1
fi

exec ./venv/bin/python test_e2e_accuracy.py "$SONG" --show-all "$@"
