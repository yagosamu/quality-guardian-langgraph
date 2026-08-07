#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# bootstrap.sh — brings the DataOps Hub up (Postgres, Qdrant, Neo4j, Mongo,
# SeaweedFS, data-generator) so the Quality Guardian agent has data to validate.
#
# Usage:
#   bash scripts/bootstrap.sh          # start everything
#   bash scripts/bootstrap.sh --down   # stop containers (keep data volumes)
#   bash scripts/bootstrap.sh --nuke   # stop AND wipe volumes (reset)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---- arg parse ----
case "${1:-}" in
  --down)
    echo "▸ Stopping Hub (data preserved)..."
    ( cd "${ROOT_DIR}" && docker compose down )
    echo "  ✓ Stopped."
    exit 0 ;;
  --nuke)
    echo "▸ FULL RESET: stopping Hub and wiping volumes..."
    ( cd "${ROOT_DIR}" && docker compose down -v )
    echo "  ✓ Wiped. Next 'up' will recreate schema and repopulate."
    exit 0 ;;
  "" ) : ;;
  * ) echo "✗ Unknown argument: $1  (use: --down | --nuke)"; exit 1 ;;
esac

# ---- step 1: check Docker ----
echo ""
echo "▸ Checking Docker daemon..."
if ! command -v docker >/dev/null 2>&1; then
  echo "  ✗ 'docker' not found in PATH. Install Docker Desktop or OrbStack."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "  ✗ Docker daemon not responding. Start Docker Desktop and try again."
  exit 1
fi
echo "  ✓ Docker is running ($(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'))"

# ---- step 2: bring up containers ----
echo ""
echo "▸ Starting Hub containers..."
( cd "${ROOT_DIR}" && docker compose up -d )

# ---- step 3: wait for Postgres (the one the agent depends on) ----
echo ""
echo "▸ Waiting for Postgres to become healthy (up to 60s)..."
status="unknown"
for i in {1..30}; do
  status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' guardian-postgres 2>/dev/null || echo missing)
  if [[ "$status" == "healthy" ]]; then
    echo "  ✓ Postgres is healthy"
    break
  fi
  sleep 2
done

if [[ "$status" != "healthy" ]]; then
  echo "  ✗ Postgres did not become healthy in time."
  echo "    Debug with: docker compose logs postgres"
  exit 1
fi

# ---- step 4: verify data is flowing ----
echo ""
echo "▸ Checking data-generator produced records..."
sleep 5
count=$(docker exec guardian-postgres psql -U dataops -d dataops -tAc "SELECT count(*) FROM customers;" 2>/dev/null | tr -d '[:space:]' || echo 0)
if [[ "${count:-0}" -gt 0 ]]; then
  echo "  ✓ ${count} customers in Ledger (data is live)"
else
  echo "  ! No customers yet — the generator writes every 30s. It will populate shortly."
fi

# ---- banner ----
echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║   ✓ HUB READY — the Quality Guardian has data to validate       ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Ports (host):"
echo "    Postgres  → localhost:5442   (db=dataops user=dataops)"
echo "    Qdrant    → localhost:6333"
echo "    Neo4j     → localhost:7474   (browser) · 7687 (bolt)"
echo "    Mongo     → localhost:27017"
echo "    SeaweedFS → localhost:8333 (s3) · 9333 (master)"
echo ""
echo "  Inspect live data:"
echo "    docker exec guardian-postgres psql -U dataops -d dataops -c \"SELECT count(*) FROM customers;\""
echo "    docker compose ps"
echo ""
echo "  Next steps:"
echo "    python -m venv .venv"
echo "    source .venv/bin/activate           # or .venv\\Scripts\\Activate.ps1 on PowerShell"
echo "    pip install -r requirements.txt"
echo "    cp .env.example .env                # add ANTHROPIC_API_KEY"
echo "    claude                              # start building src/guardian/"
echo ""
echo "  Control:"
echo "    bash scripts/bootstrap.sh --down    # stop (keep data)"
echo "    bash scripts/bootstrap.sh --nuke    # reset everything"
echo ""
