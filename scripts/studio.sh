#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_PYTHON="${AUTODECISION_PYTHON_EXECUTABLE:-${AUTODECISION_PYTHON:-}}"
if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
  # Windows may advertise a python3 Store alias that exists but cannot execute.
  for CANDIDATE_PYTHON in python3 python; do
    if command -v "$CANDIDATE_PYTHON" >/dev/null 2>&1 && "$CANDIDATE_PYTHON" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
      BOOTSTRAP_PYTHON="$CANDIDATE_PYTHON"
      break
    fi
  done
fi
if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
  echo 'Activate the project Python environment or set AUTODECISION_PYTHON_EXECUTABLE.' >&2
  exit 1
fi
exec "$BOOTSTRAP_PYTHON" "$SCRIPT_DIR/studio.py" "$@"
