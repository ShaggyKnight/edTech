# Plan próximo sprint · Ideas Boutique

> ✅ **EJECUTADO (mayo–junio 2026) — documento histórico.** Los bloques
> B (branded docs/emails), C (seed → luego catastro definitivo de 101),
> D (DTE channel-aware) y el grueso de A entraron a master. Ver estado
> real en `README.md` (sección Roadmap) y `OPERACIONES.md`. Se conserva
> por las decisiones de negocio documentadas (§7 y §8).

Trabajo pendiente identificado a partir de:

1. `sprint_pos_plus_handoff/` (Ideas 11) — 11 fixes para el POS.
2. `branded_docs/` (Ideas 12) — emails, recibos y copy WhatsApp.
3. Catálogo real de 72 perfumes (provisto por la dueña en chat, mayo 2026)
   para seedear datos verdaderos.

**No hay nada commiteado todavía** — este documento es la propuesta.

---

## 1. Resumen ejecutivo

Tres bloques de trabajo que se pueden hacer en paralelo o serie:

| Bloque | Esfuerzo | Riesgo | Bloquea lanzamiento? |
|---|---|---|---|
| A · Sprint POS+ (11 fixes) | ~14 h dev | Bajo (cero migraciones salvo P6) | No |
| B · Branded docs (emails + recibos) | ~6 h dev | Bajo (templates puros) | **Sí** (boleta cliente) |
| C · Seed de perfumes reales | ~4 h dev + decisiones de schema | Medio (puede requerir migración) | **Sí** (sin datos no se ve nada) |

Mi recomendación de orden si se hace en serie:

```
C (seed)  →  B (branded docs)  →  A (sprint POS+)
```

Razón: sin productos cargados, el sitio sigue vacío para clientes
reales. Branded docs depende parcialmente del seed (el preview de
boletas necesita datos verdaderos). POS+ no bloquea nada y se puede
hacer "en paralelo" mientras la dueña prueba el catálogo cargado.

---

## 2. Bloque A — Sprint POS+ (11 fixes)

Origen: `sprint_pos_plus_handoff/CLAUDE.md`. El plan ya está bien
detallado en ese archivo. Lo único que agrego es ordenamiento de
commits y notas de riesgo.

### Orden de aplicación (commits separados, branch `sprint-pos-plus`)

| # | ID | Fix | Archivos | Tests | Notas |
|---|---|---|---|---|---|
| 1 | P1 | Bloqueo doble-tap en Cobrar | `_pos_carrito.html` + css | smoke | 15 min, mínimo riesgo |
| 2 | F4 | Splash confirmación visual | `_pos_recibo_inner.html` + css | smoke | 45 min, sin lógica |
| 3 | F1 | Microcopy próximo paso | `home.html` | smoke | 1 h, solo template |
| 4 | F3 | Atajos físicos teclado | `home.html` (JS) | smoke | 1 h, solo JS |
| 5 | P2 | Modal confirmación cobrar | `_pos_carrito.html`, view nueva | unit + integración | 1 h |
| 6 | P3 | Deshacer borrar línea | `cart.py`, template | unit | 45 min |
| 7 | P4 | Modal pago efectivo + vuelto | template + JS + view | integración | 2 h |
| 8 | P5 | Pantalla error pago específica | template + view | integración | 2 h |
| 9 | F2 | Modo entrenamiento | middleware + services | integración + middleware | 2 h |
| 10 | P7 | Anular venta del día | view + services + template | unit + permisos | 2 h |
| 11 | P6 | Cierre caja Z | view + template + model | unit + migración | 3 h (opcional, dejar para sprint propio) |

### Decisiones a tomar

- **P6 (cierre Z)**: requiere migración (modelo `CierreCaja` nuevo).
  ¿Lo dejamos para un sprint separado y reducimos el actual a 10 fixes?
  Sugiero **sí** — los otros 10 son de bajo riesgo y se pueden mergear
  rápido. P6 amerita su propia revisión de diseño.

- **F2 (modo práctica)**: agrega middleware nuevo + bandera en URL
  (`/pos/?practica=1`). ¿La dueña la va a usar realmente o es
  feature creep? Confirmar antes de implementar.

