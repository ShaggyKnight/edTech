#!/usr/bin/env bash
# Solicita certificados Let's Encrypt para ideasboutique.cl y www.
# Requiere:
#   - DNS ya apuntando al VPS (verificá con `dig ideasboutique.cl`)
#   - nginx corriendo con la config de /etc/nginx/sites-enabled/ideas
#   - Puerto 80 abierto (lo hace 01-firewall.sh)

set -euo pipefail

log() { echo "[$(date +%T)] $*"; }

DOMAIN="ideasboutique.cl"
WWW="www.ideasboutique.cl"
ADMIN_EMAIL="shaggyxreload@gmail.com"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: ejecutar como root." >&2
  exit 1
fi

# Sanity: el DNS resuelve al servidor actual?
SERVER_IP="$(curl -s ifconfig.me || curl -s api.ipify.org)"
DNS_IP="$(dig +short A "$DOMAIN" | head -1)"
log "IP del servidor: ${SERVER_IP}"
log "DNS de ${DOMAIN}: ${DNS_IP}"

if [[ "$SERVER_IP" != "$DNS_IP" ]]; then
  echo "ADVERTENCIA: el A record de ${DOMAIN} apunta a ${DNS_IP}, no a ${SERVER_IP}."
  echo "Certbot va a fallar. Asegurate que el DNS esté propagado:"
  echo "    dig +short ${DOMAIN}"
  read -rp "¿Continuar igual? (y/N) " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
fi

log "Pidiendo certificado a Let's Encrypt para ${DOMAIN}, ${WWW}..."
certbot --nginx \
  --non-interactive --agree-tos \
  --email "${ADMIN_EMAIL}" \
  --redirect \
  --hsts \
  -d "${DOMAIN}" -d "${WWW}"

log "Test de renovacion (--dry-run, no contacta CA real)..."
certbot renew --dry-run

log ""
log "════════════════════════════════════════════════════════════════"
log "  TLS activo. Probar:"
log "    curl -I https://${DOMAIN}"
log ""
log "  Renovacion automatica via systemd timer:"
log "    systemctl status certbot.timer"
log "════════════════════════════════════════════════════════════════"
