# Ideas Boutique 2.0 — Manual de operaciones

Guía rápida para administrar el sitio en producción. Pensada como
referencia diaria: conexión, comandos comunes, ubicaciones de archivos,
recuperación ante problemas.

---

## 1. Conexión al servidor

### Desde tu PC (Windows PowerShell o macOS Terminal)

```bash
ssh ideas@<IP-del-VPS>
```

- Reemplaza `<IP-del-VPS>` por la IP real del servidor (Hetzner Cloud → tu server).
- El usuario es `ideas` (NUNCA `root` — está bloqueado por seguridad).
- Usa tu clave SSH privada (`~/.ssh/id_ed25519` o la que hayas generado).

Si tu clave no es la default, especifícala:

```bash
ssh -i ~/.ssh/mi-clave ideas@<IP-del-VPS>
```

### Si SSH no funciona (emergencia)

1. Anda a [console.hetzner.cloud](https://console.hetzner.cloud).
2. Selecciona tu server → botón **`>_`** (Console web del navegador).
3. Loguéate como `root` con la password de Hetzner.
4. Desde ahí puedes diagnosticar/desbanear sin necesidad de SSH.

Causas típicas de no poder entrar:

| Síntoma | Causa | Fix |
|---|---|---|
| `Connection timed out` | fail2ban bloqueó tu IP (5 intentos fallidos = 1h de ban) | Web console → `fail2ban-client set sshd unbanip <TU-IP>` |
| `Permission denied (publickey)` | Tu clave no está autorizada para `ideas` | Web console → editar `/home/ideas/.ssh/authorized_keys` |
| `Connection refused` | SSH service caído | Web console → `systemctl restart ssh` |

---

## 2. Ubicaciones clave

### Configuración

| Path | Qué es |
|---|---|
| `/srv/ideas/app/.env` | Variables de entorno (SECRET_KEY, DATABASE_URL, modos, pagos, etc.) |
| `/etc/nginx/sites-enabled/ideas` | Config nginx (proxy a gunicorn + SSL + rate limit) |
| `/etc/systemd/system/gunicorn-ideas.service` | Unit gunicorn |
| `/etc/systemd/system/gunicorn-ideas.socket` | Socket Unix de gunicorn |
| `/etc/letsencrypt/live/ideasboutique.cl/` | Certificados TLS (auto-renovados por certbot.timer) |
| `/srv/ideas/MAINTENANCE` | Flag: si existe, sitio en modo mantenimiento |
| `/srv/ideas/LANDING_ONLY` | Flag: si existe, solo se ve la landing |

### Código y datos

| Path | Qué es |
|---|---|
| `/srv/ideas/app/` | Código (clone de GitHub master) |
| `/srv/ideas/venv/` | Virtualenv Python |
| `/srv/ideas/staticfiles/` | Assets (CSS, JS, imágenes) — generados por `collectstatic` |
| `/srv/ideas/media/` | Fotos de productos subidas por el admin |
| `/srv/ideas/backups/` | pg_dumps locales antes de subir a Backblaze |
| `/srv/ideas/logs/` | Logs de `backup.sh` y `restore-test.sh` |
| `/var/log/nginx/ideas.access.log` | Requests HTTP |
| `/var/log/nginx/ideas.error.log` | Errores nginx (404s, 502s, etc.) |

### Base de datos

- **Postgres** corriendo en `localhost:5432`
- DB: `ideas`
- User: `ideas` (password en `DATABASE_URL` del `.env`)
- Conexión directa: `sudo -u postgres psql ideas`

---

## 3. Aliases configurados (lo que tipeas día a día)

Ya cargados en `~/.bashrc` del user `ideas`. Si no funcionan, haz `source ~/.bashrc`.

| Alias | Hace |
|---|---|
| `modo` | Ver modo actual del sitio |
| `modo normal` | Tienda 100% abierta al público |
| `modo landing` | Solo `/` y `/info/` visibles, resto redirige a `/` |
| `modo mantenimiento` | "Volvemos pronto" (HTTP 503) en todo |
| `rol` | Listar usuarios y sus roles |
| `rol <username>` | Detalle de un usuario |
| `rol <user> --add=admin` | Agregar rol (admin/cajero/bodeguero/despachador/operador) |
| `rol <user> --del=cajero` | Sacar rol |
| `djmanage <comando>` | Cualquier `manage.py` (migrate, shell, createsuperuser, etc.) |
| `logs-app` | Logs de gunicorn/Django en vivo (Ctrl+C para salir) |
| `logs-nginx-err` | Errores de nginx en vivo |
| `logs-nginx-ok` | Accesos HTTP en vivo |
| `restart-app` | Reiniciar gunicorn |
| `estado` | Status de gunicorn + nginx + postgres |
| `edit-env` | Editar `/srv/ideas/app/.env` con nano |
| `deploy-quick` | `git pull` + restart (deploy sin migraciones) |

### Recargar aliases después de editarlos

```bash
nano ~/.bashrc       # editar
source ~/.bashrc     # cargar en la sesion actual
```

---

## 4. Modos del sitio (control de visibilidad pública)

Tres estados toggleables sin restart:

### `modo normal` — todo abierto

Tienda, catálogo, productos, carrito. Estado de operación habitual.

### `modo landing` — soft-launch

Solo se ven `/` (la home con la historia de la boutique) y `/info/`. Cualquier
otra URL pública redirige (HTTP 302) a `/`. Útil cuando todavía no quieres que
los clientes vean productos o precios pero ya quieres tener el dominio activo.

### `modo mantenimiento` — corte planificado

Cualquier URL del público devuelve la página "Volvemos pronto" con HTTP 503.
Google interpreta 503 como "vuelve más tarde" y **NO desindexa el dominio**.

### Quién ve qué en cada modo

| Visitante | Normal | Landing | Mantenimiento |
|---|---|---|---|
| Público anónimo | Todo | Solo `/` y `/info/` | "Volvemos pronto" |
| Tú (logueado como staff) | Todo | Todo | Todo |
| Bots / Google | Todo | Solo `/` y `/info/` | 503 (no desindexa) |

En todos los modos, los paths necesarios para administrar
(`/admin-R0z8NiGVcdE/`, `/cuenta/login/`, `/static/`, `/media/`,
`/healthz`) siguen accesibles.

---

## 5. Tareas comunes

### Subir cambios de código

```bash
# Cuando hay un nuevo commit en GitHub master
deploy-quick
```

Si el commit incluye migraciones de DB:

```bash
cd /srv/ideas/app
git pull origin master
djmanage migrate
djmanage collectstatic --noinput
restart-app
```

### Editar el `.env` (agregar credenciales, etc.)

```bash
edit-env
# Hacer cambios, Ctrl+O, Enter, Ctrl+X
restart-app
```

### Crear o cambiar el rol de un usuario

```bash
# Listar todos los usuarios
rol

# Detalle de blanca con sus permisos
rol blanca

# Darle rol admin (mantiene los otros que tenga)
rol blanca --add=admin

# Reemplazar TODOS los roles por cajero
rol mariana --set=cajero

# Sacarle solo el rol cajero (mantiene los otros)
rol mariana --del=cajero
```

Roles disponibles: `admin`, `cajero`, `bodeguero`, `despachador`, `operador`.

> **`operador` = la vista simplificada para la dueña**: POS, ventas,
> despacho, stock, productos y ofertas — sin materiales, sin etiquetas,
> sin reportes financieros y sin admin Django. Para Blanca:
> `rol blanca --set=operador` (o desde `/cuenta/usuarios/`).

> **También se puede desde el navegador**: como admin, entra a
> `https://ideasboutique.cl/cuenta/usuarios/` — crear usuarios, asignar
> roles y resetear claves sin tocar la terminal. Es lo recomendado para
> el día a día; el comando `rol` queda para scripts/emergencias.

### Crear un super usuario nuevo

```bash
djmanage createsuperuser
# Sigue las preguntas (username, email, password)
```

### Cargar / actualizar el catálogo (perfumes y uniformes)

Los datos del negocio viven versionados en el repo
(`catalogo/data/catastro_perfumes.json` y `uniformes_sfj.json`).
Los comandos son **idempotentes** (se pueden correr N veces) y por
default hacen dry-run — nada cambia sin `--aplicar`:

```bash
# Perfumes: crea/actualiza los 101 del catastro, desactiva los no listados,
# baja imágenes faltantes desde los retail configurados
djmanage cargar_catastro_perfumes                      # dry-run (ver qué haría)
djmanage cargar_catastro_perfumes --aplicar --con-imagenes

# Uniformes SFJ (productos + variantes por talla + precios + fotos)
djmanage cargar_uniformes --aplicar
```

### Ver los pedidos online entrantes (despacho)

- Pantalla: `https://ideasboutique.cl/despacho/` (rol `despachador` o `admin`).
- Cuando un pedido online queda pagado, llega un email a los
  despachadores activos.
- Preview de todos los emails del sistema: `https://ideasboutique.cl/cuenta/emails/`.

### Mercado Pago (billetera + tarjetas + cuotas)

Pasarela con redirección (Checkout Pro): el cliente paga en el entorno
de Mercado Pago con su saldo, tarjeta o cuotas, y vuelve a la tienda ya
pagado. Nosotros nunca vemos los datos de la tarjeta.

**Setup por única vez** (en el panel de Mercado Pago, con el RUT de Blanca):
1. Crear cuenta de vendedor en mercadopago.cl y una aplicación en
   *Tus integraciones*.
2. Copiar de *Credenciales de producción*: **Access Token** (`APP_USR-…`).
3. En *Webhooks*, configurar la URL
   `https://ideasboutique.cl/tienda/pago/webhook/mercadopago/` y copiar
   la **Clave secreta**.

**Activar:**

```bash
edit-env
#   ECOMMERCE_GATEWAYS_ACTIVOS=mercadopago,transferencia
#   MERCADOPAGO_ACCESS_TOKEN=APP_USR-...
#   MERCADOPAGO_WEBHOOK_SECRET=...   (la clave secreta del webhook)
restart-app
```

> Sin `MERCADOPAGO_ACCESS_TOKEN` el método no aparece en el checkout
> (queda en modo simulador). La plata cae en la cuenta Mercado Pago y se
> retira a la CuentaRUT. Los pedidos pagados llegan solos a Despacho →
> "Nuevos" (no hay que confirmar a mano como en la transferencia).

**Probar antes de cobrar de verdad:** Mercado Pago da dos juegos de
credenciales, **"de prueba"** y **"de producción"** (ojo: ambos empiezan
con `APP_USR-`, no hay prefijo `TEST-`). Poné el Access Token **de prueba**
en el `.env` e inicia sesión con el **usuario de prueba** (`TESTUSER…`) del
panel para pagar con las tarjetas de prueba. Cuando el pedido entre bien a
Despacho, cambia al Access Token **de producción**.

### Transferencia bancaria directa (respaldo de la pasarela)

Método de pago SIN pasarela: el cliente ve los datos de la cuenta,
transfiere y manda el comprobante por WhatsApp. **La plata hay que
verificarla a mano** contra la cartola del banco.

**Activar** (o desactivar sacando `transferencia` de la lista):

```bash
edit-env
#   ECOMMERCE_GATEWAYS_ACTIVOS=khipu,transferencia
#   TRANSFERENCIA_NOMBRE=Blanca Contreras ...
#   TRANSFERENCIA_RUT=12.345.678-9
#   TRANSFERENCIA_BANCO=BancoEstado
#   TRANSFERENCIA_TIPO_CUENTA=CuentaRUT
#   TRANSFERENCIA_CUENTA=12345678
restart-app
```

**Operar** (Blanca, cada día): Despacho → pestaña **"💸 Por confirmar"**.
Revisar la cartola del banco y:
- **✓ Confirmar pago** solo si el abono YA está: descuenta stock, envía
  la boleta y el pedido pasa a "Nuevos" para empacar.
- **✗ Anular** si nunca transfirieron (limpia la cola; no toca stock).

Solo `admin` y `operador` pueden confirmar/anular (es plata); el
despachador puro solo ve la lista.

### Descuento general de lanzamiento (ofertas por tienda o familia)

Backoffice → **Ofertas → Nueva oferta** (rol `admin` u `operador`).
Una oferta tiene **un** alcance:

- **🏷️ Toda la tienda** (checkbox) — descuento general a todo el catálogo.
- **Familia completa** — ej. solo los perfumes.
- **Producto** o **variante puntual** — como siempre.

Reglas útiles:
- Los descuentos **no se suman**: si un producto queda alcanzado por
  varias ofertas, se aplica la que MÁS descuenta. Ej: "-15% toda la
  tienda" + "-30% perfumes" → los perfumes bajan 30%, el resto 15%.
- El fin de la promo se programa con la **fecha de término** — al
  vencer, los precios vuelven solos (no hay que borrar nada).
- El **canal** permite diferenciar online vs tienda física.
- El precio tachado y el % aparecen automáticamente en catálogo, PDP,
  carrito y POS; el link "Ofertas" del sitio lista lo rebajado.

### Conectarse al Django shell (debugging avanzado)

```bash
djmanage shell
# Ejemplo: contar productos activos
# >>> from catalogo.models import Producto
# >>> Producto.objects.filter(activo=True).count()
```

### Conectarse a postgres directamente

```bash
sudo -u postgres psql ideas
# Una vez adentro:
# ideas=# \dt          listar tablas
# ideas=# SELECT * FROM auth_user;
# ideas=# \q           salir
```

---

## 6. Diagnóstico cuando algo falla

### El sitio no responde

```bash
# Estado de los servicios
estado

# Si gunicorn está down
restart-app

# Si nginx está down
sudo systemctl restart nginx
```

### Error 500 en alguna página

```bash
# Ver el traceback en vivo
logs-app

# En otra ventana, recargar la página que falla en el browser
# El traceback aparece en logs-app con el path completo
```

### Static files no cargan (CSS/JS roto)

```bash
djmanage collectstatic --noinput
restart-app
```

### Imágenes nuevas se ven pixeladas o pesan demasiado

```bash
# Dry-run para ver cuáles se reducirían
djmanage optimizar_imagenes

# Aplicar (reescribe los archivos)
djmanage optimizar_imagenes --aplicar
```

### Verificar certificado TLS

```bash
sudo certbot certificates
# Lista certs activos y cuándo expiran

# Forzar renovación si está por vencer
sudo certbot renew --force-renewal
```

### Ver qué bots están atacando

```bash
# Top IPs en los logs de la última hora
sudo grep "$(date '+%d/%b/%Y:%H')" /var/log/nginx/ideas.access.log \
  | awk '{print $1}' | sort | uniq -c | sort -rn | head -10

# Ver IPs baneadas por fail2ban
sudo fail2ban-client status sshd
```

---

## 7. Backups y restore

### Backups automáticos

- **Local**: pg_dump diario a las 3:00 AM en `/srv/ideas/backups/`
- **Nube**: subida a Backblaze B2 (encriptada con GPG passphrase del `.env`)
- **Test de restore**: corre el primer día de cada mes a las 4:00 AM para
  verificar que los backups son recuperables. Resultado en
  `/srv/ideas/logs/restore-test.log`.

> ⚠️ **El backup automático cubre SOLO la base de datos.** Las fotos de
> productos subidas a mano (`/srv/ideas/media/`) NO se respaldan todavía.
> Las bajadas por comando (`cargar_catastro_perfumes --con-imagenes`) se
> pueden regenerar, pero las subidas manualmente por el admin se perderían
> si muere el disco. Pendiente: agregar `media/` a `backup.sh`.

### Hacer un backup manual ahora

```bash
sudo /srv/ideas/app/deploy/backup.sh
ls -la /srv/ideas/backups/
```

### Restaurar desde un backup (procedimiento de emergencia)

⚠️ **Esto borra los datos actuales y los reemplaza por los del backup.**

```bash
# 1. Listar backups disponibles
ls -la /srv/ideas/backups/

# 2. Parar la app para que nadie escriba a la DB
sudo systemctl stop gunicorn-ideas.service

# 3. Desencriptar el backup (te pide la BACKUP_GPG_PASSPHRASE del .env)
gpg --decrypt /srv/ideas/backups/ideas-YYYY-MM-DD.sql.gpg > /tmp/restore.sql

# 4. Restaurar (drop DB + recreate)
sudo -u postgres dropdb ideas
sudo -u postgres createdb -O ideas ideas
sudo -u postgres psql ideas < /tmp/restore.sql

# 5. Limpiar y arrancar
rm /tmp/restore.sql
sudo systemctl start gunicorn-ideas.service
```

---

## 7½. Monitoreo de uptime (saber si el sitio se cayó ANTES que los clientes)

El sitio expone `https://ideasboutique.cl/healthz` — responde `ok` (HTTP 200)
siempre, incluso en modo mantenimiento. Un monitor externo gratis avisa
por email si deja de responder:

1. Crear cuenta en [uptimerobot.com](https://uptimerobot.com) (plan free = 50 monitores).
2. **Add New Monitor** → tipo `HTTP(s)`:
   - URL: `https://ideasboutique.cl/healthz`
   - Interval: 5 minutos
   - Alert contacts: tu email (y el de Blanca si quiere).
3. Opcional: segundo monitor tipo `Keyword` a `https://ideasboutique.cl/`
   buscando la palabra `Ideas` — detecta el caso "responde pero muestra
   una página rota".

Si llega la alerta: `estado` por SSH → `restart-app` → si persiste,
sección 6 (Diagnóstico).

---

## 8. Pausar el servidor (Hetzner billing)

**Importante**: Hetzner cobra lo mismo encendido o apagado. Si quieres ahorrar
realmente, hay que tomar snapshot y borrar el server.

### Procedimiento de pausa larga (>1 mes)

1. **Backup manual** (paso 7 arriba) — para tener copia local.
2. **Pasar a modo landing** o **mantenimiento**:
   ```bash
   modo mantenimiento
   ```
3. **En Hetzner Cloud Console** (web):
   - Tu server → **Snapshots** → "Take snapshot"
   - Espera 3-5 min hasta que diga `Available`
   - Nombre sugerido: `ideas-pause-YYYY-MM-DD`
4. **Anota** la IP actual y guarda tu `.env` afuera del server.
5. **Delete server** en Hetzner Console (el snapshot QUEDA).

Costo durante la pausa: ~€0.36/mes (solo el snapshot) vs ~€4.51/mes (server vivo).

### Reanudar después de la pausa

1. **Hetzner Console** → **Snapshots** → "Create server from snapshot"
2. Anota la IP nueva (cambia respecto a la original).
3. **Actualiza DNS**: A record de `ideasboutique.cl` → IP nueva.
4. Espera 5-15 min que propague.
5. SSH al server nuevo y re-emite el cert TLS (LetsEncrypt valida por IP):
   ```bash
   sudo certbot renew --force-renewal
   ```

---

## 9. Procedimiento de cambios sensibles

### Antes de tocar producción

1. Prueba en local primero (`runserver`).
2. Si es código → push a master en GitHub → `deploy-quick` en el server.
3. Si es config → edita `.env`, haz backup del valor anterior:
   ```bash
   sudo cp /srv/ideas/app/.env /srv/ideas/app/.env.bak.$(date +%Y%m%d)
   edit-env
   restart-app
   ```

### Si algo se rompe después de un cambio

```bash
# Volver al estado anterior
cd /srv/ideas/app
git log --oneline -5                    # ver últimos commits
git reset --hard <hash-anterior>        # rollback código
restart-app

# Si fue un cambio en .env
sudo cp /srv/ideas/app/.env.bak.YYYYMMDD /srv/ideas/app/.env
restart-app
```

---

## 10. Setup al clonar el repo en una máquina nueva

Después de `git clone`, activa el hook que valida los mensajes de commit:

```bash
git config core.hooksPath .githooks
```

Esto rechaza commits que incluyan `Co-Authored-By:` a herramientas AI
(política definida en `AGENTS.md`). Sin este paso, el hook no corre
porque vive en `.githooks/` versionado, no en `.git/hooks/` que no se
clona.

---

## 11. Contactos y referencias

- **Dominio**: ideasboutique.cl (DNS gestionado en NIC.cl o Cloudflare según corresponda)
- **VPS**: Hetzner Cloud — [console.hetzner.cloud](https://console.hetzner.cloud)
- **Email del owner** (recibe alertas de errores 500): `eduardo.tapia.contreras@gmail.com`
- **Repo de código**: github.com/ShaggyKnight/edTech
- **Backups**: Backblaze B2 bucket `ideas-backups-2026`

### Pagos y boleta (cuando se activen)

- **TUU** (POS presencial): tuu.cl → API key en `.env`
- **KLAP** (online, tarjetas ~2,75%): klap.cl → `KLAP_*` en `.env`
- **Khipu** (online, transferencia ~0,79%): khipu.com → `KHIPU_*` en `.env`
- Hoy ambos gateways online corren en `mock` (`ECOMMERCE_GATEWAYS_ACTIVOS=mock`)
- **OpenFactura** (boleta SII): openfactura.cl

### Para emergencias graves

1. Sacar el sitio del aire: `modo mantenimiento`
2. Diagnosticar tranquilo desde la web console de Hetzner
3. Pegarle el error a tu desarrollador con el contexto del log

---

## Apéndice: cómo se ve cada modo desde el navegador

| URL | Normal | Landing | Mantenimiento |
|---|---|---|---|
| `https://ideasboutique.cl/` | Home completa | Home completa | "Volvemos pronto" |
| `https://ideasboutique.cl/tienda/` | Catálogo | Redirige a `/` | "Volvemos pronto" |
| `https://ideasboutique.cl/info/` | Página info | Página info | "Volvemos pronto" |
| `https://ideasboutique.cl/admin-R0z8NiGVcdE/` | Admin Django | Admin Django | Admin Django |
| `https://ideasboutique.cl/cuenta/login/` | Login | Login | Login |
| `https://ideasboutique.cl/healthz` | `ok` | `ok` | `ok` |

Healthcheck (`/healthz`) siempre responde 200 para que el monitoring no
se confunda en modo mantenimiento.
