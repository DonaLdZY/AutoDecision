#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/.dev-state/pids.sh"

health_url() {
  case "$1" in
    autorealize-api) echo "http://127.0.0.1:18101/health" ;;
    algoevolve-api) echo "http://127.0.0.1:18103/health" ;;
    autoreport-api) echo "http://127.0.0.1:18104/health" ;;
    gateway-api) echo "http://127.0.0.1:18080/api/health" ;;
    frontend-ui) echo "http://127.0.0.1:5173" ;;
    *) echo "" ;;
  esac
}

listener_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u | paste -sd, -
  fi
}

http_status() {
  local url="$1"
  local status
  status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || true)"
  if [[ -z "$status" || "$status" == "000" ]]; then
    echo "not-ready"
  else
    echo "$status"
  fi
}

if [[ ! -f "$PID_FILE" ]]; then
  echo "State file not found: $PID_FILE"
  echo "Run ./scripts/dev-up.sh first."
  exit 0
fi

# shellcheck source=/dev/null
source "$PID_FILE"

echo "AutoDecision dev services"
echo "Root: $ROOT_DIR"
echo
printf '%-20s %-8s %-9s %-14s %-10s\n' "SERVICE" "PID" "PROCESS" "LISTENER PID" "HEALTH"
printf '%-20s %-8s %-9s %-14s %-10s\n' "--------------------" "--------" "---------" "--------------" "----------"

for row in "${PROCESSES[@]}"; do
  IFS='|' read -r name pid port workdir cmd <<< "$row"
  process_state="dead"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    process_state="alive"
  fi
  listeners="$(listener_pids "$port" || true)"
  [[ -n "$listeners" ]] || listeners="-"
  url="$(health_url "$name")"
  status="-"
  [[ -z "$url" ]] || status="$(http_status "$url")"
  printf '%-20s %-8s %-9s %-14s %-10s\n' "$name" "$pid" "$process_state" "$listeners" "$status"
done

echo
echo "Logs: ./scripts/dev-logs.sh gateway-api --follow"
echo "Stop: ./scripts/dev-down.sh"
