#!/usr/bin/env bash
# Deploy de cambios en producción.
#
# Uso (como user `ideas`):
#   /srv/ideas/app/deploy/deploy.sh
#   /srv/ideas/app/deploy/deploy.sh --branch=develop   (opcional)
#
# Hace:
#   1. git pull desde la rama indicada (default: master)
#   2. Si requirements.txt cambió → pip install
#   3. migrate (no-input, autoabort si conflicto)
#   4. collectstatic
#   5. systemctl reload gunicorn-ideas (zero-downtime)
#
# Si algo falla a la mitad — el último commit que andaba sigue vivo
# porque gunicorn no se recargó.

set -euo pipefail

APP_DIR="/srv/ideas/app"
VENV="/srv/ideas/venv"
BRANCH="${BRANCH:-master}"

# Args.
for arg in "$@"; do
  case "$arg" in
    --branch=*) BRANCH="${arg#*=}";;
    -h|--help)
      sed -n '/^# Uso/,/^$/p' "$0"; exit 0;;
  esac
done

log() { echo "[$(date +%T)] $*"; }

cd "$APP_DIR"

log "Deploy desde rama: ${BRANCH}"

# ── 1. git pull ────────────────────────────────────────────────────
log "git fetch..."
git fetch origin "$BRANCH"
CURRENT="$(git rev-parse HEAD)"
TARGET="$(git rev-parse "origin/${BRANCH}")"

if [[ "$CURRENT" == "$TARGET" ]]; then
  log "Ya en ${TARGET:0:7} — nada que deployar."
  exit 0
fi

log "${CURRENT:0:7} → ${TARGET:0:7}"
git reset --hard "origin/${BRANCH}"

# ── 2. requirements (solo si cambió) ───────────────────────────────
if git diff --name-only "$CURRENT" "$TARGET" | grep -qE '^requirements\.txt$'; then
  log "requirements.txt cambió — pip install..."
  "$VENV/bin/pip" install --quiet -r requirements.txt
else
  log "requirements.txt sin cambios — skip pip."
fi

# ── 3. migraciones ─────────────────────────────────────────────────
log "Migrate..."
"$VENV/bin/python" manage.py migrate --noinput

# ── 4. collectstatic ───────────────────────────────────────────────
log "collectstatic..."
"$VENV/bin/python" manage.py collectstatic --noinput --clear

# ── 5. reload gunicorn (zero-downtime) ─────────────────────────────
log "systemctl reload gunicorn-ideas..."
sudo /bin/systemctl reload gunicorn-ideas.service

# ── Sanity: ver que respondio ──────────────────────────────────────
sleep 2
if ! curl -s -o /dev/null -w '%{http_code}' http://localhost/healthz | grep -q 200; then
  log "ADVERTENCIA: /healthz no responde 200. Revisa logs:"
  log "    sudo journalctl -u gunicorn-ideas -n 50"
  exit 1
fi

log "OK — deploy completo en ${TARGET:0:7}."
