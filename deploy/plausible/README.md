# Plausible Community Edition — self-host en el VPS

Setup paso a paso para correr Plausible Analytics (Community Edition)
en el VPS de Hetzner, accesible en `https://plausible.ideasboutique.cl`.

## Arquitectura

```
  Internet ──TLS──> nginx (puerto 443)
                       │
                       ▼  reverse proxy
                  127.0.0.1:8000  (container plausible)
                       │
                       ├──> plausible_db        (postgres, config + users)
                       └──> plausible_events_db (clickhouse, eventos)
```

Recursos en uso: ~300 MB RAM + ~5 GB disco inicial.
Crece ~10 MB/dia de eventos para sitios de bajo trafico.

## Prerequisitos en el VPS

- Docker + docker-compose-plugin instalados (`docker compose version` debe
  responder).
- nginx + certbot configurados (igual que para la app principal).
- DNS: `plausible.ideasboutique.cl` debe resolver al VPS antes de pedir
  el cert TLS.

## Deploy

### 1. Subir archivos al VPS

Desde tu local:

```bash
cd /ruta/al/repo
scp -r deploy/plausible root@ideas-prod:/srv/
```

O si preferis git clone en el VPS (recomendado para que cambios via git
pull lleguen aca tambien):

```bash
# En el VPS:
cd /srv/ideas/app/deploy
ls plausible/   # ya esta porque viene del repo
sudo cp -r plausible /srv/plausible
sudo chown -R root:docker /srv/plausible
```

### 2. Generar secrets y crear el `.env`

```bash
cd /srv/plausible
cp plausible.env.template .env

# Generar SECRET_KEY_BASE
openssl rand -base64 48
# Generar POSTGRES_PASSWORD
openssl rand -base64 24

# Editar .env y pegar ambos
nano .env

# Permisos restringidos (tiene secrets)
chmod 600 .env
```

### 3. DNS — agregar el subdomain

En Hetzner DNS Console → zona `ideasboutique.cl`:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | plausible | 178.105.168.8 | 3600 |

Verificar propagacion antes de seguir:

```bash
dig +short plausible.ideasboutique.cl
# Debe devolver 178.105.168.8
```

### 4. nginx — reverse proxy

```bash
sudo cp /srv/plausible/nginx-plausible.conf /etc/nginx/sites-available/plausible
sudo ln -s /etc/nginx/sites-available/plausible /etc/nginx/sites-enabled/plausible
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Cert TLS via certbot

```bash
sudo certbot --nginx -d plausible.ideasboutique.cl
# Aceptar todo (incluido el redirect HTTP -> HTTPS).
```

Certbot agrega el bloque `server { listen 443 ssl; ... }` solo y
configura el auto-renewal del cert.

### 6. Levantar Plausible

```bash
cd /srv/plausible
docker compose up -d
# Esperar ~30 segundos a que clickhouse y postgres terminen migraciones
docker compose logs -f plausible
# Buscar: "Running PlausibleWeb.Endpoint with cowboy 2.x at 0.0.0.0:8000"
# Ctrl+C para salir del logs (no apaga el container)
```

### 7. Crear el primer admin

Abrir `https://plausible.ideasboutique.cl/register` en el browser.
Crear cuenta:

- Email: `eduardo.tapia.contreras@gmail.com` (o el que uses)
- Password: una fuerte (guardar en gestor)
- Nombre: tu nombre

Despues del signup, Plausible te pide crear el primer sitio:

- Domain: `ideasboutique.cl`
- Timezone: `America/Santiago`

Listo. Te muestra el snippet de tracking — vos no lo vas a pegar a
mano, ya lo tenemos en `edTech/templates/base_public.html` apuntando
al subdomain self-host (ver paso 8).

### 8. Cerrar el signup publico

Editar `/srv/plausible/.env`:

```
DISABLE_REGISTRATION=invite_only
```

Recargar:

```bash
cd /srv/plausible
docker compose up -d plausible
```

Ahora la pagina `/register` rechaza signups nuevos (solo invite-only via
admin). Importante porque alguien que descubra el subdomain podria
crearse cuenta y consumir tu storage si no esta cerrado.

### 9. Activar el tracking en Django

En el `.env` de la app principal (`/srv/ideas/app/.env`):

```
ANALYTICS_DOMAIN=ideasboutique.cl
```

Importante: en el template `base_public.html` ya esta el `src` apuntando
a `https://plausible.ideasboutique.cl/js/script.tagged-events.js` (ver
commit del repo). Si todavia no, ese cambio entra en el commit del
deploy plausible.

Recargar Django para que tome el nuevo `.env`:

```bash
sudo systemctl restart gunicorn-ideas
```

### 10. Verificacion

Abrir `https://ideasboutique.cl` en el browser → debe disparar un
pageview. Volver al panel de Plausible → "Live visitors" deberia
mostrar `1` durante los primeros 30s. Tambien aparece la pagina en
"Top pages".

## Operacion

### Logs

```bash
cd /srv/plausible
docker compose logs --tail 100 plausible
docker compose logs --tail 100 plausible_db
docker compose logs --tail 100 plausible_events_db
```

### Actualizar Plausible a una version nueva

```bash
cd /srv/plausible
# Editar docker-compose.yml: cambiar v3.0.1 -> v3.x.x
nano docker-compose.yml
docker compose pull
docker compose up -d
# Esperar a que aplique migraciones
docker compose logs -f plausible
```

### Backups

Los datos viven en docker volumes:

- `plausible_postgres_data`  - config, users, sites
- `plausible_clickhouse_data` - eventos (lo grueso)

Backup manual del postgres:

```bash
cd /srv/plausible
docker compose exec plausible_db pg_dump -U postgres plausible_db | \
  gzip > /var/backups/plausible_pg_$(date +%Y%m%d).sql.gz
```

Backup de ClickHouse (mas complejo — usar `clickhouse-backup` cli o
copiar el volumen entero con el container detenido).

Recomendacion: agregar al `deploy/backup.sh` existente cuando este
volumen valga la pena guardar (despues de tener N meses de eventos).

### Apagar / encender

```bash
cd /srv/plausible
docker compose stop      # apaga todo, mantiene datos
docker compose start     # vuelve a prender
docker compose down      # apaga + remueve containers (datos persisten en volumes)
docker compose down -v   # ELIMINA volumenes — perdes TODO. NO usar salvo recrear desde cero.
```

## Troubleshooting

### `502 Bad Gateway` desde nginx

Plausible no esta listo (sigue migrando) o crash:

```bash
docker compose logs --tail 50 plausible
```

Buscar errores. Suele ser DATABASE_URL mal formado o CLICKHOUSE no
healthy. Esperar 60s mas — la primera vez tarda al correr migraciones.

### "Site not found" al abrir el dashboard

No creaste el sitio (paso 7). Login al panel y agrega `ideasboutique.cl`
en Settings.

### El contador no se mueve

1. Verificar que `ANALYTICS_DOMAIN=ideasboutique.cl` este en `.env` prod.
2. Verificar que el script aparezca en el HTML (View Source en el
   browser).
3. Network tab del browser: deberia haber un POST a
   `https://plausible.ideasboutique.cl/api/event` con status 202.
4. Si el POST falla (CORS, 4xx), revisar nginx config y logs.

### Disco lleno

ClickHouse no compactar tablas vacias automaticamente. Si en X meses el
volumen esta grande, correr:

```bash
docker compose exec plausible_events_db clickhouse-client \
  --query "OPTIMIZE TABLE plausible_events_db.events FINAL"
```
