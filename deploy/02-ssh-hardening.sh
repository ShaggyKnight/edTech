#!/usr/bin/env bash
# SSH hardening + fail2ban.
#
# Hace:
#   - Crear user `ideas` (no-root, sudo NOPASSWD para tareas de app)
#   - Copiar las authorized_keys de root al user `ideas`
#   - Deshabilitar login de root via SSH
#   - Deshabilitar password auth (solo key auth)
#   - Instalar y configurar fail2ban (anti-brute-force a nivel SSH)
#
# ¡CUIDADO! Después de este script NO te podrás conectar como root.
# Asegurate de que tu pubkey está en /root/.ssh/authorized_keys ANTES
# de correrlo, porque el script la copia al user `ideas`.

set -euo pipefail

log() { echo "[$(date +%T)] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: ejecutar como root." >&2
  exit 1
fi

APP_USER="ideas"

# ── 1. Crear user app ───────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
  log "Creando user $APP_USER..."
  useradd -m -s /bin/bash "$APP_USER"
fi

# Sudo NOPASSWD acotado a tareas operativas (systemctl restart, nginx -t).
log "Configurando sudo para $APP_USER..."
cat > "/etc/sudoers.d/${APP_USER}" <<EOF
# Permisos minimos para que el user de app pueda:
#   - Reiniciar gunicorn / nginx (necesario para deploy.sh)
#   - Correr psql/createdb/dropdb como postgres (necesario para restore-test.sh)
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl restart gunicorn-ideas.service
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl reload gunicorn-ideas.service
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl status gunicorn-ideas.service
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl reload nginx
${APP_USER} ALL=(root) NOPASSWD: /usr/sbin/nginx -t
${APP_USER} ALL=(postgres) NOPASSWD: /usr/bin/psql, /usr/bin/createdb, /usr/bin/dropdb
EOF
chmod 0440 "/etc/sudoers.d/${APP_USER}"
visudo -c -f "/etc/sudoers.d/${APP_USER}" >/dev/null

# ── 2. Copiar authorized_keys ───────────────────────────────────────
log "Copiando authorized_keys de root → $APP_USER..."
mkdir -p "/home/${APP_USER}/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  cp /root/.ssh/authorized_keys "/home/${APP_USER}/.ssh/authorized_keys"
else
  echo "ADVERTENCIA: /root/.ssh/authorized_keys no existe. El user $APP_USER no podrá entrar sin tu pubkey."
fi
chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.ssh"
chmod 700 "/home/${APP_USER}/.ssh"
chmod 600 "/home/${APP_USER}/.ssh/authorized_keys" 2>/dev/null || true

# ── 3. Endurecer sshd_config ────────────────────────────────────────
log "Endureciendo /etc/ssh/sshd_config..."
SSHD=/etc/ssh/sshd_config
cp -n "$SSHD" "${SSHD}.bak.$(date +%F)"   # backup la primera vez

# Funcion helper para set de valor en sshd_config (idempotente).
set_sshd() {
  local key="$1" val="$2"
  if grep -qE "^\s*${key}\s+" "$SSHD"; then
    sed -i -E "s|^\s*${key}\s+.*|${key} ${val}|" "$SSHD"
  else
    echo "${key} ${val}" >> "$SSHD"
  fi
}

set_sshd PermitRootLogin no
set_sshd PasswordAuthentication no
set_sshd KbdInteractiveAuthentication no
set_sshd ChallengeResponseAuthentication no
set_sshd UsePAM yes
set_sshd MaxAuthTries 3
set_sshd LoginGraceTime 30
set_sshd X11Forwarding no
set_sshd AllowTcpForwarding no
set_sshd ClientAliveInterval 300
set_sshd ClientAliveCountMax 2

sshd -t   # test config; falla si hay sintaxis mala
log "Recargando sshd..."
systemctl reload ssh || systemctl reload sshd

# ── 4. fail2ban ─────────────────────────────────────────────────────
log "Instalando fail2ban..."
apt-get install -y -qq fail2ban

cat > /etc/fail2ban/jail.local <<'EOF'
# Jail local: SSH + nginx login endpoints.
# Sobreescribe los defaults de /etc/fail2ban/jail.conf.
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

# Notificar via journald (más simple que email).
banaction = ufw
backend = systemd

[sshd]
enabled = true
port = ssh

# Auxiliar: ban a IPs que escanean /admin/ y nuestro ADMIN_URL.
# El log de nginx debe estar en /var/log/nginx/access.log (default).
[nginx-noscript]
enabled = false   # activar despues si vemos abuso
# Si lo activamos:
# port    = http,https
# filter  = nginx-noscript
# logpath = /var/log/nginx/access.log
EOF

systemctl enable --now fail2ban
systemctl restart fail2ban

log "fail2ban status:"
fail2ban-client status sshd || true

log "OK — SSH endurecido. Conectate ahora como: ssh ${APP_USER}@<IP-del-vps>"
log "Hint: ssh-copy-id ${APP_USER}@<IP> desde tu maquina si no copiaste la key todavia."
