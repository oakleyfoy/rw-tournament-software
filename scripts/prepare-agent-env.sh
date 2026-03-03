#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_BACKEND=1
INSTALL_FRONTEND=1

usage() {
  cat <<'EOF'
Usage: scripts/prepare-agent-env.sh [options]

Bootstraps this repository for local/cloud agent work.

Options:
  --backend-only     Install backend dependencies only
  --frontend-only    Install frontend dependencies only
  -h, --help         Show this help text

Examples:
  scripts/prepare-agent-env.sh
  scripts/prepare-agent-env.sh --backend-only
EOF
}

for arg in "$@"; do
  case "$arg" in
    --backend-only)
      INSTALL_FRONTEND=0
      ;;
    --frontend-only)
      INSTALL_BACKEND=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$INSTALL_BACKEND" -eq 1 ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required but not found." >&2
    exit 1
  fi

  echo "==> Installing backend dependencies"
  python3 -m pip install -r "${ROOT_DIR}/backend/requirements.txt"
fi

if [[ "$INSTALL_FRONTEND" -eq 1 ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required for frontend dependencies but not found." >&2
    exit 1
  fi

  echo "==> Installing frontend dependencies"
  npm ci --prefix "${ROOT_DIR}/frontend"
fi

echo "Environment bootstrap complete."
echo "Next steps:"
echo "  Backend tests:  cd ${ROOT_DIR}/backend && python3 -m pytest"
echo "  Frontend build: cd ${ROOT_DIR}/frontend && npm run build"
