# Ideas Boutique 2.0

Sistema integral de retail para **Ideas Boutique** (Los Vilos, Chile) — boutique
familiar fundada en 1987 que vende perfumes originales, uniformes
escolares (San Francisco Javier, Divina Providencia, Nicolás Federico
Lohse, Diego de Almagro) y moda casual.

El sistema cubre el negocio entero en un solo Django:
- **Tienda online** pública con catálogo, carrito y pago multi-gateway
  (KLAP tarjetas + Khipu transferencia; mock hasta tener credenciales).
- **POS presencial** con cobro físico TUU, modo pantalla completa
  diseñado para tablet en mostrador.
- **Backoffice** completo: catálogo, bodega, materiales, ofertas, stock,
  usuarios y roles, preview de emails.
- **Despacho**: cola de pedidos online pagados para preparar y despachar.
- **Reportes** financieros (Dashboard, EERR, Balance, Caja, Producción)
  con filtros HTMX en vivo y comparativa vs período anterior.
- **Hardening** pre-deploy y **receta concreta de deploy en Hetzner**.

---

## Stack

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ (prod) — dev local corre 3.9 + Django 4.2, ver `AGENTS.md` |
| Framework | **Django 5.2** (requirements) |
| Interactividad | **HTMX 2.0.4** + Alpine.js 3.14 (sin React/Vue) |
| API helper | Django REST Framework (endpoints puntuales) |
| DB dev | SQLite |
| DB prod | PostgreSQL (`psycopg2-binary`) |
| Config | `django-environ` (`.env`) |
| Imágenes | Pillow |
| Frontend | Templates Django + CSS custom + vanilla JS |
| Iconos | Sprite SVG propio |
| Fuentes | EB Garamond + Inter (tienda pública) · Inter (backoffice) · Cormorant (docs impresos) |
| HTTP cliente | `requests` (gateways de pago) |
| Codes de barra | `python-barcode` (SVG inline) |
| WSGI prod | `gunicorn` (Unix socket + systemd) |
| Reverse proxy | `nginx` con rate limiting + Let's Encrypt |
| Static prod | `whitenoise` (Compressed Manifest + brotli) |
| Pasarela online | Multi-gateway: KLAP (tarjetas) + Khipu (transferencia) — adapters en `ecommerce/gateways/`, mock hasta certificar credenciales |
| Pasarela POS | TUU / Haulmer Pago Remoto |
| DTE / SII | OpenFactura (Haulmer) — campos listos en `ReciboVenta`, canal-aware (`DTE_CANALES_HABILITADOS`) |
| Charts | Chart.js 4.4 (lazy-load defer) |
| Anti-fuerza-bruta | **django-axes 7** |
| Email transaccional | SMTP Zoho Mail (`ventas@ideasboutique.cl`, app password) |
| Analytics | Plausible self-host (privacy-first) + Microsoft Clarity (heatmaps/replays) — ambos opt-in por env |
| Backups | `pg_dump` + `gpg` AES256 + Backblaze B2 (S3-compat) |
| Tests | `django.test.TestCase` con `self.client` (**650+ tests**) |

---

## Apps Django

```
edTech/         settings + landing publica + robots.txt + sitemaps
                + página /info/ (envíos, cambios, tallas, contacto)
accounts/       login + dashboard del staff (cajero/bodeguero/despachador/
                admin/cliente) + CRUD de usuarios y roles (/cuenta/usuarios/)
                + preview de emails transaccionales (/cuenta/emails/)
                + django-axes lockout tests + comandos seed y `rol`
catalogo/       Familia, Colegio, Atributo, ValorAtributo,
                Producto, ProductoVariante, ProductoImagen,
                Oferta (con canal: presencial / online / ambos)
bodega/         Tienda, Proveedor, Material, StockTienda,
                StockMaterial, MovimientoStock, MovimientoMaterial,
                Rendimiento, Inventario, InventarioLinea
                + CRUD productos / variantes / materiales /
                  rendimientos / ofertas (con filtros AJAX)
pos/            Carrito presencial, ReciboVenta, ReciboVentaDetalle,
                payments (TUU/mock), DTE,
                búsqueda con alias de colegios locales (liceo, fraga,
                parro, publica), modo pantalla completa para tablet
ecommerce/      Tienda publica, carrito online, gateways/ (mock, KLAP,
                Khipu), emails transaccionales, "avísame cuando vuelva",
                cuenta del cliente, página de pedido público
despacho/       Cola de pedidos online pagados (rol DESPACHADOR):
                preparar, marcar despachado / reabrir, con auditoría
contabilidad/   MovimientoCaja con categorias para EERR
                + desglose por familia para el EERR
reportes/       Dashboard, Caja, EERR, Balance, Producción
                — todos con filtros HTMX live + comparativa vs período
                anterior + atajos rápidos de período + KPIs con drill-down
```

