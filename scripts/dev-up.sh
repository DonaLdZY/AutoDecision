#!/usr/bin/env bash
set -euo pipefail

FORCE=0
OPEN_BROWSER=0
PYTHON_OVERRIDE="${AUTODECISION_PYTHON:-}"

usage() {
  cat <<'EOF'
Usage: ./scripts/dev-up.sh [--force] [--open] [--python /path/to/python]

Options:
  --force, -f       Stop existing listeners on AutoDecision development ports.
  --open, -o        Open the frontend in the default browser after startup.
  --python PATH     Use a specific Python 3.11+ interpreter.

The AUTODECISION_PYTHON environment variable is also supported.
Without an override, the script first reads python.executable from
frontend/config/global_settings.yaml, then checks the active Conda environment.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f)
      FORCE=1
      shift
      ;;
    --open|-o)
      OPEN_BROWSER=1
      shift
      ;;
    --python)
      if [[ $# -lt 2 ]]; then
        echo "--python requires an interpreter path." >&2
        exit 2
      fi
      PYTHON_OVERRIDE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.dev-state"
LOG_DIR="$STATE_DIR/logs"
PID_FILE="$STATE_DIR/pids.sh"
TEMP_PROCESS_FILE="$STATE_DIR/.processes.tmp"

AUTOREALIZE_DIR="$ROOT_DIR/core/AutoRealize"
MLEVOLVE_DIR="$ROOT_DIR/core/MLEvolve-Alter"
AUTOREPORT_DIR="$ROOT_DIR/core/AutoReport"
GATEWAY_DIR="$ROOT_DIR/frontend/backend"
UI_DIR="$ROOT_DIR/frontend/ui"
GLOBAL_SETTINGS_FILE="${AUTODECISION_GLOBAL_SETTINGS_PATH:-$ROOT_DIR/frontend/config/global_settings.yaml}"
if [[ "$GLOBAL_SETTINGS_FILE" != /* ]]; then
  GLOBAL_SETTINGS_FILE="$ROOT_DIR/$GLOBAL_SETTINGS_FILE"
fi

KNOWN_PORTS=(18101 18103 18104 18080 5173)
STARTUP_COMPLETE=0
STARTED_ANY=0

mkdir -p "$STATE_DIR" "$LOG_DIR"
rm -f "$TEMP_PROCESS_FILE"

listening_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
  fi
}

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    return $?
  fi
  return 1
}

stop_port_listeners() {
  local port="$1"
  local pids
  pids="$(listening_pids "$port" || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Stopping existing listener(s) on port $port: $(echo "$pids" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $pids >/dev/null 2>&1 || true
  sleep 0.5
  pids="$(listening_pids "$port" || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids >/dev/null 2>&1 || true
  fi
}

state_has_live_processes() (
  set +u
  # shellcheck source=/dev/null
  source "$PID_FILE" >/dev/null 2>&1 || exit 1
  local row name pid port workdir cmd
  for row in "${PROCESSES[@]}"; do
    IFS='|' read -r name pid port workdir cmd <<< "$row"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1 && port_in_use "$port"; then
      exit 0
    fi
  done
  exit 1
)

cleanup_started() {
  if [[ ! -f "$TEMP_PROCESS_FILE" ]]; then
    return 0
  fi
  local row name pid port workdir cmd
  while IFS= read -r row; do
    IFS='|' read -r name pid port workdir cmd <<< "$row"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done < "$TEMP_PROCESS_FILE"
  sleep 0.3
  while IFS= read -r row; do
    IFS='|' read -r name pid port workdir cmd <<< "$row"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    stop_port_listeners "$port"
  done < "$TEMP_PROCESS_FILE"
}

on_exit() {
  local status=$?
  if [[ "$STARTUP_COMPLETE" -ne 1 ]]; then
    cleanup_started
    # The state file is only written after every health check passes. Do not
    # remove a pre-existing state file when a second start attempt is refused.
    rm -f "$TEMP_PROCESS_FILE"
    if [[ "$status" -ne 0 && "$STARTED_ANY" -eq 1 ]]; then
      echo "Startup failed. See logs in $LOG_DIR" >&2
    fi
  fi
}
trap on_exit EXIT

if [[ -f "$PID_FILE" ]]; then
  if state_has_live_processes; then
    if [[ "$FORCE" -ne 1 ]]; then
      echo "Detected running AutoDecision services from $PID_FILE" >&2
      echo "Run ./scripts/dev-down.sh first, or use ./scripts/dev-up.sh --force." >&2
      exit 1
    fi
    "$ROOT_DIR/scripts/dev-down.sh"
  else
    echo "Removing stale state file: $PID_FILE"
    rm -f "$PID_FILE"
  fi
fi

for port in "${KNOWN_PORTS[@]}"; do
  if port_in_use "$port"; then
    if [[ "$FORCE" -eq 1 ]]; then
      stop_port_listeners "$port"
    else
      echo "Port $port is already in use. Run ./scripts/dev-down.sh or retry with --force." >&2
      exit 1
    fi
  fi
done

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

configured_python_from_settings() {
  if [[ ! -f "$GLOBAL_SETTINGS_FILE" ]]; then
    return 0
  fi
  awk '
    /^[[:space:]]*python:[[:space:]]*$/ { in_python = 1; next }
    in_python && /^[^[:space:]]/ { exit }
    in_python && /^[[:space:]]+executable:[[:space:]]*/ {
      value = $0
      sub(/^[[:space:]]+executable:[[:space:]]*/, "", value)
      sub(/[[:space:]]+#.*$/, "", value)
      gsub(/^"|"$/, "", value)
      print value
      exit
    }
  ' "$GLOBAL_SETTINGS_FILE"
}

resolve_python() {
  local candidates=()
  local candidate resolved
  if [[ -n "$PYTHON_OVERRIDE" ]]; then
    candidates+=("$PYTHON_OVERRIDE")
  fi
  if [[ -n "$CONFIGURED_PYTHON" ]]; then
    candidates+=("$CONFIGURED_PYTHON")
  fi
  if [[ -n "${CONDA_PREFIX:-}" ]]; then
    candidates+=("$CONDA_PREFIX/bin/python3.12" "$CONDA_PREFIX/bin/python")
  fi
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    candidates+=("$VIRTUAL_ENV/bin/python")
  fi
  candidates+=(
    "$ROOT_DIR/.venv/bin/python"
    "python3.12"
    "python3.11"
    "python3"
    "python"
  )

  for candidate in "${candidates[@]}"; do
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
    if [[ -z "$resolved" || ! -x "$resolved" ]]; then
      continue
    fi
    if python_supported "$resolved"; then
      echo "$resolved"
      return 0
    fi
  done
  return 1
}

CONFIGURED_PYTHON="$(configured_python_from_settings || true)"
PYTHON_BIN="$(resolve_python || true)"
if [[ -z "$CONFIGURED_PYTHON" && -x "$ROOT_DIR/.venv/bin/python" ]] && ! python_supported "$ROOT_DIR/.venv/bin/python"; then
  OLD_VENV_VERSION="$($ROOT_DIR/.venv/bin/python -c 'import platform; print(platform.python_version())' 2>/dev/null || echo unknown)"
  echo "Warning: ignoring project .venv because it uses Python $OLD_VENV_VERSION; Python 3.11+ is required." >&2
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "AutoDecision requires Python 3.11 or newer (3.11/3.12 recommended)." >&2
  echo "The current .venv may have been created with the macOS system Python 3.9." >&2
  echo "Recreate it with Python 3.11/3.12, or pass --python /path/to/python." >&2
  exit 1
fi

PYTHON_VERSION="$($PYTHON_BIN -c 'import platform; print(platform.python_version())')"
PYTHON_PREFIX="$($PYTHON_BIN -c 'import sys; print(sys.prefix)')"
if ! "$PYTHON_BIN" -c 'import fastapi, pydantic, uvicorn, yaml' >/dev/null 2>&1; then
  echo "Python $PYTHON_VERSION at $PYTHON_BIN is missing AutoDecision runtime dependencies." >&2
  echo "Install them with:" >&2
  echo "  $PYTHON_BIN -m pip install -r $ROOT_DIR/requirements.txt" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required to start the frontend." >&2
  exit 1
fi
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 20 || (major === 20 && minor >= 19) ? 0 : 1)' >/dev/null 2>&1; then
  echo "AutoDecision frontend requires Node.js 20.19 or newer." >&2
  exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "$NODE_MAJOR" -ge 23 ]]; then
  echo "Warning: Node.js $(node --version) is newer than the tested range (20/22 LTS)."
fi
if [[ ! -x "$UI_DIR/node_modules/.bin/vite" ]]; then
  echo "Frontend dependencies are missing. Run: (cd $UI_DIR && npm install)" >&2
  exit 1
fi

start_service() {
  local name="$1"
  local workdir="$2"
  local port="$3"
  shift 3
  local logfile="$LOG_DIR/${name}.log"
  local service_pid_file="$STATE_DIR/.${name}.pid"
  local cmd_display=""
  local arg pid

  : > "$logfile"
  for arg in "$@"; do
    printf -v cmd_display '%s%q ' "$cmd_display" "$arg"
  done

  (
    cd "$workdir"
    nohup "$@" >"$logfile" 2>&1 &
    echo "$!" > "$service_pid_file"
  )
  pid="$(cat "$service_pid_file")"
  rm -f "$service_pid_file"
  printf '%s|%s|%s|%s|%s\n' "$name" "$pid" "$port" "$workdir" "$cmd_display" >> "$TEMP_PROCESS_FILE"
  STARTED_ANY=1
  echo "Started $name (PID $pid, port $port)"
}

show_service_log() {
  local name="$1"
  local logfile="$LOG_DIR/${name}.log"
  if [[ -f "$logfile" ]]; then
    echo "----- $name log -----" >&2
    tail -n 60 "$logfile" >&2 || true
  fi
}

wait_http_ready() {
  local log_name="$1"
  local display_name="$2"
  local url="$3"
  local pid="$4"
  local timeout_secs="${5:-45}"
  local deadline=$(( $(date +%s) + timeout_secs ))

  while [[ "$(date +%s)" -lt "$deadline" ]]; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "Ready: $display_name ($url)"
      return 0
    fi
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "$display_name exited before becoming ready." >&2
      # Give stdio buffers a moment to flush so the actionable traceback is
      # visible immediately instead of only appearing in the log afterwards.
      sleep 0.2
      show_service_log "$log_name"
      return 1
    fi
    sleep 0.5
  done

  echo "$display_name health check timed out after ${timeout_secs}s: $url" >&2
  show_service_log "$log_name"
  return 1
}

last_started_pid() {
  tail -n 1 "$TEMP_PROCESS_FILE" | awk -F'|' '{print $2}'
}

echo "Using Python: $PYTHON_BIN ($PYTHON_VERSION)"
if [[ -d "$PYTHON_PREFIX/conda-meta" ]]; then
  echo "Using Conda:  $(basename "$PYTHON_PREFIX") ($PYTHON_PREFIX)"
fi
echo "Using Node:   $(command -v node) ($(node --version))"

start_service "autorealize-api" "$AUTOREALIZE_DIR" 18101 "$PYTHON_BIN" -m uvicorn autorealize.service_api:app --host 127.0.0.1 --port 18101
wait_http_ready "autorealize-api" "AutoRealize API" "http://127.0.0.1:18101/health" "$(last_started_pid)"

start_service "mlevolve-api" "$MLEVOLVE_DIR" 18103 "$PYTHON_BIN" -m uvicorn service_api:app --host 127.0.0.1 --port 18103
wait_http_ready "mlevolve-api" "MLEvolve API" "http://127.0.0.1:18103/health" "$(last_started_pid)"

start_service "autoreport-api" "$AUTOREPORT_DIR" 18104 "$PYTHON_BIN" -m uvicorn service_api:app --host 127.0.0.1 --port 18104
wait_http_ready "autoreport-api" "AutoReport API" "http://127.0.0.1:18104/health" "$(last_started_pid)"

start_service "gateway-api" "$GATEWAY_DIR" 18080 "$PYTHON_BIN" -m uvicorn app:app --host 127.0.0.1 --port 18080
wait_http_ready "gateway-api" "Gateway API" "http://127.0.0.1:18080/api/health" "$(last_started_pid)"

start_service "frontend-ui" "$UI_DIR" 5173 "$UI_DIR/node_modules/.bin/vite" --host 127.0.0.1 --port 5173
wait_http_ready "frontend-ui" "Frontend UI" "http://127.0.0.1:5173" "$(last_started_pid)"

{
  echo "#!/usr/bin/env bash"
  printf 'ROOT_DIR=%q\n' "$ROOT_DIR"
  echo "PROCESSES=("
  while IFS= read -r line; do
    printf '  %q\n' "$line"
  done < "$TEMP_PROCESS_FILE"
  echo ")"
} > "$PID_FILE"
chmod 600 "$PID_FILE"
rm -f "$TEMP_PROCESS_FILE"
STARTUP_COMPLETE=1

echo
echo "All services are healthy:"
echo "1) AutoRealize API: http://127.0.0.1:18101/health"
echo "2) MLEvolve API:    http://127.0.0.1:18103/health"
echo "3) AutoReport API:  http://127.0.0.1:18104/health"
echo "4) Gateway API:     http://127.0.0.1:18080/api/health"
echo "5) Frontend UI:     http://127.0.0.1:5173"
echo
echo "Status: ./scripts/dev-status.sh"
echo "Logs:   ./scripts/dev-logs.sh gateway-api --follow"
echo "Stop:   ./scripts/dev-down.sh"

if [[ "$OPEN_BROWSER" -eq 1 ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open "http://127.0.0.1:5173"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:5173" >/dev/null 2>&1 &
  fi
fi