- **F3 (atajos teclado)**: ¿Tablets de Ideas tienen teclado BT?
  Si no, postergar.

### Definición de hecho (copiada del README del bundle)

- Cero confusión en las primeras 5 ventas de Blanca usando el POS
  modificado.
- Cajero nuevo puede hacer 3 ventas de práctica sin tutorial.
- TUU rechaza → cajero ve "qué" y "qué hacer", no error genérico.
- Borrar línea → recuperable en 5 segundos.
- Cierre Z imprimible al fin del día (si P6 entra).
- `python manage.py test pos` 100% verde.

---

## 3. Bloque B — Branded docs

Origen: `branded_docs/` con 8 emails + 2 recibos POS + WhatsApp copies.

### Plan de aplicación

**B.1 — Mover archivos al repo** (1 commit, ~30 min)

```
branded_docs/emails/_base.html          → edTech/templates/emails/_base.html
branded_docs/emails/boleta_compra.*     → edTech/templates/emails/
branded_docs/emails/aviso_dueno_orden.html
branded_docs/emails/registro_bienvenida.html
branded_docs/emails/recuperar_password.html
branded_docs/emails/carrito_abandonado.html
branded_docs/emails/stock_disponible.html
branded_docs/emails/pedir_resena.html
branded_docs/emails/recordatorio_familia.html

branded_docs/recibos/recibo_pos_termico.html  → pos/templates/pos/
branded_docs/recibos/recibo_pos_a4.html       → pos/templates/pos/
```

**B.2 — Cablear emails a los flujos existentes** (~3 h)

- `ecommerce/emails.py`: cambiar `render_to_string` de los emails
  actuales por las versiones nuevas. Verificar que el contexto que
  pasamos coincide con lo que esperan los templates.
- Agregar funciones nuevas para los emails que aún no existen:
  - `enviar_aviso_dueno(recibo)` — al confirmar pago online
  - `enviar_stock_disponible(producto, suscripciones)` — cuando vuelve stock
  - `enviar_carrito_abandonado(carrito)` — campaña +24h
  - `enviar_pedir_resena(recibo)` — +14 días post-compra
  - `enviar_recordatorio_familia(cliente)` — anual febrero (uniformes)
- Tareas Celery / cron para los emails programados (carrito,
  reseña, recordatorio familia). Si no quieres Celery todavía, usar
  un management command corrido por cron diario.

**B.3 — Recibos POS** (~1 h)

En `pos/views.py`:

```python
def recibo_imprimir(request, pk):
    recibo = get_object_or_404(ReciboVenta, pk=pk)
    formato = request.GET.get('f', 'termico')  # termico | a4
    template = f'pos/recibo_pos_{formato}.html'
    return render(request, template, {'recibo': recibo})
```

En `pos/urls.py`:

```python
path('recibo/<int:pk>/imprimir/', views.recibo_imprimir, name='recibo_imprimir'),
```

Botón en `_pos_recibo_inner.html` para abrir el recibo en pestaña nueva.

**B.4 — WhatsApp templates** (~5 min)

Mover `branded_docs/whatsapp/templates.md` a `docs/whatsapp_templates.md`.
Documentarlo en `OPERACIONES.md` para que Blanca los tenga a mano.

### Decisiones a tomar

- **SMTP de Gmail**: la dueña necesita crear un app password en
  `myaccount.google.com/apppasswords` con 2FA habilitado. Esto bloquea
  el envío de emails reales en prod. Lo podemos diferir si los emails
  están deshabilitados pero el código quedaría listo.

- **From address**: el template dice `Ideas Boutique <ventas@ideasboutique.cl>`.
  ¿Esa casilla existe ya? Si no, alternativas: alias en el dominio o
  usar la personal de Blanca (no recomendado para volumen).

- **Carrito abandonado y pedir reseña**: son emails programados que
  requieren cron o Celery. ¿Los activamos en este sprint o esperamos?
  Sugiero **postergar** — el código se deja listo pero apagado por
  flag (`FEATURE_CARRITO_ABANDONADO=False`).

---

## 4. Bloque C — Seed de perfumes reales

72 SKUs reales del local físico de Los Vilos. Necesita decisiones de
schema antes de implementar.