---

## Funcionalidades

### Tienda online — `/tienda/`
- Catálogo con filtros AJAX (categoría, colegio, talla, rango de precio,
  búsqueda) — sin reload, URL sincronizada via `hx-push-url`.
- Búsqueda accent-insensitive contra `nombre_buscable` y
  `descripcion_buscable` normalizados al guardar.
- Live search dropdown en header (debounce 180 ms; sugiere productos +
  colegios; endpoint `GET /tienda/buscar.json?q=…`).
- Detalle de producto con:
  - Galería de imágenes (modelo `ProductoImagen` + drag-drop para
    reordenar desde admin).
  - Chips de variante: tallas (4-16, S-XXL), volúmenes (5-250 ml),
    concentraciones (EDT, EDP, Elixir, Cologne) — ordenados por
    natural (no alfabético).
  - "Avísame cuando vuelva" para variantes agotadas.
  - Precio "desde" del producto refleja la oferta vigente correctamente
    (recalculada por variante, no descontada de precio_base).
  - Cuota inicial respeta el precio con descuento.
- Carrito en sesión, checkout con datos del cliente.
- Pago multi-gateway (`ecommerce/gateways/`): el cliente elige método
  si hay más de uno activo (`ECOMMERCE_GATEWAYS_ACTIVOS=klap,khipu`).
  KLAP (tarjetas ~2,75%) y Khipu (transferencia ~0,79%) son adapters
  con el shape real del proveedor pero operan en mock hasta cargar
  credenciales; `MockOnlineGateway` con simulador en `/tienda/mock-pago/`.
- Confirmación atómica con `select_for_update`, idempotente.
- Boleta por email al quedar pagado (console backend en dev, SMTP prod).
- Cuenta del cliente: login / logout / registro / historial de pedidos
  (con accesibilidad — número de pedido en aria-label).
- Modal "Vista rápida" con copy honesto ("Elegir talla y agregar →").
- Página `/info/` con secciones: envíos, cambios, tallas, contacto.
- Link a WhatsApp configurable via `PUBLIC_WHATSAPP` env var.
- SEO: sitemap.xml, robots.txt, JSON-LD Product en PDP, JSON-LD
  ClothingStore en landing.
- Analytics: Plausible opt-in vía `ANALYTICS_DOMAIN` + Microsoft
  Clarity (heatmaps/session replays) opt-in vía `CLARITY_PROJECT_ID`.
- "Avísame cuando vuelva la talla": suscripción por email en la PDP.
  Envía **UN solo correo** por suscripción cuando reponen stock
  (`FEATURE_EMAIL_STOCK_DISPONIBLE`), con link de cancelación.

### POS presencial — `/pos/`
- **Carrito sticky con "Cobrar" siempre visible** — diseñado para
  cajero sin scroll. La lista de items tiene scroll interno propio.
- **Stepper `[ − ] [ N ] [ + ]`** por línea con botones 44px+ touch-friendly.
- **Chips de talla prominentes** en la tabla de productos y carrito.
- **Modo pantalla completa para tablet** que persiste durante todo el
  ciclo de venta (cobrar → recibo → nueva venta en HTMX swaps, sin
  perder fullscreen API del browser).
- **Búsqueda con modismos locales de Los Vilos**:
  - `liceo` → Lohse, `lice`, `nicolas`
  - `fraga` / `sfj` → Javier (San Francisco Javier)
  - `parro` / `parroquial` → Divina Providencia
  - `publica` / `escuela` → Diego de Almagro
