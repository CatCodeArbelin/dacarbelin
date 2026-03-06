#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_SQL="${TMPDIR:-/tmp}/dac_alembic_upgrade_head.sql"

cd "$ROOT_DIR"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@db:5432/dac}"
export ADMIN_KEY="${ADMIN_KEY:-check_admin_key}"
export SECRET_KEY="${SECRET_KEY:-check_secret_key}"

PYTHONPATH="$ROOT_DIR" alembic upgrade head --sql > "$TMP_SQL"

PYTHONPATH="$ROOT_DIR" python - <<'PY'
from app.main import app

print(f"FastAPI app loaded: {app.title}")
PY

echo "Migration SQL generated at: $TMP_SQL"
