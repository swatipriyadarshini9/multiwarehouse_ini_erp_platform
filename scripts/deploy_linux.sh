#!/bin/bash
# One-shot deploy on Linux (e.g. Oracle Cloud Always Free ARM VM).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
  echo "Log out and back in so docker group applies, then re-run this script."
  exit 0
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin required (docker compose)."
  exit 1
fi

[[ -f .env ]] || cp .env.example .env

echo "==> docker compose up -d --build"
docker compose up -d --build

wait_exit() {
  local svc="$1"
  local max="${2:-1800}"
  local t=0
  while [[ $t -lt $max ]]; do
    cid="$(docker compose ps -q "$svc" 2>/dev/null || true)"
    if [[ -z "$cid" ]]; then
      sleep 5
      t=$((t + 5))
      continue
    fi
    status="$(docker inspect -f '{{.State.Status}}' "$cid")"
    if [[ "$status" == "exited" ]]; then
      code="$(docker inspect -f '{{.State.ExitCode}}' "$cid")"
      if [[ "$code" != "0" ]]; then
        docker compose logs --tail 50 "$svc"
        echo "ERROR: $svc exited $code"
        exit 1
      fi
      echo "    $svc OK"
      return 0
    fi
    echo "    $svc still running (${t}s)..."
    sleep 15
    t=$((t + 15))
  done
  echo "TIMEOUT: $svc"
  exit 1
}

wait_exit odoo-init 2400
wait_exit seed 600

docker compose exec -T api python scripts/apply_odoo_branding.py || true
docker compose exec -T api python -m pytest -q || true

echo ""
echo "Deployed. Open ports 8000, 8501, 8069 in your cloud security list (or use Cloudflare Tunnel)."
echo "  API:       http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_VM_IP):8000/docs"
echo "  Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_VM_IP):8501"
echo "  Odoo:      http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_VM_IP):8069"