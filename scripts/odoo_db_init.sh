#!/bin/bash
set -euo pipefail

DB_NAME="${ODOO_DB:-inventory}"
MARKER="/var/lib/odoo/.middleware_db_initialized"

if [[ -f "${MARKER}" ]]; then
  echo "Odoo database ${DB_NAME} already initialized (marker present)."
  exit 0
fi

echo "Initializing Odoo database ${DB_NAME} with stock and purchase modules..."
/entrypoint.sh odoo -d "${DB_NAME}" \
  -i base,stock,purchase,purchase_stock,website \
  --without-demo=all \
  --stop-after-init

touch "${MARKER}"
echo "Odoo init complete."