- **Match exacto en talla** (S/M/L/XL/XS/XXL) y concentraciones
  (EDT/EDP/Elixir/Cologne) — evita falsos positivos.
- **Match con unidad** para volúmenes: `30` matchea `"30 ml"` pero no
  `"130 ml"` ni `"300 ml"`.
- Banner de escaneo de código de barras (USB barcode scanner-friendly).
- Aplica mejor oferta vigente por canal automáticamente.
- Checkout atómico con idempotency key, descuento de stock con `F()` y
  auditoría en `MovimientoStock`.
- Pasarela TUU (Haulmer) con polling, mock para dev.
- Listado de ventas, recibo imprimible (con formato CLP correcto),
  selección de tienda activa, carga rápida de stock.

### Backoffice — `/bodega/`
- Stock por tienda con alertas (agotado / bajo).
- Reposición con movimiento auditado.
- CRUD productos (imagen principal + galería, familia, colegio, precios,
  descripción, variantes, precio_costo para margen).
- CRUD variantes (SKU + atributos talla / volumen / concentración) con
  filtros AJAX.
- CRUD materiales (rollos de tela con proveedor y costo).
- CRUD rendimientos (cuántas prendas salen por rollo).
- CRUD ofertas con filtros (vigentes / programadas / vencidas /
  pausadas), por canal y búsqueda; pausar / reactivar (toggle);
  validaciones de fechas, valor y exclusividad producto/variante.
- **Búsqueda de productos/variantes** en el form de oferta convertida
  en listbox visible (size=8) — evita el bug de `option.hidden` en
  selects cerrados.
- Panel inline de ofertas en la edición de cada producto.
- **Campos de perfumería** en el form de producto (marca, concentración,
  género, familia olfativa, notas clave) — la sección aparece solo si la
  familia es perfumería.
- Carga masiva de stock inicial.
- Galería de imágenes con drag-drop para reordenar.
- Drag-drop también para variantes de talla.
- **Usuarios y roles** (`/cuenta/usuarios/`): crear usuarios, asignar
  roles y resetear claves sin pasar por el Django admin (solo ADMIN).
- **Preview de emails** (`/cuenta/emails/`): ver todos los emails
  transaccionales renderizados con datos demo + envío de prueba.

### Despacho — `/despacho/`
- Cola de pedidos online **pagados**: "nuevos" (a preparar) y
  "despachados" (histórico), con contadores.
- Detalle por pedido pensado para empacar: variantes con talla/volumen
  legibles, datos del cliente y dirección.
- Marcar despachado / reabrir (timestamp + usuario, auditado).
- Notificación por email a los despachadores activos cuando entra un
  pedido pagado. Rol dedicado `despachador` (Blanca/admin ven todo igual).

### Reportes — `/reportes/`

**Dashboard** `/reportes/`:
- KPI cards: Ventas totales, Presencial, Online, Saldo de caja, Valor
  de inventario, Promedio por venta.
- **Filtros HTMX auto-submit sin recargar página**: Últimos N días,
  Tienda, **Canal (Todos / Presencial / Online)**.
- **Comparativa vs período anterior** — chip `↑ +18%` verde / `↓ -12%`
  rojo bajo cada KPI.
- **Drill-down**: cada card linkea a su detalle (`/pos/ventas/`,
  `/reportes/caja/`, `/bodega/stock/`) con los filtros activos.
- Gráficos: ventas por día (línea) + distribución por canal (donut).
- Top productos vendidos.
- Header con copy explicando "ventana móvil vs calendario" (para no
  confundir con el EERR).

**EERR (Estado de Resultados)** `/reportes/eerr/`:
- KPIs: Ingresos, Costo de ventas (COGS), Margen bruto, Utilidad neta.
- **Filtros HTMX auto-submit**: Período (mes / año / rango libre),
  Mes, Año, Tienda.
- **Atajos rápidos de período** (chips clickeables): Este mes, Mes
  anterior, Este año, Año anterior, Últimos 12 meses.
- **Comparativa vs período anterior**: chips con variación %, y para
  margen específicamente delta en **puntos porcentuales** (ppts) que es
  la convención contable correcta.
