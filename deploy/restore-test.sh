#!/usr/bin/env bash
# Test mensual de backup: bajar el último .gpg de B2, desencriptar,
# restaurar en una DB temporal, contar registros y dropear.
#
# Si esto falla, abrir incidente AHORA — significa que los backups no
# sirven y un evento de pérdida deja la tienda sin recuperación.

set -euo pipefail

APP_DIR="/srv/ideas/app"
TMP_DIR="$(mktemp -d -t ideas-restore-XXXXXX)"
TMP_DB="ideas_restore_test"
LOG_TS() { date '+%F %T'; }
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$APP_DIR"

# Cargar .env.
if [[ -f .env ]]; then
  set -a; source .env; set +a
else
  echo "[$(LOG_TS)] ERROR: $APP_DIR/.env no existe." >&2
  exit 1
fi

: "${B2_ACCOUNT_ID:?B2_ACCOUNT_ID vacio}"
: "${B2_APPLICATION_KEY:?B2_APPLICATION_KEY vacio}"
: "${B2_BUCKET:?B2_BUCKET vacio}"
: "${BACKUP_GPG_PASSPHRASE:?BACKUP_GPG_PASSPHRASE vacio}"

# Listar el archivo más reciente en B2.
echo "[$(LOG_TS)] b2 authorize-account..."
b2 account authorize "$B2_ACCOUNT_ID" "$B2_APPLICATION_KEY" >/dev/null

echo "[$(LOG_TS)] obteniendo archivo más reciente..."
LATEST="$(b2 ls "b2://$B2_BUCKET" | grep '\.sql\.gz\.gpg$' | sort | tail -1 | awk '{print $NF}')"
[[ -n "$LATEST" ]] || { echo "[$(LOG_TS)] ERROR: no hay backups en B2." >&2; exit 2; }

echo "[$(LOG_TS)] descargando ${LATEST}..."
b2 file download --quiet "b2://${B2_BUCKET}/${LATEST}" "${TMP_DIR}/${LATEST}"

echo "[$(LOG_TS)] desencriptando..."
gpg --batch --yes --passphrase "$BACKUP_GPG_PASSPHRASE" \
    --decrypt --output "${TMP_DIR}/dump.sql.gz" \
    "${TMP_DIR}/${LATEST}"

echo "[$(LOG_TS)] descomprimiendo..."
gunzip "${TMP_DIR}/dump.sql.gz"   # → ${TMP_DIR}/dump.sql

# Crear DB temporal (usuario postgres del sistema).
echo "[$(LOG_TS)] creando DB temporal ${TMP_DB}..."
sudo -u postgres dropdb --if-exists "$TMP_DB"
sudo -u postgres createdb -E UTF8 -l es_CL.UTF-8 -T template0 "$TMP_DB"

echo "[$(LOG_TS)] restaurando dump..."
sudo -u postgres psql -d "$TMP_DB" --quiet -f "${TMP_DIR}/dump.sql" >/dev/null

# ── Validacion: contar tablas clave ────────────────────────────────
COUNT_PROD="$(sudo -u postgres psql -t -A -c "SELECT COUNT(*) FROM catalogo_producto" "$TMP_DB")"
COUNT_VENTAS="$(sudo -u postgres psql -t -A -c "SELECT COUNT(*) FROM pos_reciboventa" "$TMP_DB" 2>/dev/null || echo 0)"

# Dropear inmediatamente — no queremos copias en disco.
sudo -u postgres dropdb "$TMP_DB"

# Verificacion: el backup tiene que tener AL MENOS productos (la tienda
# arranca con 4-10 productos en el seed). Si reporta 0, algo está mal.
if [[ "$COUNT_PROD" -eq 0 ]]; then
  echo "[$(LOG_TS)] RESTORE FAIL — 0 productos en el dump." >&2
  exit 3
fi

echo "[$(LOG_TS)] RESTORE OK — ${COUNT_PROD} productos, ${COUNT_VENTAS} ventas (archivo ${LATEST})"
