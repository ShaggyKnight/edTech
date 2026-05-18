#!/usr/bin/env bash
# Postgres: crea DB `ideas` y user `ideas` con permisos minimos.
#
# - Password se genera random + se imprime al final (copialo al .env)
# - User NO es superuser, NO puede createdb, NO replicacion
# - Solo CONNECT a la DB `ideas`
# - listen_addresses queda en 'localhost' (no expone Postgres a internet)

set -euo pipefail

log() { echo "[$(date +%T)] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: ejecutar como root (sudo)." >&2
  exit 1
fi

DB_NAME="ideas"
DB_USER="ideas"
DB_PASS="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"

log "Creando user $DB_USER (perms minimos)..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  ELSE
    ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASS}';
  END IF;
END\$\$;
SQL

log "Creando DB $DB_NAME..."
if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
  # Intentar con es_CL.UTF-8 primero; si no existe, usar C.UTF-8 (siempre disponible)
  LC_COLLATE="es_CL.UTF-8"
  if ! locale -a | grep -q "^es_CL\.utf8"; then
    log "Locale es_CL.UTF-8 no encontrado; usando C.UTF-8 como fallback"
    LC_COLLATE="C.UTF-8"
  fi
  sudo -u postgres createdb -O "${DB_USER}" -E UTF8 -l "${LC_COLLATE}" -T template0 "${DB_NAME}"
fi

# Permisos minimos: solo el user 'ideas' puede acceder a esa DB.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
REVOKE ALL ON DATABASE ${DB_NAME} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${DB_NAME} TO ${DB_USER};
GRANT USAGE, CREATE ON SCHEMA public TO ${DB_USER};
SQL

log "Confirmando que Postgres NO escucha en interfaces publicas..."
PG_HBA="$(find /etc/postgresql -name pg_hba.conf | head -1)"
PG_CONF="$(find /etc/postgresql -name postgresql.conf | head -1)"

# listen_addresses = 'localhost' (default OK en Ubuntu — confirmar)
if grep -qE "^\s*listen_addresses" "$PG_CONF"; then
  sed -i -E "s|^\s*listen_addresses\s*=.*|listen_addresses = 'localhost'|" "$PG_CONF"
else
  echo "listen_addresses = 'localhost'" >> "$PG_CONF"
fi

systemctl restart postgresql

log ""
log "════════════════════════════════════════════════════════════════"
log "  Postgres listo. Copia esta linea a /srv/ideas/app/.env"
log ""
log "  DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
log ""
log "  IMPORTANTE: este password se imprime UNA SOLA VEZ. Guardalo en"
log "  un gestor (1Password, Bitwarden) AHORA, no podes recuperarlo."
log "════════════════════════════════════════════════════════════════"
