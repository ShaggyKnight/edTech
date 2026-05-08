# Ideas Boutique 2.0

Sistema de retail para **Ideas Boutique** (Los Vilos, Chile) — boutique
familiar fundada en 1987 que vende perfumes originales, uniformes
escolares (San Francisco Javier, Divina Providencia, Lohse, Almagro) y
moda casual.

El sistema cubre el negocio entero en un solo Django:
- **Tienda online** pública con catálogo, carrito y pasarela.
- **POS presencial** con cobro en máquina física TUU.
- **Backoffice** para administrar productos, variantes, materiales,
  rendimientos, ofertas y stock.
- **Reportes** financieros (Caja, EERR, Balance, Producción).

---

## Stack

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.9+ |
| Framework | **Django 5.2** |
| API helper | Django REST Framework (instalado, hoy solo endpoints puntuales) |
| DB dev | SQLite |
| DB prod | PostgreSQL (`psycopg2-binary`) |
| Config | `django-environ` (`.env`) |
| Imágenes | Pillow |
| Frontend | Templates Django + CSS custom + **vanilla JS** (sin framework) |
| Iconos | Sprite SVG propio |
| Fuentes | Cormorant Garamond + Inter (Google Fonts) |
| HTTP cliente | `requests` (gateways de pago) |
| WSGI prod | `gunicorn` |
| Static prod | `whitenoise` (con manifest + compresión) |
| Pasarela online | Webpay Plus REST (Transbank) |
| Pasarela POS | TUU / Haulmer Pago Remoto |
| DTE / SII | Campos en `ReciboVenta` listos; integración OpenFactura pendiente |
| Tests | `django.test.TestCase` con `self.client` (215 tests) |

**No se usa React, Vue, Next, Tailwind ni HTMX hoy.**

---

## Apps Django

```
edTech/         settings + landing publica + robots.txt
accounts/       login y dashboard del staff (cajero/bodeguero/admin)
catalogo/       Familia, Colegio, Atributo, ValorAtributo,
                Producto, ProductoVariante, Oferta
bodega/         Tienda, Proveedor, Material, StockTienda,
                StockMaterial, MovimientoStock, MovimientoMaterial,
                Rendimiento, Inventario, InventarioLinea
                + CRUD de productos / variantes / materiales /
                  rendimientos / ofertas
pos/            Carrito presencial, ReciboVenta, ReciboVentaDetalle,
                payments (TUU/mock), DTE
ecommerce/      Tienda publica, Cliente, carrito online, payments
                (Webpay/mock), emails (boleta), cuenta del cliente
contabilidad/   MovimientoCaja con categorias para EERR
reportes/       Dashboard, Caja, Produccion, EERR, Balance General
```

---

## Funcionalidades

### Tienda online — `/tienda/`
- Catálogo con filtros AJAX (categoría, colegio cuando aplica, talla,
  rango de precio, búsqueda) — sin reload, URL sincronizada.
- Búsqueda accent-insensitive contra campos `nombre_buscable` y
  `descripcion_buscable` normalizados al guardar.
- Live search dropdown en el header (debounce 180 ms; sugiere productos
  + colegios; endpoint `GET /tienda/buscar.json?q=…`).
- Detalle de producto con chips de variante. Tallas en orden natural
  (4, 6, 8, …, S, M, L, XL). Perfumes ordenados por volumen creciente
  (5 ml → 200 ml) y dentro del volumen por concentración.
- Carrito en sesión, checkout con datos del cliente.
- Pasarela: `WebpayGateway` (Transbank Webpay Plus REST) en prod,
  `MockOnlineGateway` con simulador en `/tienda/mock-pago/` en dev.
- Confirmación atómica con `select_for_update`, idempotente.
- Boleta por email al quedar pagado (console backend en dev).
- Cuenta del cliente (login / logout / registro / historial de pedidos).

