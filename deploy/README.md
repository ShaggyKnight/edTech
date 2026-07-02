# Deploy de Ideas Boutique 2.0 en Hetzner

Receta paso a paso para desplegar la app en un VPS Hetzner Cloud
(Ubuntu 24.04 LTS).

> **Tiempo total:** ~90 minutos para una persona técnica que sigue
> los pasos sin distraerse. La mayor parte del tiempo es esperar
> (DNS propagación, `apt`, certbot).

---

## 0 · Pre-requisitos

| Item | Cómo conseguirlo |
|---|---|
| Cuenta Hetzner Cloud | https://www.hetzner.com/cloud — agregar tarjeta + validar |
| Dominio `ideasboutique.cl` | Registrado en NIC.cl o cualquier registrar |
| Llave SSH | `ssh-keygen -t ed25519 -C "eduardo@ideas-boutique"` — subir la pública al panel Hetzner |
| Cuenta Backblaze B2 (para backups) | https://www.backblaze.com/b2/ — crear bucket `ideas-backups-{año}`, generar Application Key con scope al bucket |
| Acceso al repo GitHub | OK |

---

## 1 · Crear el VPS

En el panel de Hetzner Cloud:

1. **Add Server**.
2. **Location:** `Nuremberg` (eu-central) o `Ashburn` (us-east) — más cerca de Chile.
3. **Image:** Ubuntu 24.04.
4. **Type:** `CX22` (2 vCPU x86, 4 GB RAM, 40 GB SSD, ~€3.79/mes) — suficiente para 1000 productos y ~30 pedidos diarios.
5. **Networking:** marcar "Public IPv4" y "Public IPv6". Deja la SSH key que subiste.
6. **Cloud config (opcional):** dejar vacío, los scripts lo configuran después.
7. **Name:** `ideas-prod`.

Cuando termine, anotá la **IP pública IPv4** del server (ej. `49.13.X.X`).

---

## 2 · Apuntar el dominio al servidor

En tu registrar de `ideasboutique.cl` (NIC.cl):

```
@      A     49.13.X.X        TTL: 3600
www    A     49.13.X.X        TTL: 3600
```

Verificar propagación (puede tomar 5-30 min):

```bash
dig +short ideasboutique.cl
dig +short www.ideasboutique.cl
# Ambas deben devolver 49.13.X.X.
```

**No avances al paso 6 hasta que esto resuelva** (certbot lo necesita).

---

## 3 · Conectarte al VPS y subir los scripts

Desde tu máquina local:

```bash
ssh root@49.13.X.X
```

Una vez dentro, clonar este repo para tener los scripts a mano:

```bash
apt-get update -y && apt-get install -y git
git clone https://github.com/ShaggyKnight/edTech.git /tmp/ideas-bootstrap
cd /tmp/ideas-bootstrap/deploy
chmod +x *.sh
```

> Los scripts son **idempotentes** — re-ejecutarlos no rompe nada.

---

## 4 · Hardening del SO

Ejecutar en orden:

```bash
./01-firewall.sh          # UFW: solo 22/80/443
./02-ssh-hardening.sh     # disable root, key-only, fail2ban
./03-system-deps.sh       # nginx, postgres, python, certbot, etc.
./04-postgres-init.sh     # crea DB + user con perms limitados
```

Al finalizar `02-ssh-hardening.sh` el SSH root queda **deshabilitado**.
A partir de acá te conectás como el user `ideas`:

```bash
# Desde tu máquina:
ssh-copy-id ideas@49.13.X.X        # copiar tu pubkey al user ideas
ssh ideas@49.13.X.X                # ahora entrás como `ideas`
```

---

## 5 · Instalar la app

```bash
sudo /tmp/ideas-bootstrap/deploy/05-app-install.sh
```

Lo que hace:

