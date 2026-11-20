#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -gt 0 && "$1" != -* ]]; then
  SERVICE_NAME="$1"
  shift
  exec bash "$SCRIPT_DIR/studio.sh" logs --name "$SERVICE_NAME" "$@"
fi
exec bash "$SCRIPT_DIR/studio.sh" logs "$@"
