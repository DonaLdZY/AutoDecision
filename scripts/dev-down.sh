#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.dev-state"
PID_FILE="$STATE_DIR/pids.sh"

if [[ ! -f "$PID_FILE" ]]; then
  echo "State file not found: $PID_FILE"
  echo "If processes still exist, check ports 18101/18102/18103/18104/18080/5173 manually."
  exit 0
fi

# shellcheck source=/dev/null
source "$PID_FILE"

if [[ "${#PROCESSES[@]}" -eq 0 ]]; then
  echo "State file is empty, removing it directly."
  rm -f "$PID_FILE"
  exit 0
fi

for row in "${PROCESSES[@]}"; do
  IFS='|' read -r name pid port workdir cmd <<< "$row"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.2
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    echo "Stopped: $name (PID $pid)"
  else
    echo "Not running: $name (PID ${pid:-N/A})"
  fi
done

rm -f "$PID_FILE"
echo "State file removed."