- **Desglose por línea de negocio (Familia)**: tabla con Ingresos,
  COGS, Margen y Margen% por familia, ordenado descendente — clarifica
  qué línea tira el carro.
- Top gastos del período.
- Gráfico de evolución mensual (12 meses).
- **Sección de potencial**: con la materia prima ya pagada, cuánto
  margen adicional se podría sumar si se confecciona y vende todo lo
  que la tela actual permite.

**Balance General** `/reportes/balance/`:
- Activos (caja + inventario terminado + materia prima), pasivos,
  patrimonio. Snapshot al `fecha` indicada.

**Caja** `/reportes/caja/`:
- Movimientos detallados, registro de salidas manuales (gastos
  operativos).
- KPI de saldo con **color condicional**: rojo si negativo, azul/verde
  si positivo (consistente entre Dashboard y Caja).

**Producción** `/reportes/produccion/`:
- Capacidad de confección con la materia prima en stock, valor
  potencial a precio de venta, costo potencial, margen potencial.

### Contabilidad
- `MovimientoCaja` categorizado: `ingreso_venta`, `costo_inventario`
  (compra de tela = activo, no gasto), `costo_produccion`,
  `gasto_operativo`.
- Valorización de inventario al `precio_costo` (calculado on-demand).
- Asiento idempotente al pagar un recibo.

### Auth y roles
- Cinco grupos de staff: `cajero`, `bodeguero`, `despachador`,
  `operador` (operación completa simplificada: POS + despacho + stock +
  productos + ofertas, sin materiales/reportes/admin — pensado para la
  dueña) y `admin` (todos los permisos) + superusuarios. Fuente de
  verdad en `accounts/roles.py`; asignación por CLI (`manage.py rol`)
  o web (`/cuenta/usuarios/`).
- **Cliente sin rol staff** → al entrar a `/cuenta/dashboard/` redirige
  a `/tienda/cuenta/pedidos/` (antes daba 403).
- Login del staff y login del cliente boutique separados.
- **django-axes**: 5 intentos por (usuario+IP), 1 hora de lockout, con
  comandos `axes_reset`, `axes_list_attempts`.

### Identidad de marca
- **Favicon "Clásico"** Ideas Boutique (anillos dorados + i italic
  sobre fondo negro):
  - `favicon.svg` para browsers modernos
  - `favicon.ico` multi-resolución (16/32/48)
  - `favicon-16/32/48/192.png` para sizes específicos
  - `apple-touch-icon-180.png` para iOS home screen
- `site.webmanifest` con tema dorado `#C9A96E`.
- `scripts/build_favicon_ico.py` para regenerar si cambia el diseño.

---

## Hardening pre-deploy

`edTech/settings.py` ya configura, dependiendo del modo:

**Siempre:**
- `DATA_UPLOAD_MAX_MEMORY_SIZE` y `FILE_UPLOAD_MAX_MEMORY_SIZE` en 5 MB.
- `SESSION_COOKIE_HTTPONLY = True`, `SameSite = Lax`.
- `CSRF_COOKIE_SAMESITE = Lax`.
- **django-axes** activo con thresholds configurables vía env.
- **`ADMIN_URL` configurable** vía env (default `admin/`, en prod
  algo no-obvio como `eduardo-blanca-x7k2/`).
- **`ADMINS`** populado desde `ADMIN_EMAIL` env — Django manda los
  reportes de error 500 automáticamente.

**Solo en prod (`DEBUG=False`):**
- `SECURE_PROXY_SSL_HEADER` para nginx que termina TLS.
- `SECURE_SSL_REDIRECT` (controlable por env).
- HSTS (empezar en 0 y subir a `31536000` cuando el dominio esté
  estable).
- `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE`.
- `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY = 'same-origin'`,
  `X_FRAME_OPTIONS = 'DENY'`.

`robots.txt` servido en `/robots.txt` por Django: permite indexar
landing y catálogo público, bloquea backoffice, POS, reportes, admin
(usa `settings.ADMIN_URL` dinámico) y todas las áreas transaccionales
del cliente.

