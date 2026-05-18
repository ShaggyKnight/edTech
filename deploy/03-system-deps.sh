#!/usr/bin/env bash
# Dependencias del sistema:
#   - Python 3.12 (default en Ubuntu 24.04)
#   - PostgreSQL 16
#   - nginx
#   - certbot (snap)
#   - git, build tools, libpq-dev
#   - b2-cli (Backblaze) para backups
#   - gpg (encrypt backups)
#   - tzdata (timezone Santiago)

set -euo pipefail

log() { echo "[$(date +%T)] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: ejecutar como root (sudo)." >&2
  exit 1
fi

log "Actualizando indices apt..."
apt-get update -y -qq
apt-get upgrade -y -qq

log "Configurando timezone America/Santiago..."
timedatectl set-timezone America/Santiago

log "Generando locales necesarios (es_CL.UTF-8, es_GL.UTF-8)..."
apt-get install -y -qq locales
sed -i 's/^# \(es_CL.UTF-8\)/\1/' /etc/locale.gen
sed -i 's/^# \(es_GL.UTF-8\)/\1/' /etc/locale.gen
locale-gen

log "Instalando paquetes core..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3 python3-venv python3-dev python3-pip \
  build-essential pkg-config \
  postgresql postgresql-contrib libpq-dev \
  nginx \
  git curl ca-certificates \
  gnupg gpg \
  unattended-upgrades \
  htop logrotate cron

# Backblaze B2 CLI (oficial) via pip system-wide.
log "Instalando b2 cli (Backblaze) en /usr/local/bin..."
python3 -m pip install --quiet --break-system-packages 'b2>=4.0' || \
  python3 -m pip install --quiet 'b2>=4.0'

# Certbot via snap (recomendacion oficial — snap mantiene certbot actualizado).
log "Instalando certbot via snap..."
if ! command -v snap &>/dev/null; then
  apt-get install -y -qq snapd
fi
snap install --classic certbot || snap refresh certbot
ln -sf /snap/bin/certbot /usr/bin/certbot

# Auto-updates de seguridad solo (no breaking changes).
log "Activando unattended-upgrades para parches de seguridad..."
dpkg-reconfigure -f noninteractive unattended-upgrades

# Habilitar nginx y postgres (start at boot).
systemctl enable --now nginx
systemctl enable --now postgresql

log "OK — paquetes instalados."
log "Versiones:"
python3 --version
psql --version | head -1
nginx -v 2>&1 | head -1
certbot --version
b2 version || true