### POS presencial — `/pos/`
- Carrito en sesión separado del online.
- Aplica mejor oferta vigente por canal automáticamente.
- Checkout atómico con idempotency key, descuento de stock con `F()` y
  auditoría en `MovimientoStock`.
- Pasarela TUU (Haulmer) con polling, mock para dev.
- Listado de ventas, recibo imprimible, selección de tienda activa,
  carga rápida de stock.

### Backoffice — `/bodega/`
- Stock por tienda con alertas (agotado / bajo).
- Reposición con movimiento auditado.
- CRUD productos (imagen, familia, colegio, precios, descripción,
  variantes, precio_costo para margen).
- CRUD variantes (SKU + atributos talla / volumen / concentración).
- CRUD materiales (rollos de tela con proveedor y costo).
- CRUD rendimientos (cuántas prendas salen por rollo).
- CRUD ofertas: filtros (vigentes / programadas / vencidas / pausadas),
  por canal y búsqueda; pausar / reactivar (toggle); validaciones de
  fechas, valor y exclusividad producto/variante.
- Panel inline de ofertas en la edición de cada producto, con atajo
  para crear con producto pre-seleccionado.

### Reportes — `/reportes/`
- Dashboard general.
- Caja (entradas / salidas / saldo).
- Producción (rollos consumidos, prendas hechas).
- EERR con margen potencial por inventario valorizado.
- Balance General.

### Contabilidad
- `MovimientoCaja` categorizado: ingreso_venta, costo_inventario
  (compra de tela = activo, no gasto), costo_producción, gasto_operativo.
- Valorización de inventario al `precio_costo` (calculado on-demand).
- Asiento idempotente al pagar un recibo.

### Auth y roles
- Tres grupos: `cajero` (12 perms), `bodeguero` (41), `admin` (80) +
  superusuarios.
- Login del staff y login del cliente boutique separados.

---

## Levantar el proyecto en desarrollo

### Setup inicial (una vez)

```bash
# 1. Crear y activar virtualenv
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables (ver bloque mas abajo)
#    Crear .env en la raiz del repo

# 4. Migrar y poblar datos demo
python manage.py migrate
python manage.py seed_demo

# 5. Crear superusuario
python manage.py createsuperuser
```

### `.env` mínimo para dev

```env
SECRET_KEY=dev-key-no-usar-en-prod
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.101.10
USE_WHITENOISE=False
PAYMENT_GATEWAY=mock
ECOMMERCE_PAYMENT_GATEWAY=mock
ECOMMERCE_TIENDA_ID=1
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DTE_EMISSOR=mock
```

### Levantar el servidor

**Solo en localhost:**
```bash
python manage.py runserver
```
Abre `http://127.0.0.1:8000/`.

**En la red local (LAN) — para probar desde el celular o tablet:**
```bash
python manage.py runlan
```

El comando custom `runlan`:
1. Detecta automáticamente las IPs LAN de la PC (filtrando virtuales
   irrelevantes).
2. Imprime las URLs `http://<ip>:8000/` que se pueden abrir desde
   cualquier dispositivo en la misma red WiFi.
3. Avisa si el firewall de Windows no tiene regla para el puerto 8000.
4. Arranca `runserver 0.0.0.0:8000`.

**Antes de usar `runlan` por primera vez:**
- Agregá tu IP LAN a `ALLOWED_HOSTS` en `.env` (ej. `192.168.101.10`).
- En Windows, abrí el puerto 8000 con
  `scripts/firewall_open_8000.bat` ejecutado como Administrador
  (clic derecho → "Ejecutar como administrador").
- En Linux/Mac no hace falta abrir nada normalmente.

**Para apagar la regla de firewall después:**
`scripts/firewall_close_8000.bat` (también como Administrador).

### Otros comandos útiles

```bash
python manage.py test               # toda la suite (215 tests)
python manage.py test bodega        # solo una app
python manage.py seed_demo          # repobla con datos demo
python manage.py collectstatic      # copia static a /staticfiles (prod)
```