Ver **`SECURITY.md`** para el runbook completo:
- Variables OBLIGATORIAS en prod.
- Cómo desbloquear lockouts.
- Cómo rotar `SECRET_KEY`.
- Procedimiento de respuesta a incidente.
- Plan de backups con verificación mensual.
- Cadencia de `pip-audit` y Django security releases.

**Pendientes (re-evaluar al crecer):**
- CSP estricta (hoy hay HTMX inline scripts que la rompen).
- 2FA admin (`django-otp`).
- WAF Cloudflare delante.
- Argon2 password hasher.

---

## Deploy en Hetzner

Receta paso a paso en **`deploy/README.md`**. Costo operativo
esperado: **~$5 USD/mes** (Hetzner CX22 + Backblaze B2).

Scripts numerados para ejecución secuencial:

```
deploy/
├── README.md                          # flujo completo + troubleshooting
├── 01-firewall.sh                     # UFW (22/80/443)
├── 02-ssh-hardening.sh                # user `ideas`, key-only, fail2ban
├── 03-system-deps.sh                  # nginx, postgres 16, certbot, b2-cli, gpg
├── 04-postgres-init.sh                # DB + user perms mínimos
├── 05-app-install.sh                  # clone + venv + systemd + cron
├── 06-tls-setup.sh                    # Let's Encrypt
├── nginx-ideas.conf                   # reverse proxy + rate limit + bloqueos
├── gunicorn-ideas.{service,socket}    # systemd Unix socket
├── ideas.env.production.template      # .env plantilla
├── backup.sh                          # pg_dump → gpg → Backblaze B2
├── restore-test.sh                    # validación mensual del backup
└── deploy.sh                          # git pull → migrate → reload sin downtime
```

---

## Convenciones del proyecto

- **Idioma del dominio en español**: nombres de modelos, campos,
  variables (`Producto`, `nombre_buscable`, `tienda_id`). Solo el
  framework queda en inglés.
- **Variantes XOR producto**: las relaciones a stock / ofertas usan
  uno u otro, nunca ambos. Hay `CheckConstraint` en los modelos.
- **Idempotencia en venta**: cada `ReciboVenta` tiene
  `payment_idempotency_key` (uuid4) — reintentos del cliente o
  webhook duplicado no doble-cobran ni doble-descuentan stock.
- **Atomicidad**: `pos.services.procesar_venta` y
  `ecommerce.services.confirmar_pedido` están envueltos en
  `@transaction.atomic` con `select_for_update` sobre `StockTienda`.
- **Comentarios Django multi-línea**: SIEMPRE `{% comment %}...{% endcomment %}`,
  NUNCA `{# ... #}` multi-línea (Django solo trata `{# %#}` como
  comentario en UNA línea — multi-línea filtra texto al HTML). Hay un
  lint preventivo: `python scripts/check_django_comments.py`.

---

## Levantar el proyecto en desarrollo

### Setup inicial (una vez)

```bash
# 1. Crear y activar virtualenv (Python 3.10+)
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables (ver .env.example)
cp .env.example .env
# editar .env con SECRET_KEY, DATABASE_URL, etc.

# 4. Migrar y poblar datos
python manage.py migrate

# Datos REALES del negocio (catastro versionado en catalogo/data/):
python manage.py cargar_catastro_perfumes --aplicar --con-imagenes  # 101 perfumes
python manage.py cargar_uniformes --aplicar                         # uniformes SFJ

# (Alternativa demo si no quieres datos reales: seed_demo + seed_perfumes_real)

# 5. Crear superusuario
python manage.py createsuperuser
```

### Levantar el servidor

**Solo en localhost:**
```bash
python manage.py runserver
```
Abre `http://127.0.0.1:8000/`.

**En la red local (LAN) — para probar desde celular o tablet:**
```bash
python manage.py runlan
```

El comando custom `runlan`:
1. Detecta automáticamente las IPs LAN.
2. Imprime las URLs `http://<ip>:8000/` para abrir desde cualquier
   dispositivo en la misma WiFi.
3. Avisa si el firewall de Windows no tiene regla para el puerto 8000.
4. Detecta si la red WiFi está marcada como "Public" (común en
   Windows) y la regla solo cubre "Private" — caso común que rompe
   acceso desde celular.
