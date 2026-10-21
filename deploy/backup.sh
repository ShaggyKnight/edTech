#!/usr/bin/env bash
# Backup de la base (cron mensual hoy; diario cuando haya Backblaze):
#   1. pg_dump de la DB
#   2. Gzip
#   3. Encriptar con gpg --symmetric (passphrase del .env)
#   4. Subir a Backblaze B2 (si B2_* esta configurado)
#   5. Limpiar locales viejos (ver BACKUP_LOCAL_DIAS) y B2 > 30 días (lifecycle)
#
# Sin Backblaze configurado igual respalda, pero la copia queda SOLO en
# este servidor (protege de errores en los datos, no de perder el disco).
#
# Diseñado para correr de cron (crontab del user `ideas`) — lee
# /srv/ideas/app/.env para los secretos.

set -euo pipefail
# El .sql sin cifrar existe unos segundos en disco: solo para `ideas`.
umask 077

APP_DIR="/srv/ideas/app"
BACKUP_DIR="/srv/ideas/backups"
LOG_TS() { date '+%F %T'; }

cd "$APP_DIR"

# Cargar .env (las vars quedan exportadas).
if [[ -f .env ]]; then
  # Sin `source .env`: un valor con < o > rompia el script (ver lib-env.sh).
  source "$APP_DIR/deploy/lib-env.sh"
  cargar_env .env
else
  echo "[$(LOG_TS)] ERROR: $APP_DIR/.env no existe." >&2
  exit 1
fi

: "${BACKUP_GPG_PASSPHRASE:?BACKUP_GPG_PASSPHRASE vacio en .env}"

SUBIR_B2=1
if [[ -z "${B2_ACCOUNT_ID:-}" || -z "${B2_APPLICATION_KEY:-}" || -z "${B2_BUCKET:-}" ]]; then
  SUBIR_B2=0
  echo "[$(LOG_TS)] AVISO: Backblaze (B2_*) sin configurar — el backup queda solo en este servidor."
fi

# Dias que se guardan los backups locales. Con B2 la copia de afuera
# guarda 30 dias y aca basta una semana; sin B2 la local es la unica, asi
# que se guarda un año (con el cron mensual, unas 12 copias).
if [[ $SUBIR_B2 == 1 ]]; then
  DIAS_LOCAL="${BACKUP_LOCAL_DIAS:-7}"
else
  DIAS_LOCAL="${BACKUP_LOCAL_DIAS:-400}"
fi

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
if [[ $SUBIR_B2 == 1 ]]; then
  # Auth idempotente — el comando es no-op si ya estás autenticado.
  echo "[$(LOG_TS)] b2 authorize-account..."
  b2 account authorize "$B2_ACCOUNT_ID" "$B2_APPLICATION_KEY" >/dev/null

  echo "[$(LOG_TS)] b2 upload..."
  b2 file upload --quiet "$B2_BUCKET" "$GPG_FILE" "$(basename "$GPG_FILE")"
fi

# ── Limpiar locales (los de mas de DIAS_LOCAL dias) ────────────────
echo "[$(LOG_TS)] limpiando backups locales de mas de ${DIAS_LOCAL} dias..."
find "$BACKUP_DIR" -type f -name 'ideas-*.gpg' -mtime +"$DIAS_LOCAL" -delete

echo "[$(LOG_TS)] OK — backup completado: $(basename "$GPG_FILE") ($(du -h "$GPG_FILE" | cut -f1))"
