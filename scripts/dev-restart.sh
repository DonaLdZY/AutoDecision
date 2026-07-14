#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT_DIR/scripts/dev-down.sh"
exec "$ROOT_DIR/scripts/dev-up.sh" "$@"
