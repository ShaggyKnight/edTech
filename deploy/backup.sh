#!/usr/bin/env bash
# Backup diario:
#   1. pg_dump de la DB
#   2. Gzip
#   3. Encriptar con gpg --symmetric (passphrase del .env)
#   4. Subir a Backblaze B2
#   5. Limpiar locales > 7 días (en disco) y B2 > 30 días (lifecycle)
#
# Diseñado para correr de /etc/cron — lee /srv/ideas/app/.env para los
# secretos.

set -euo pipefail

APP_DIR="/srv/ideas/app"
BACKUP_DIR="/srv/ideas/backups"
LOG_TS() { date '+%F %T'; }

cd "$APP_DIR"

# Cargar .env (las vars quedan exportadas).
if [[ -f .env ]]; then
  set -a; source .env; set +a
else
  echo "[$(LOG_TS)] ERROR: $APP_DIR/.env no existe." >&2
  exit 1
fi

: "${B2_ACCOUNT_ID:?B2_ACCOUNT_ID vacio en .env}"
: "${B2_APPLICATION_KEY:?B2_APPLICATION_KEY vacio en .env}"
: "${B2_BUCKET:?B2_BUCKET vacio en .env}"
: "${BACKUP_GPG_PASSPHRASE:?BACKUP_GPG_PASSPHRASE vacio en .env}"

# Extraer DB url del DATABASE_URL.
DB_URL="${DATABASE_URL:?DATABASE_URL vacio}"

STAMP="$(date '+%Y-%m-%d-%H%M')"
DUMP_FILE="${BACKUP_DIR}/ideas-${STAMP}.sql"
GZ_FILE="${DUMP_FILE}.gz"
GPG_FILE="${GZ_FILE}.gpg"

mkdir -p "$BACKUP_DIR"

echo "[$(LOG_TS)] pg_dump → ${DUMP_FILE}"
pg_dump --no-owner --no-privileges --clean --if-exists "$DB_URL" > "$DUMP_FILE"

echo "[$(LOG_TS)] gzip..."
gzip -f "$DUMP_FILE"   # → $GZ_FILE

echo "[$(LOG_TS)] gpg encrypt..."
gpg --batch --yes --passphrase "$BACKUP_GPG_PASSPHRASE" \
    --symmetric --cipher-algo AES256 \
    --output "$GPG_FILE" \
    "$GZ_FILE"
rm -f "$GZ_FILE"

# ── B2 upload ──────────────────────────────────────────────────────
# Auth idempotente — el comando es no-op si ya estás autenticado.
echo "[$(LOG_TS)] b2 authorize-account..."
b2 account authorize "$B2_ACCOUNT_ID" "$B2_APPLICATION_KEY" >/dev/null

echo "[$(LOG_TS)] b2 upload..."
b2 file upload --quiet "$B2_BUCKET" "$GPG_FILE" "$(basename "$GPG_FILE")"

# ── Limpiar locales (solo los > 7 días) ────────────────────────────
echo "[$(LOG_TS)] limpiando backups locales antiguos..."
find "$BACKUP_DIR" -type f -name 'ideas-*.gpg' -mtime +7 -delete

echo "[$(LOG_TS)] OK — backup completado: $(basename "$GPG_FILE") ($(du -h "$GPG_FILE" | cut -f1))"