### Datos provistos (mayo 2026)

Cada perfume trae:
- `nombre` — ej. "Coralia for Women"
- `marca` — ej. "Aco Perfumes"
- `concentracion` — Body Spray | EDP | EDT | EDC
- `medida` — ej. "200 ml" (UNA medida por SKU, no varias)
- `familia_olfativa` — ej. "Fresca Oceánica"
- `descripcion` — frase corta
- `notas_clave` — lista de notas separadas por coma

### Lo que tenemos hoy

- `accounts/management/commands/seed_perfumes_real.py` — comando ya
  existe pero asume estructura distinta:
  - 1 perfume = N variantes por tamaño (formato "30ml, 50ml, 100ml")
  - Sin campos para marca, familia olfativa o notas

- Modelo `Producto` no tiene `marca`, `concentracion`, `familia_olfativa`,
  `notas`. La info se podría meter en `descripcion` pero queda sin
  estructura para filtros del catálogo.

### Opciones de schema (elegir una)

#### Opción 1 — Campos directos en `Producto` (mínimo cambio)

```python
class Producto(models.Model):
    # ... campos existentes ...
    marca = models.CharField(max_length=80, blank=True, db_index=True)
    concentracion = models.CharField(
        max_length=20, blank=True,
        choices=[
            ('EDP', 'Eau de Parfum'),
            ('EDT', 'Eau de Toilette'),
            ('EDC', 'Eau de Cologne'),
            ('BODY', 'Body Spray'),
            ('SET', 'Set / Estuche'),
        ],
    )
    medida_ml = models.PositiveIntegerField(null=True, blank=True)
    familia_olfativa = models.CharField(max_length=60, blank=True, db_index=True)
    notas_clave = models.CharField(max_length=300, blank=True)
```

**Pros**: 1 migración chica, queries simples. Funciona también para
perfumes uniformes (los campos quedan vacíos).
**Contras**: campos perfume-específicos en el modelo genérico.

#### Opción 2 — Modelo `PerfumeSpec` con OneToOne

```python
class PerfumeSpec(models.Model):
    producto = models.OneToOneField(Producto, on_delete=models.CASCADE, related_name='perfume')
    marca = models.CharField(max_length=80, db_index=True)
    concentracion = models.CharField(max_length=20, choices=...)
    medida_ml = models.PositiveIntegerField()
    familia_olfativa = models.CharField(max_length=60, db_index=True)
    notas_clave = models.CharField(max_length=300)
```

**Pros**: separación limpia, escalable a otros tipos (ej. ropa, perfumería
artesanal con otros campos).
**Contras**: joins extra en las queries del catálogo. Más código.

#### Opción 3 — JSON field genérico

```python
class Producto(models.Model):
    # ... campos existentes ...
    specs = models.JSONField(default=dict, blank=True)
    # specs = {"marca": "Lattafa", "concentracion": "EDP", "medida_ml": 100,
    #          "familia_olfativa": "Oriental Gourmand", "notas_clave": "..."}
```

**Pros**: flexible, sin migraciones cuando agreguemos campos.
**Contras**: queries por específico son feas, filtros del catálogo
necesitan índices GIN (Postgres). Para 72 perfumes es overkill.

**Mi sugerencia**: **Opción 1** — campos directos. Es lo más simple
y el catálogo de Ideas no va a tener "perfumes artesanales" con
schema distinto en el horizonte.

### Tareas de implementación

Asumiendo Opción 1:

1. **Migración** (10 min): agregar los 5 campos.
2. **Actualizar comando seed** (`seed_perfumes_real.py`):
   - Reescribir lista para usar la estructura nueva (72 SKUs).
   - Reemplazar la lógica de variantes-por-tamaño con productos simples.
   - Mantener idempotencia (`get_or_create`).
   - Mantener flags `--solo-mujer`, `--solo-hombre`, `--unisex`.
3. **Categorización mujer/hombre/unisex**: el catálogo provisto NO trae
   esta columna explícita. La infiero del nombre/notas:
   - "for Women", "Women", nombres tradicionalmente femeninos → mujer
   - "Man", "Men", "Homme", "Hombre" → hombre
   - Body sprays con nombre ambiguo → unisex
   - Listar las dudosas para que la dueña confirme.
