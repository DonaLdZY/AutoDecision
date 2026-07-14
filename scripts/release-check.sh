#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

git submodule status --recursive
if git submodule status --recursive | grep -q '^-'; then
  echo "Initialize all submodules before running release checks." >&2
  exit 1
fi

python scripts/repository-audit.py

repositories=(. core/AutoRealize core/MLEvolve-Alter core/AutoReport)
for repository in "${repositories[@]}"; do
  git -C "$repository" diff --check
  git -C "$repository" diff --cached --check
done

required=(
  README.md docs/THIRD_PARTY_NOTICES.md docs/release-checklist.md
  core/AutoRealize/config/config.yaml
  core/MLEvolve-Alter/config/config.yaml
  core/AutoReport/config/config.yaml
)
for file in "${required[@]}"; do
  test -f "$file" || { echo "Missing required file: $file" >&2; exit 1; }
done

if [[ "${1:-}" != "--skip-tests" ]]; then
  python -m pytest frontend/backend/tests -q
  python -m ruff check frontend/backend --select E9,F63,F7,F82
  (cd core/AutoRealize && python -m pytest -q && python -m ruff check autorealize tests --select E9,F63,F7,F82)
  (cd core/MLEvolve-Alter && python -m pytest -q && python -m ruff check agents config engine llm utils run.py service_api.py tests --select E9,F63,F7,F82)
  (cd core/AutoReport && python -m pytest -q && python -m ruff check autoreport service_api.py tests --select E9,F63,F7,F82)
  (cd frontend/ui && npm run test && npm run build)
fi

if [[ ! -f LICENSE ]]; then
  echo "WARNING: BLOCKER: LICENSE is missing. Resolve upstream MLEvolve permission before release." >&2
fi
echo "Local checks completed. Full-history secret cleanup remains a manual release blocker."
