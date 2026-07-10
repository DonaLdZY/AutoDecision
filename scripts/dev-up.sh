#!/usr/bin/env bash
set -euo pipefail

FORCE=0
if [[ "${1:-}" == "--force" || "${1:-}" == "-f" ]]; then
  FORCE=1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.dev-state"
LOG_DIR="$STATE_DIR/logs"
PID_FILE="$STATE_DIR/pids.sh"

AUTOREALIZE_DIR="$ROOT_DIR/core/AutoRealize"
MLEVOLVE_DIR="$ROOT_DIR/core/MLEvolve-Alter"
AUTOREPORT_DIR="$ROOT_DIR/core/AutoReport"
GATEWAY_DIR="$ROOT_DIR/frontend/backend"
UI_DIR="$ROOT_DIR/frontend/ui"

mkdir -p "$STATE_DIR" "$LOG_DIR"

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "( sport = :$port )" | tail -n +2 | grep -q .
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port$"
    return $?
  fi
  return 1
}

start_service() {
  local name="$1"
  local workdir="$2"
  local port="$3"
  local cmd="$4"
  local logfile="$LOG_DIR/${name}.log"

  if port_in_use "$port" && [[ "$FORCE" -ne 1 ]]; then
    echo "Port $port is already in use. Use --force or run ./scripts/dev-down.sh first."
    exit 1
  fi

  (
    cd "$workdir"
    nohup bash -lc "$cmd" >"$logfile" 2>&1 &
    echo $! > "$STATE_DIR/.${name}.pid"
  )
  local pid
  pid="$(cat "$STATE_DIR/.${name}.pid")"
  rm -f "$STATE_DIR/.${name}.pid"
  echo "$name|$pid|$port|$workdir|$cmd" >> "$STATE_DIR/.processes.tmp"
}

if [[ -f "$PID_FILE" && "$FORCE" -ne 1 ]]; then
  echo "Detected existing state file: $PID_FILE"
  echo "Run ./scripts/dev-down.sh first, or use ./scripts/dev-up.sh --force."
  exit 1
fi

rm -f "$STATE_DIR/.processes.tmp"

start_service "autorealize-api" "$AUTOREALIZE_DIR" 18101 "uvicorn autorealize.service_api:app --host 127.0.0.1 --port 18101"
start_service "mlevolve-api" "$MLEVOLVE_DIR" 18103 "uvicorn service_api:app --host 127.0.0.1 --port 18103"
start_service "autoreport-api" "$AUTOREPORT_DIR" 18104 "uvicorn service_api:app --host 127.0.0.1 --port 18104"
start_service "gateway-api" "$GATEWAY_DIR" 18080 "uvicorn app:app --host 127.0.0.1 --port 18080"
start_service "frontend-ui" "$UI_DIR" 5173 "npm run dev -- --host 127.0.0.1 --port 5173"

{
  echo "#!/usr/bin/env bash"
  echo "ROOT_DIR=\"$ROOT_DIR\""
  echo "PROCESSES=("
  while IFS= read -r line; do
    echo "  \"$line\""
  done < "$STATE_DIR/.processes.tmp"
  echo ")"
} > "$PID_FILE"
chmod +x "$PID_FILE"
rm -f "$STATE_DIR/.processes.tmp"

echo
echo "All services started in background:"
echo "1) AutoRealize API: http://127.0.0.1:18101/health"
echo "2) MLEvolve API:    http://127.0.0.1:18103/health"
echo "3) AutoReport API:  http://127.0.0.1:18104/health"
echo "4) Gateway API:     http://127.0.0.1:18080/api/health"
echo "5) Frontend UI:     http://127.0.0.1:5173"
echo
echo "Stop all: ./scripts/dev-down.sh"