- Clona el repo a `/srv/ideas/app/`
- Crea venv en `/srv/ideas/venv/`
- Instala `requirements.txt`
- Copia `ideas.env.production.template` → `/srv/ideas/app/.env` (queda vacío, lo completas tú)
- Crea directorios `/srv/ideas/{media,backups,logs}`
- Instala los `.service` / `.socket` de systemd
- **No arranca todavía** (falta llenar `.env` y migrar DB)

**Ahora editá el `.env` con los secretos reales:**

```bash
sudo -u ideas nano /srv/ideas/app/.env
```

Las variables y sus valores esperados están **documentados dentro de la
plantilla** `deploy/ideas.env.production.template` (que `05-app-install.sh`
ya copió a `/srv/ideas/app/.env`) — esa plantilla es la fuente de verdad:
Zoho Mail (SMTP), multi-gateway (KLAP/Khipu/mock), Clarity/Plausible,
modos del sitio, backups B2, feature flags. Ver también `SECURITY.md`
para las obligatorias de hardening.

Reglas rápidas:
- `DEBUG=False` SIEMPRE; `SECRET_KEY` de 50+ chars.
- `ADMIN_URL` no-obvio (los bots scanean `/admin/`).
- Email = Zoho **app password** (no la clave del webmail), ver `docs/email.md`.
- Pagos parten en `mock` — KLAP/Khipu se activan al tener credenciales.

Luego migrar + collectstatic + crear superuser:

```bash
cd /srv/ideas/app
sudo -u ideas /srv/ideas/venv/bin/python manage.py migrate
sudo -u ideas /srv/ideas/venv/bin/python manage.py collectstatic --noinput
sudo -u ideas /srv/ideas/venv/bin/python manage.py createsuperuser
# username: eduardo
# email: shaggyxreload@gmail.com
# password: <generado con un gestor>
```

Cargar el catálogo real (idempotente, dry-run sin `--aplicar`):

```bash
sudo -u ideas /srv/ideas/venv/bin/python manage.py cargar_catastro_perfumes --aplicar --con-imagenes
sudo -u ideas /srv/ideas/venv/bin/python manage.py cargar_uniformes --aplicar
```

Arrancar la app:

```bash
sudo systemctl enable --now gunicorn-ideas.socket
sudo systemctl status gunicorn-ideas.service
# Debe mostrar "active (running)"
```

---

## 6 · TLS con Let's Encrypt

**Solo después que el DNS resuelva** (paso 2).

```bash
sudo cp /tmp/ideas-bootstrap/deploy/nginx-ideas.conf /etc/nginx/sites-available/ideas
sudo ln -s /etc/nginx/sites-available/ideas /etc/nginx/sites-enabled/ideas
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo /tmp/ideas-bootstrap/deploy/06-tls-setup.sh
# certbot --nginx -d ideasboutique.cl -d www.ideasboutique.cl
```

Certbot:
- Pide tu email (usá `shaggyxreload@gmail.com`)
- Acepta TOS
- Pregunta si redirige http→https → **Sí, redirect**
- Renovación automática queda activa via `systemctl status certbot.timer`

---

## 7 · Activar HSTS (después de confirmar HTTPS estable)

Una vez que confirmás que el sitio carga bien en HTTPS por al menos
48 horas y todo funciona:

```bash
sudo -u ideas sed -i 's/SECURE_HSTS_SECONDS=0/SECURE_HSTS_SECONDS=31536000/' /srv/ideas/app/.env
sudo systemctl restart gunicorn-ideas.service
```

Esto activa HSTS por 1 año. **Cuidado:** los browsers cachean HSTS y
no se puede revertir sin tocar cada cliente. Por eso esperá a estar
seguro.

---

## 8 · Backups automáticos

Ya quedó programado el cron por `05-app-install.sh`. Verificá:

```bash
sudo crontab -u ideas -l
# Debe mostrar:
# 0 3 * * * /srv/ideas/app/deploy/backup.sh >> /srv/ideas/logs/backup.log 2>&1
# 0 4 1 * * /srv/ideas/app/deploy/restore-test.sh >> /srv/ideas/logs/restore-test.log 2>&1
```