4. **Estimación de precios de carga inicial** (heurística):
   - Body Spray 200ml → CLP 6.990 base, 4.990 oferta
   - EDT 100ml marca masiva (Aco, Lattafa, Maison Alhambra) → 14.990
   - EDT 100ml premium (Calvin Klein, D&G, Versace) → 39.990
   - EDP 100ml premium → 59.990
   - Sets → 19.990
   Estos son **referenciales**. La dueña ajusta después con el bulk
   edit de precios en `/bodega/productos/`.
5. **Admin Django**: mostrar los campos nuevos en list_display y
   list_filter (`marca`, `familia_olfativa`, `concentracion`).
6. **Catálogo público**: agregar filtros por marca y familia olfativa
   (sidebar de `/tienda/`).
7. **PDP**: mostrar el bloque "Notas olfativas" con las notas
   bonitas (tipo pastilla / chip).
8. **Búsqueda**: incluir `marca` y `notas_clave` en el `nombre_buscable`
   o agregar otro campo indexado.

### Aplicación a local + prod

Una vez merged a master:

```bash
# Local
git pull
python manage.py migrate catalogo
python manage.py seed_perfumes_real

# Prod
cd /srv/ideas/app
git fetch origin master && git reset --hard origin/master
djmanage migrate catalogo
djmanage seed_perfumes_real
djmanage collectstatic --noinput
restart-app
```

El seed es **idempotente** — se puede correr varias veces sin duplicar.

### Decisiones a tomar

- **Schema**: ¿Opción 1, 2 o 3?
- **Precios iniciales**: ¿confirmas los rangos de arriba o pasas tú
  los precios reales en otro mensaje?
- **Género**: ¿la dueña los confirma uno por uno, o aceptamos mi
  inferencia con review post-carga?
- **Imágenes**: el seed las deja vacías. La dueña sube via admin.
  ¿Tenemos una carpeta con fotos por SKU para hacer carga masiva?
- **Stock inicial**: ¿cuánto stock asignamos a cada SKU? Sugiero 10
  unidades por defecto y que la dueña corrija con su inventario real.

---

## 5. Dependencias y secuencia recomendada

```
                  ┌──────────────┐
                  │ Decisiones   │  (responder preguntas de cada bloque)
                  └──────┬───────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       Bloque C      Bloque B      Bloque A
      (seed perf.) (branded docs) (sprint POS+)
            │            │            │
            └────┬───────┘            │
                 │                    │
                 ▼                    │
         Carga datos prod             │
         (seed + migrate)             │
                 │                    │
                 └────────────────────┤
                                      ▼
                          modo normal (lanzamiento)
```

C y B se pueden hacer en paralelo si hay dos developers. A puede
correr en paralelo a ambos siempre que no toque el modelo `Producto`.

---

## 6. Pendientes que NO entran en este sprint

Identificados pero fuera de scope:

- Webhooks de Webpay/TUU (sigue siendo polling).
- Sentry para tracking de errores.
- WebP / responsive images.
- CSP estricta.
- 2FA admin.
- SMS templates.
- Push notifications PWA.
- Newsletter mensual.
- Gift cards.

Documentar en `BUGS.md` (o `ROADMAP.md`) para no perderlos.

---

## 7. Decisiones tomadas (mayo 2026)

1. **Schema del seed**: campos directos en `Producto` + archivo JSON
   versionado como fuente de verdad. Si necesitamos más campos, agregar.
2. **Género de perfumes**: usar mi inferencia. Casos dudosos quedan
   marcados en `docs/perfumes_catalogo_real.md` para review post-carga.
3. **Precios**: usar la heurística referencial. La dueña ajusta después
   con bulk edit en `/bodega/productos/`.
4. **P6 (cierre Z)** y todo lo de **efectivo**: postergado. La dueña no
   maneja efectivo en este momento — el POS opera virtual.
5. **Emails programados**: TODOS apagados (feature flags off).

## 8. Estrategia de lanzamiento (impacto en alcance)

La dueña confirmó:

