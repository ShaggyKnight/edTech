#!/usr/bin/env bash
# Instala la app en /srv/ideas/.
#
# Layout:
#   /srv/ideas/app/        (clone del repo)
#   /srv/ideas/venv/       (virtualenv)
#   /srv/ideas/media/      (uploads — fotos de producto)
#   /srv/ideas/staticfiles/ (collectstatic)
#   /srv/ideas/backups/    (pg_dumps temporales antes de subir a B2)
#   /srv/ideas/logs/       (backup.log, restore-test.log)
#
# NO arranca la app — falta llenar .env y migrar la DB. El README
# explica los siguientes pasos.

set -euo pipefail

log() { echo "[$(date +%T)] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: ejecutar como root (sudo)." >&2
  exit 1
fi

APP_USER="ideas"
APP_HOME="/srv/ideas"
APP_DIR="${APP_HOME}/app"
VENV="${APP_HOME}/venv"
REPO="https://github.com/ShaggyKnight/edTech.git"
BRANCH="${BRANCH:-master}"

log "Creando layout en ${APP_HOME}..."
mkdir -p "${APP_HOME}"/{media,staticfiles,backups,logs}
chown -R "${APP_USER}:${APP_USER}" "${APP_HOME}"

# ── Clone / pull ────────────────────────────────────────────────────
if [[ -d "${APP_DIR}/.git" ]]; then
  log "Repo ya clonado — pulling ${BRANCH}..."
  sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch origin "${BRANCH}"
  sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
else
  log "Clonando ${REPO} → ${APP_DIR} (rama ${BRANCH})..."
  sudo -u "${APP_USER}" git clone --branch "${BRANCH}" --depth 1 "${REPO}" "${APP_DIR}"
fi

# ── venv ────────────────────────────────────────────────────────────
log "Creando venv en ${VENV}..."
sudo -u "${APP_USER}" python3 -m venv "${VENV}"
sudo -u "${APP_USER}" "${VENV}/bin/pip" install --quiet --upgrade pip setuptools wheel
sudo -u "${APP_USER}" "${VENV}/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

# ── .env desde template (si no existe) ──────────────────────────────
ENV_FILE="${APP_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  log "Copiando template a ${ENV_FILE} (sin secretos — completar manualmente)..."
  cp "${APP_DIR}/deploy/ideas.env.production.template" "${ENV_FILE}"
  chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
else
  log "${ENV_FILE} ya existe — NO se sobreescribe."
fi

# ── systemd: socket + service ───────────────────────────────────────
log "Instalando units de systemd para gunicorn..."
install -m 0644 "${APP_DIR}/deploy/gunicorn-ideas.socket"  /etc/systemd/system/
install -m 0644 "${APP_DIR}/deploy/gunicorn-ideas.service" /etc/systemd/system/
systemctl daemon-reload

# ── crontabs ────────────────────────────────────────────────────────
log "Programando cron para backups + restore-test..."
CRON_LINES="0 3 * * * ${APP_DIR}/deploy/backup.sh >> ${APP_HOME}/logs/backup.log 2>&1
0 4 1 * * ${APP_DIR}/deploy/restore-test.sh >> ${APP_HOME}/logs/restore-test.log 2>&1"

# Set crontab idempotente (preserva otros entries si los hay).
(
  sudo -u "${APP_USER}" crontab -l 2>/dev/null | grep -vF "${APP_DIR}/deploy/backup.sh" | grep -vF "${APP_DIR}/deploy/restore-test.sh"
  echo "${CRON_LINES}"
) | sudo -u "${APP_USER}" crontab -

# Logrotate para los logs de backup.
cat > /etc/logrotate.d/ideas <<EOF
${APP_HOME}/logs/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    create 0640 ${APP_USER} ${APP_USER}
}
EOF

log ""
log "════════════════════════════════════════════════════════════════"
log "  App instalada. PRÓXIMOS PASOS MANUALES:"
log ""
log "  1) Editar ${ENV_FILE} con los secretos reales:"
log "       sudo -u ${APP_USER} nano ${ENV_FILE}"
log ""
log "  2) Generar SECRET_KEY:"
log "       sudo -u ${APP_USER} ${VENV}/bin/python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'"
log ""
log "  3) Migrar y crear superuser:"
log "       cd ${APP_DIR}"
log "       sudo -u ${APP_USER} ${VENV}/bin/python manage.py migrate"
log "       sudo -u ${APP_USER} ${VENV}/bin/python manage.py collectstatic --noinput"
log "       sudo -u ${APP_USER} ${VENV}/bin/python manage.py createsuperuser"
log ""
log "  4) Levantar la app:"
log "       systemctl enable --now gunicorn-ideas.socket"
log "       systemctl status gunicorn-ideas.service"
log ""
log "  5) Configurar nginx y TLS — ver paso 6 del README."
log "════════════════════════════════════════════════════════════════"
