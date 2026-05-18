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
  # Locale para collation: queremos es_CL si esta disponible — sort
  # con ñ correcto (entre n y o), util para ORDER BY nombre del catalogo.
  #
  # Sutileza importante: Linux reporta el locale en `locale -a` con la
  # forma CANONICA (lowercase, sin guion, ej: `es_CL.utf8`). PostgreSQL
  # valida estricto y no acepta variantes con mayusculas o guiones
  # (`es_CL.UTF8`, `es_CL.UTF-8`). Antes pasabamos `es_CL.UTF8` aunque
  # el OS lo tenia como `es_CL.utf8` -> PG fallaba con
  # `invalid LC_COLLATE locale name`.
  #
  # Solucion: si el locale no esta presente, lo generamos. Despues
  # extraemos la forma EXACTA como aparece en `locale -a` y la pasamos
  # a createdb.

  if ! locale -a 2>/dev/null | grep -qi "^es_cl"; then
    log "Locale es_CL no esta generado, intentando generarlo..."
    if command -v locale-gen >/dev/null 2>&1; then
      locale-gen es_CL.UTF-8 || true
      command -v update-locale >/dev/null && update-locale || true
    fi
  fi

  LC_COLLATE="$(locale -a 2>/dev/null | grep -i '^es_cl' | head -1 || true)"
  if [[ -z "$LC_COLLATE" ]]; then
    log "Locale es_CL no disponible — usando C.UTF-8 como fallback."
    log "(Sort case-insensitive de ñ no funcionara optimo, pero el catalogo"
    log " va a operar normal.)"
    LC_COLLATE="C.UTF-8"
  else
    log "Usando locale: $LC_COLLATE"
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
