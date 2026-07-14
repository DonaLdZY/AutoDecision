#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.dev-state"
PID_FILE="$STATE_DIR/pids.sh"
KNOWN_PORTS=(18101 18103 18104 18080 5173)

listening_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
  fi
}

descendant_pids() {
  local parent="$1"
  local child
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi
  for child in $(pgrep -P "$parent" 2>/dev/null || true); do
    descendant_pids "$child"
    echo "$child"
  done
}

stop_process_tree() {
  local pid="$1"
  local descendants all_pids still_alive=""
  if [[ -z "$pid" ]] || ! kill -0 "$pid" >/dev/null 2>&1; then
    return 1
  fi
  descendants="$(descendant_pids "$pid" || true)"
  all_pids="$pid $descendants"
  # shellcheck disable=SC2086
  kill $all_pids >/dev/null 2>&1 || true
  sleep 0.5
  local candidate
  for candidate in $all_pids; do
    if kill -0 "$candidate" >/dev/null 2>&1; then
      still_alive="$still_alive $candidate"
    fi
  done
  if [[ -n "$still_alive" ]]; then
    # shellcheck disable=SC2086
    kill -9 $still_alive >/dev/null 2>&1 || true
  fi
  return 0
}

cleanup_port() {
  local port="$1"
  local pids
  pids="$(listening_pids "$port" || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Stopping orphan listener(s) on port $port: $(echo "$pids" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $pids >/dev/null 2>&1 || true
  sleep 0.3
  pids="$(listening_pids "$port" || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids >/dev/null 2>&1 || true
  fi
}

if [[ -f "$PID_FILE" ]]; then
  if source "$PID_FILE" >/dev/null 2>&1; then
    for row in "${PROCESSES[@]}"; do
      IFS='|' read -r name pid port workdir cmd <<< "$row"
      if stop_process_tree "${pid:-}"; then
        echo "Stopped: $name (PID $pid)"
      else
        echo "Not running: $name (PID ${pid:-N/A})"
      fi
    done
  else
    echo "Could not parse state file; cleaning known ports instead: $PID_FILE"
  fi
  rm -f "$PID_FILE"
else
  echo "State file not found: $PID_FILE"
fi

for port in "${KNOWN_PORTS[@]}"; do
  cleanup_port "$port"
done

echo "AutoDecision development services stopped."
