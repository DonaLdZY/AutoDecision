#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.dev-state/logs"
NAME=""
LINES=80
FOLLOW=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --follow|-f)
      FOLLOW=1
      shift
      ;;
    --lines|-n)
      LINES="${2:-}"
      if [[ -z "$LINES" ]]; then
        echo "$1 requires a number." >&2
        exit 2
      fi
      shift 2
      ;;
    --help|-h)
      echo "Usage: ./scripts/dev-logs.sh [service-name] [--lines N] [--follow]"
      exit 0
      ;;
    *)
      if [[ -n "$NAME" ]]; then
        echo "Unexpected argument: $1" >&2
        exit 2
      fi
      NAME="$1"
      shift
      ;;
  esac
done

if [[ ! -d "$LOG_DIR" ]]; then
  echo "Log directory not found: $LOG_DIR"
  exit 0
fi

if [[ -z "$NAME" ]]; then
  echo "Available logs:"
  find "$LOG_DIR" -maxdepth 1 -type f -name '*.log' -print | sort | while IFS= read -r path; do
    basename "$path"
  done
  echo
  echo "Example: ./scripts/dev-logs.sh gateway-api --follow"
  exit 0
fi

paths=()
for path in "$LOG_DIR/$NAME.log" "$LOG_DIR/$NAME.stdout.log" "$LOG_DIR/$NAME.stderr.log"; do
  if [[ -f "$path" ]]; then
    paths+=("$path")
  fi
done

if [[ "${#paths[@]}" -eq 0 ]]; then
  echo "No log files found for: $NAME" >&2
  exit 1
fi

if [[ "$FOLLOW" -eq 1 ]]; then
  tail -n "$LINES" -f "${paths[@]}"
else
  tail -n "$LINES" "${paths[@]}"
fi
