#!/usr/bin/env bash
# Activa gzip para CSS/JS/SVG en /static/ de ideasboutique.cl.
#
# Correr UNA vez como root (por ejemplo desde la consola de Hetzner):
#   bash /srv/ideas/app/deploy/nginx-gzip.sh
#
# Respalda la config en /root, agrega gzip_static/gzip_vary/gzip_types en
# cada bloque `location /static/` de /etc/nginx/sites-available/ideas,
# valida con `nginx -t` y recarga. Si nginx rechaza el cambio, restaura el
# respaldo. Si ya estaba aplicado, no hace nada.
#
# No se copia deploy/nginx-ideas.conf encima porque certbot le agrego al
# archivo del servidor la configuracion SSL, que se perderia.

set -euo pipefail

CONF="${CONF:-/etc/nginx/sites-available/ideas}"
BAK="/root/nginx-ideas.bak-$(date +%Y%m%d-%H%M%S)"

if [[ $EUID -ne 0 ]]; then
  echo "Hay que correrlo como root: bash $0" >&2
  exit 1
fi

if grep -q 'gzip_static on;' "$CONF"; then
  echo "Ya estaba aplicado, no hay nada que hacer."
  exit 0
fi

cp -p "$CONF" "$BAK"
sed -i '/location \/static\/ {/,/}/ s|^\([[:space:]]*\)access_log off;$|\1access_log off;\n\1gzip_static on;\n\1gzip_vary on;\n\1gzip_types text/css application/javascript image/svg+xml application/json;|' "$CONF"

if nginx -t; then
  systemctl reload nginx
  echo "LISTO: gzip activo en $(grep -c 'gzip_static on;' "$CONF") bloques /static/. Respaldo: $BAK"
else
  cp -p "$BAK" "$CONF"
  echo "RESTAURADO: nginx rechazo el cambio y quedo la config original." >&2
  exit 1
fi