5. Arranca `runserver 0.0.0.0:8000`.

**Antes de usar `runlan` por primera vez:**
- Agregá tu IP LAN a `ALLOWED_HOSTS` en `.env`.
- En Windows, abrí el puerto con
  `scripts/firewall_open_8000.bat` como Administrador.

### Otros comandos útiles

```bash
python manage.py test                              # toda la suite (650+ tests)
python manage.py test pos                          # solo una app
python manage.py test reportes.tests.test_views   # un test class

# Datos del negocio (idempotentes, dry-run por default → --aplicar)
python manage.py cargar_catastro_perfumes --aplicar --con-imagenes
python manage.py cargar_uniformes --aplicar        # uniformes SFJ + fotos
python manage.py cargar_fotos_perfumes             # fotos faltantes desde retail
python manage.py actualizar_precios_uniformes      # precios uniformes

# Usuarios y roles
python manage.py rol                               # listar users + roles
python manage.py rol blanca --set=admin            # asignar rol
python manage.py crear_despachador                 # seed rol despachador

# Modo del sitio (normal / landing / mantenimiento)
python manage.py modo                              # ver modo actual
python manage.py modo landing

# Demo/legacy
python manage.py seed_demo                         # datos demo
python manage.py seed_perfumes_real                # 43 perfumes (superseded por catastro)

python manage.py collectstatic                     # /staticfiles (prod)
python manage.py check --deploy                    # warnings de prod

# Anti-fuerza-bruta (axes)
python manage.py axes_reset                        # desbloquear todos
python manage.py axes_reset_username eduardo       # desbloquear user
python manage.py axes_list_attempts                # ver intentos fallidos

# Lint propio
python scripts/check_django_comments.py            # detecta {# %#} multi-line
```

---

## Tests

```bash
python manage.py test
```

**Estado: 634 tests verdes** (al 2026-07-01, local Python 3.9 + Django 4.2).

> Los asserts de montos normalizan el NBSP (`\xa0`) que usa py3.9/dj4.2
> como separador de miles, así la suite pasa igual en local y en prod
> (Django 5.x usa punto).

Tests por app:
- `accounts/` — auth, roles, dashboard router, axes lockout, CRUD usuarios
- `bodega/` — CRUD productos/variantes/materiales, ofertas, reponer, AJAX
- `catalogo/` — modelos, precios con oferta (ProductoConVariantesPreciosTests),
  performance admin
- `contabilidad/` — categorías de MovimientoCaja, atomicidad
- `ecommerce/tests/` — catálogo, filtros, búsqueda, e2e, ofertas en
  PDP, cuenta del cliente, services, buscar.json, accesibilidad
- `pos/tests/` — venta, idempotencia, gateway TUU mock,
  búsqueda con alias (`PosSearchAliasMasTallaLetraTests`, etc.),
  perfumes (volumen + concentración), HTMX flow
- `reportes/` — Dashboard mejoras, EERR mejoras, Caja, Balance
- `edTech/` — `/info/`, WhatsApp link, PaginaInfoTests

---

## Estructura de archivos relevantes

