#!/usr/bin/env bash
# Firewall UFW: solo SSH/HTTP/HTTPS desde afuera.
# Idempotente — re-ejecutar no rompe nada.

set -euo pipefail

log() { echo "[$(date +%T)] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: ejecutar como root (sudo)." >&2
  exit 1
fi

log "Instalando ufw..."
apt-get update -y -qq
apt-get install -y -qq ufw

log "Reglas por default: deny inbound, allow outbound."
ufw default deny incoming
ufw default allow outgoing

# Puertos.
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

# Hetzner usa IPv6 — UFW las cubre con la misma regla por default.
# Si en el futuro hay alguna app en localhost, NO la expongas — usa
# socket Unix o bind a 127.0.0.1.

log "Habilitando UFW (no-prompt)..."
echo "y" | ufw enable >/dev/null
ufw status verbose

log "OK — firewall activo. SSH/HTTP/HTTPS permitidos, todo lo demás bloqueado."