---

## Estructura de archivos relevantes

```
manage.py
requirements.txt
Procfile                            # deploy Heroku/Railway-style
.env                                # NO commitear (esta en .gitignore)
db.sqlite3                          # solo dev
edTech/
  settings.py                       # config con env vars + security
  urls.py                           # root URLconf
  views.py                          # landing + robots.txt
  templates/
    base.html                       # layout backoffice (sidebar)
    base_public.html                # layout tienda publica
    index.html                      # landing
  static/
    css/ideas.css                   # tienda publica (~800 lineas)
    css/backoffice.css              # backoffice
    js/...                          # vanilla JS sin framework
accounts/
  management/commands/
    seed_demo.py                    # seed con productos reales
    runlan.py                       # dev server + IPs LAN + firewall hint
catalogo/, bodega/, pos/, ecommerce/, contabilidad/, reportes/
  models.py + views.py + forms.py + tests*.py + templates/
scripts/
  firewall_open_8000.bat
  firewall_close_8000.bat
```

---

## Seguridad

`edTech/settings.py` ya configura, dependiendo del modo:

**Siempre:**
- `DATA_UPLOAD_MAX_MEMORY_SIZE` y `FILE_UPLOAD_MAX_MEMORY_SIZE` en 5 MB.
- `SESSION_COOKIE_HTTPONLY = True`, `SameSite = Lax`.
- `CSRF_COOKIE_SAMESITE = Lax`.

**Solo en prod (`DEBUG=False`):**
- `SECURE_PROXY_SSL_HEADER` para nginx/Railway/Fly que terminan TLS.
- `SECURE_SSL_REDIRECT` (controlable por env).
- HSTS (empezar en 0 y subir a `31536000` cuando el dominio esté
  estable).
- `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE`.
- `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY = 'same-origin'`,
  `X_FRAME_OPTIONS = 'DENY'`.

**`robots.txt`** servido en `/robots.txt` por Django: permite indexar
landing y catálogo público, bloquea backoffice, POS, reportes, admin
y todas las áreas transaccionales del cliente.

**Para mejorar a futuro (no implementado todavía):**
- Rate limiting en login / registro / endpoints AJAX (vía
  `django-ratelimit` + Redis o memoria local).
- CSP (Content Security Policy) con `django-csp` — requiere quitar
  inline scripts/styles primero.
- 2FA para admin / superuser (vía `django-otp`).
- Argon2 como hasher de contraseñas (`PASSWORD_HASHERS`) — necesita
  `argon2-cffi`.

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

---

## Tests

```bash
python manage.py test
```

Estado actual: **215/215 verde** (al 2026-05-08).

Tests por app:
- `accounts/tests.py` — auth + roles
- `bodega/tests.py` + `tests_crud*.py` + `tests_ofertas.py` + `tests_reponer.py`
- `catalogo/tests.py`
- `contabilidad/tests.py`
- `ecommerce/tests/` — catálogo, filtros, búsqueda, e2e, ofertas en
  PDP, cuenta del cliente, services, buscar.json
- `pos/tests/` — venta, idempotencia, gateway TUU mock
- `reportes/tests.py` — Caja, EERR, Balance

---

## Roadmap

Fases completadas: **A** (datos), **B** (POS), **C** (tienda online),
**M** (Django admin refinado), **N** (colegios + atributos perfumes),
**Ñ** (CRUD desde backoffice), **Ñ.1** (CRUD productos/variantes),
**Ñ.2** (materiales + telas + EERR), **O** (reportes financieros),
**O.1** (CRUD ofertas).

Pendiente:
- **E**: Facturación electrónica real (OpenFactura/Acepta) — los
  campos DTE en `ReciboVenta` ya están listos.
- Métricas de venta por canal/período/top sellers.
- Webhooks de TUU/Webpay (hoy es polling).