```
manage.py
requirements.txt
Procfile                            # deploy Heroku/Railway-style
.env                                # NO commitear (en .gitignore)
.env.example                        # plantilla pública
db.sqlite3                          # solo dev
BUGS.md                             # registro de 16 bugs P0-P3 cerrados
SECURITY.md                         # runbook de seguridad
README.md                           # este archivo

docs/
  perfumes_catalogo_real.md         # catastro histórico mayo (superseded)
  whatsapp_templates.md             # copies para WhatsApp de Blanca
  email.md                          # setup Zoho Mail + DNS + flags

edTech/
  settings.py                       # config con env vars + axes + ADMIN_URL
  urls.py                           # admin URL dinámica
  views.py                          # landing + robots.txt + /info/
  middleware.py                     # HtmxMiddleware
  context_processors.py             # PUBLIC_WHATSAPP, SITE_URL, etc.
  templates/
    base.html                       # layout backoffice (sidebar)
    base_public.html                # layout tienda publica
    index.html                      # landing
    info.html                       # /info/ (envíos, cambios, tallas)
  static/
    favicon.svg + favicon-{16,32,48,192}.png + apple-touch-icon-180.png
    site.webmanifest
    css/ideas.css                   # tienda publica (~800 lineas)
    css/backoffice.css              # backoffice + .bo-chart-wrap
    css/sprint2-mobile.css          # mobile/tablet portrait

accounts/
  management/commands/
    seed_demo.py                    # productos demo
    seed_perfumes_real.py           # perfumes desde JSON (superseded por catastro)
    rol.py                          # listar/asignar roles por CLI
    modo.py                         # normal / landing / mantenimiento
    crear_despachador.py            # seed del rol despachador
    runlan.py                       # dev server + IPs LAN

catalogo/
  data/
    catastro_perfumes.json          # catastro REAL (101 perfumes) — fuente de verdad
    uniformes_sfj.json              # uniformes SFJ con variantes y precios
    uniformes_img/                  # fotos de uniformes versionadas
  management/commands/
    cargar_catastro_perfumes.py     # loader idempotente del catastro
    cargar_uniformes.py             # loader uniformes SFJ
    cargar_fotos_perfumes.py        # fotos faltantes desde retail
    actualizar_precios_uniformes.py
    optimizar_imagenes.py

catalogo/, bodega/, pos/, ecommerce/, despacho/, contabilidad/, reportes/
  models.py + views.py + forms.py + tests*.py + templates/

ecommerce/
  gateways/                         # base + mock + klap + khipu (multi-gateway)
  emails.py                         # boleta, aviso dueño, stock disponible, etc.

reportes/
  services.py                       # resumen_negocio, variacion_pct, etc.
  templates/reportes/
    dashboard.html, _dashboard_content.html
    eerr.html, _eerr_content.html
    _variacion_chip.html
    caja.html, balance.html, produccion.html

pos/
  search.py                         # ALIASES_COLEGIO + EXACT_MATCH_TOKENS
  templates/pos/
    home.html, recibo.html
    _pos_carrito.html, _pos_productos_tbody.html
    _pos_fullscreen.html            # modo pantalla completa

scripts/
  firewall_open_8000.bat / firewall_close_8000.bat
  build_favicon_ico.py
  check_django_comments.py          # lint preventivo

deploy/                             # receta Hetzner (ver sección Deploy)
```

---

## Roadmap

Fases completadas: **A** (datos), **B** (POS), **C** (tienda online),
**M** (Django admin refinado), **N** (colegios + atributos perfumes),
**Ñ** (CRUD desde backoffice), **Ñ.1** (CRUD productos/variantes),
**Ñ.2** (materiales + telas + EERR), **O** (reportes financieros),
**O.1** (CRUD ofertas), **QA Sweep** (16 bugs P0-P3), **Identidad**
(favicon Ideas), **POS UX Tablet** (fullscreen ciclo, sticky cart,
stepper, búsqueda con alias), **Reportes Live** (HTMX auto-submit,
drill-down, comparativa, desglose por familia), **Hardening**
(django-axes, ADMIN_URL, ADMINS, SECURITY.md), **Deploy Hetzner**
(receta completa con backups), **Emails transaccionales** (Zoho SMTP +
preview + flags), **Despacho** (rol + cola + notificaciones),
**Catastro real** (101 perfumes con género/precio/imagen verificados +
uniformes SFJ), **Multi-gateway** (KLAP/Khipu adapters), **Analytics**
(Clarity + Plausible self-host preparado).

Pendiente:
- **Pasarela de pago real**: contratar KLAP y/o Khipu, cargar
  credenciales y certificar (el código adapter ya está).
- **E**: Facturación electrónica real al SII (OpenFactura) — los
  campos DTE en `ReciboVenta` ya están listos, canal-aware.
- Infra Plausible: subdominio + nginx + Let's Encrypt (docker-compose listo).
- Webhooks de TUU (hoy es polling).
- Backup de `/srv/ideas/media/` (hoy solo se respalda la DB).
- Sentry para error tracking.
- CDN Cloudflare delante.
- Sistema de fidelización / programa "Familias Ideas".
- App nativa POS para Android tablet (PWA ya está parcialmente
  configurada).