**Forzar el primer backup manualmente** (para verificar que las creds
de B2 funcionan):

```bash
sudo -u ideas /srv/ideas/app/deploy/backup.sh
# Verás en Backblaze: ideas-2026-05-16-1030.sql.gz.gpg
```

---

## 9 · Verificación final

Checklist post-deploy:

```bash
# (1) Django check de prod
cd /srv/ideas/app
sudo -u ideas /srv/ideas/venv/bin/python manage.py check --deploy
# Debe pasar sin warnings.

# (2) Cargar sitio
curl -I https://ideasboutique.cl
# HTTP/2 200, headers Strict-Transport-Security presente si HSTS activado

# (3) Admin oculto NO responde 200 en /admin/
curl -I https://ideasboutique.cl/admin/
# HTTP 404

# (4) Admin SÍ responde en ADMIN_URL configurado
curl -I https://ideasboutique.cl/<ADMIN_URL>/
# HTTP 302 (redirect a login)

# (5) Tests del API público
curl https://ideasboutique.cl/robots.txt
curl https://ideasboutique.cl/sitemap.xml
```

---

## Deploy de cambios después del primer deploy

Una vez que el sitio anda y quieres subir nuevos commits:

```bash
ssh ideas@49.13.X.X
/srv/ideas/app/deploy/deploy.sh
```

`deploy.sh` hace:
1. `git pull` desde `master`
2. Reinstala deps si `requirements.txt` cambió
3. `migrate`
4. `collectstatic`
5. Reinicia gunicorn (sin downtime — systemd reload)

---

## Archivos en este folder

| Archivo | Propósito |
|---|---|
| `01-firewall.sh` | UFW: solo 22/80/443 |
| `02-ssh-hardening.sh` | Disable root, key-only, fail2ban |
| `03-system-deps.sh` | apt packages |
| `04-postgres-init.sh` | DB + user con perms mínimos |
| `05-app-install.sh` | App + venv + systemd + cron |
| `06-tls-setup.sh` | Certbot Let's Encrypt |
| `nginx-ideas.conf` | Reverse proxy + rate limiting + gzip + security headers |
| `gunicorn-ideas.service` | systemd service |
| `gunicorn-ideas.socket` | systemd socket (Unix socket en `/run/`) |
| `ideas.env.production.template` | `.env` plantilla |
| `backup.sh` | pg_dump + gpg + upload a B2 |
| `restore-test.sh` | Bajar último backup + restore en DB temporal + verificación |
| `deploy.sh` | Pull + migrate + collectstatic + reload |

---

## Troubleshooting

| Síntoma | Probable causa | Fix |
|---|---|---|
| `502 Bad Gateway` | gunicorn no arrancó | `sudo systemctl status gunicorn-ideas.service` → leer log |
| `400 Bad Request` | ALLOWED_HOSTS no incluye el dominio | revisar `.env` |
| `CSRF verification failed` | CSRF_TRUSTED_ORIGINS mal | revisar `.env`, debe ser `https://...` |
| `permission denied` al `git pull` | falta deploy key | ver paso 5 — agregar SSH key al repo |
| Backup falla | B2 creds incorrectas | `sudo -u ideas /srv/ideas/venv/bin/b2 authorize-account` |
| Certbot timeout | DNS no propagado o port 80 cerrado | `dig` + `sudo ufw status` |

---

## Mejoras opcionales (cuando crezca el negocio)

- **Sentry** para error tracking ($26/mes hobby plan).
- **Cloudflare** delante del VPS (gratis, CDN + DDoS protection).
- **DB managed** en Hetzner Postgres si volume crece.
- **Staging server** clon del prod para probar deploys.
- **CI/CD** con GitHub Actions → deploy automático al push a `master`.

Re-evaluar cuando lleguen a 500 pedidos/mes.