> "Partiremos por la tienda online. Sin la tienda física aún. Cuando se
> integre el SII, las boletas online van al SII, pero las del POS
> presencial NO, hasta que se implemente la tienda física y se integre
> con TUU. De momento el POS se usará para movimientos virtuales que
> reflejan la tienda física, pero no se implementa en local físico aún."

### Consecuencias en el sprint

**Fuera del scope inmediato:**

- ❌ **P4 — Modal pago efectivo + vuelto** (sin ventas en efectivo).
- ❌ **P5 — Pantalla error TUU** (TUU sigue en mock, sin uso real).
- ❌ **P6 — Cierre caja Z** (ya postergado).
- ⚠️ **F2 — Modo entrenamiento** — el POS ya es "virtual" hoy, agregar
   un modo práctica encima es redundante. Postergar.

**Quedan en el sprint** (los que SÍ aportan al POS virtual):

- ✅ **P1** — Bloqueo doble-tap (afecta cualquier flujo de cobranza).
- ✅ **P2** — Modal confirmación al cobrar (igual aplica al virtual).
- ✅ **P3** — Deshacer borrar línea.
- ✅ **P7** — Anular venta del día (útil para corregir movimientos
   virtuales).
- ✅ **F1** — Microcopy próximo paso.
- ✅ **F3** — Atajos teclado (si Blanca tiene teclado BT).
- ✅ **F4** — Splash confirmación visual.

Sprint POS+ se reduce de **11 fixes a 7**, ~6 h dev en lugar de 14 h.

### Cambios técnicos transversales que se agregan

Por la estrategia de "online va a SII, presencial no", aparece un
**nuevo item de trabajo** que NO estaba en los handoffs:

**D — DTE channel-aware** (~2 h)

- Nuevo setting `DTE_CANALES_HABILITADOS = ['online']` (lista de canales
  que generan boleta SII).
- Adaptar `ecommerce/services.py` y `pos/services.py` para chequear si
  el canal del recibo está en la lista antes de invocar OpenFactura.
- Cuando llegue la tienda física + TUU, agregar `'presencial'` a la
  lista (1 línea en .env).
- Tests: `test_dte_no_emite_para_canal_no_habilitado`.

**E — POS virtual (sin TUU, sin efectivo)** (~3 h)

El flujo actual del POS asume pago real (TUU o efectivo). En modo
virtual:

- El botón "Cobrar" registra la venta directo, sin invocar TUU mock.
- No se calcula vuelto, no se procesa tarjeta.
- El estado del recibo queda `pagado` automáticamente (es virtual).
- `ReciboVenta` gana un campo booleano `virtual` (o se usa una nueva
  forma de pago `VIRTUAL` en el enum existente).
- En el ticket POS aparece "MOVIMIENTO VIRTUAL — sin valor fiscal".
- Cuando la tienda física arranque y se integre TUU, el flag se
  desactiva.

Esto reemplaza a F2 (modo práctica) — más útil porque es el modo
operativo real, no un sandbox.

### Reordenamiento del plan

| Bloque | Antes | Ahora |
|---|---|---|
| A · Sprint POS+ | 11 fixes / 14 h | 7 fixes / ~6 h |
| B · Branded docs | 8 emails + 2 recibos / 6 h | Igual |
| C · Seed perfumes | ~4 h | Igual |
| **D · DTE channel-aware** | — | **2 h (nuevo)** |
| **E · POS virtual** | — | **3 h (nuevo)** |
| **Total** | ~24 h | **~21 h** |

Orden recomendado para lanzar la **tienda online**:

```
C (seed)  →  B (branded docs)  →  D (DTE channel-aware)  →  E (POS virtual)  →  A (sprint POS+)
```

Hasta D inclusive, la tienda online está lista para vender (sin POS
físico aún, eso es E + A).

## 9. Próximo paso concreto

Las 5 decisiones están tomadas. Voy a:

1. Implementar Bloque C (seed perfumes) en local — **sin push**.
2. Mostrar resultado para tu review.
3. Cuando lo apruebes, push en branch `seed-perfumes-reales`.
4. Después arranco Bloque D y E en paralelo con B (todos sin push hasta
   que des OK).
5. Bloque A (sprint POS+ reducido) al final, como mejoras de polishing.
