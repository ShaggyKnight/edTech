# BUGS — QA Ideas Boutique (15/05/2026)

Base URL probada: http://192.168.1.87:8000
Usuario probado: admin (autenticado en backoffice y tienda)

## P0 — Bloqueantes

### BUG-001 · "Agregar al carrito" no agrega productos
- Ruta: /tienda/p/13/ (Polera básica unisex) y /tienda/p/11/ (Oud Royal Elixir)
- Pasos:
  1. Entrar a la ficha
  2. Elegir talla M / formato 100 ml
  3. Click en "Agregar al carrito · $X"
  4. Ir a /tienda/carrito/
- Esperado: el item aparece en el carrito y el contador del header sube.
- Actual: carrito sigue en 0 items, sin feedback al usuario.
- Causa raíz identificada en consola del browser:
  > An invalid form control with name='' is not focusable.
  > <input ... id="pdp-notify-email" required>
  El input del bloque "Avísame cuando vuelva" (oculto via `hidden`) tenía
  `required`. Esa input estaba ADENTRO del `<form id="pdp-form">`. Al hacer
  click en "Agregar al carrito" el browser intentaba validar todos los
  required del form, no podía focusear un input dentro de un contenedor
  hidden, y cancelaba el submit silenciosamente. Por eso no llegaba POST
  al server (los pocos POSTs que vimos en logs eran cuando el notify-form
  todavía no se había abierto/cerrado y por timing el browser no validaba).
- Fix: quitar `required` del input notify-email. El JS de `notifySubmit`
  ya valida el email con regex antes de procesar.
- ✅ Resuelto en commit pendiente — `ecommerce/templates/ecommerce/producto.html`.
  Test de regresión: `ecommerce/tests/test_carrito_htmx_anon.py
  · test_pdp_notify_email_no_tiene_required`.

### BUG-002 · Estado del botón "Elige tu formato primero" se queda pegado
- Ruta: /tienda/p/11/
- Pasos: seleccionar 30 ml → seleccionar 100 ml → volver a 30 ml
- Actual: en algunas transiciones el botón vuelve a "Elige tu formato primero"
  (disabled) aunque haya formato marcado.
- Análisis: el JS sólo setea `btn.disabled = false` en UN lugar (chip handler,
  producto.html). Nunca lo vuelve a `true` después del page load. La única
  manera de que el botón quede stuck disabled es:
  1. Page reload (estado inicial del HTML), o
  2. Una excepción JS aborta el handler ANTES de llegar a `btn.disabled = false`.
  Probablemente este bug era downstream de BUG-001 (el form no submiteaba, el
  usuario clickeaba otro chip, y la sensación era "botón pegado").
- Fix defensivo: reordenar el handler para que `hidden.value` y `btn.disabled = false`
  corran PRIMERO, y envolver todos los updates visuales en try/catch. Así un
  error futuro en un update visual nunca puede dejar el botón inutilizable.
- ✅ Resuelto en commit pendiente — `ecommerce/templates/ecommerce/producto.html`
  (chip click handler refactor).

## P1 — Datos / cálculos

### BUG-003 · "DESDE $X" del listado no respeta la oferta vigente
- Ruta: /tienda/ (listado) → Oud Royal Elixir
- Listado dice: "DESDE $38.491".
- Real (oferta -10% sobre Oud, ver /bodega/ofertas/):
  - 30 ml $44.990 → $40.491
  - 100 ml $64.990 → $58.491
- Esperado: "DESDE $40.491".
- Causa raíz: `Producto.precio_oferta_online` hacía `precio_minimo − desc`
  donde `desc` se calculaba contra `precio_base` (que en este producto valía
  $64.990, la variante grande). Resultado: 44.990 − 6.499 = 38.491.
  El descuento porcentual se restaba de la variante chica pero estaba
  proporcional al precio de la grande.
- Fix: iterar variantes activas y aplicar el descuento por variante
  (`v.precio - desc_v`), devolver `min(...)`. Mismo criterio para
  `descuento_porcentaje_online` (badge) y para `tiene_oferta_online`
  (ahora también True si la oferta vive en una variante específica).
- ✅ Resuelto en commit pendiente — `catalogo/models.py`.
  Tests de regresión: `catalogo/tests_precios.py
  · ProductoConVariantesPreciosTests` (4 tests).

### BUG-004 · Cuota mostrada antes de elegir variante usa el precio sin descuento
- Ruta: /tienda/p/11/ (estado inicial, sin formato elegido)
- Muestra: "$38.491 (con $44.990 tachado) · 3 cuotas sin interés de $14997"
- 14997 = 44990 / 3. Debería ser 38491 / 3 = 12.830 (o, si "desde" se corrige
  a 40.491, sería 13.497).
- Acción: que la cuota se calcule sobre el mismo precio que muestra "desde".
- Causa raíz: el `{% widthratio %}` en la PDP dividía `producto.precio_minimo`
  (precio sin descuento) o `producto.precio_base` en lugar de
  `producto.precio_oferta_online` cuando había oferta vigente. Ahora con
  BUG-003 ya fixed, el "desde" es $40.491 y la cuota debe ser $13.497.
- Fix: condicionar el widthratio a `tiene_oferta_online`, asignar a una var
  con `as` y pasar por `|intcomma` para el separador de miles.
- ✅ Resuelto en commit pendiente — `ecommerce/templates/ecommerce/producto.html`
  (líneas de PDP con variantes y sin variantes).

### BUG-005 · Formato monetario inconsistente
- Casos detectados:
  - /tienda/p/11/ estado inicial: "$14997" sin separador.
  - /reportes/ (Dashboard): "Promedio por venta $34437" sin separador
    (mismo dato en /pos/ventas/ aparece "$34.437" bien formateado).
  - /tienda/pedido/<uuid>/: precios como "$64990.00", "$58491.00",
    "-$6499.00" con dos decimales y sin punto de miles.
- Esperado: formato CLP `$XX.XXX` sin decimales en todo el sitio.
- Acción: centralizar en un template filter (ej. `|clp`) y reemplazar.
- Causa común: en los 3 sitios faltaba `|floatformat:0|intcomma` para
  Decimals, o `widthratio ... as var` + `|intcomma` para enteros derivados.
  El locale Django (es-CL) ya emite "." como separador via `intcomma`.
- Fix puntual (sin filtro central, para minimizar blast radius):
  - PDP cuota inicial: arreglada con BUG-004.
  - Dashboard "Promedio por venta": agregado `as prom_venta` + `|intcomma`
    al widthratio.
  - /tienda/pedido/<uuid>/: agregado `|floatformat:0|intcomma` en todas
    las celdas de monto (precio_unitario, subtotal, recibo.subtotal,
    descuento, total). También el email plaintext `boleta.txt`.
- Pendiente (futuro): crear un template filter `|clp` que envuelva este
  patrón y barrer el resto del sitio. Ya queda anotado como deuda técnica.
- ✅ Resuelto en commit pendiente — `reportes/templates/reportes/dashboard.html`,
  `ecommerce/templates/ecommerce/pedido.html`,
  `ecommerce/templates/ecommerce/email/boleta.txt`.
  Test actualizado: `reportes/tests/test_views.py
  · DashboardContenidoTests.test_admin_ve_dashboard_con_totales`.

### BUG-006 · Discrepancia de métricas Dashboard vs EERR
- Dashboard "últimos 30 días": Ventas totales $344.372
- EERR "Mayo 2026": Ingresos $314.392
- No es bug de cálculo (ventanas distintas) pero el copy debería aclararlo.
- Fix: el subheader del Dashboard ahora dice "Últimos N días corridos:
  DD-MM-YYYY — DD-MM-YYYY · para análisis por mes o año usa Estado de
  Resultados" con link directo a /reportes/eerr/. Hace explícito que la
  ventana es móvil y guía al usuario al EERR cuando necesita el corte
  contable.
- ✅ Resuelto en commit pendiente — `reportes/templates/reportes/dashboard.html`.

### BUG-007 · Margen bruto con doble unidad
- /reportes/eerr/ → "Margen bruto $126.892 · 0.40% — 40% del ingreso"
- Mostrar solo "40,4 % del ingreso" (o el ratio, no ambos).
- Causa raíz: `eerr.margen_pct` se guarda como decimal `0..1` (ver
  `contabilidad/services.py` línea 184). El template lo mostraba dos veces:
  `{{ margen_pct|floatformat:2 }}%` → "0.40%" (sin multiplicar por 100)
  y `{% widthratio margen_pct 1 100 %}%` → "40%". Doble unidad +
  primer número con escala equivocada.
- Fix: una sola expresión calculada como `widthratio margen_bruto ingresos 100`
  → "40% del ingreso". Si `ingresos == 0` muestra fallback amistoso.
- ✅ Resuelto en commit pendiente — `reportes/templates/reportes/eerr.html`.

## P2 — Navegación / UX

### BUG-008 · Enlaces del footer apuntan a anchors genéricos
- Footer (home y tienda):
  - Envíos → #visitanos
  - Cambios → #visitanos
  - Contacto → #visitanos
  - Sucursal → #visitanos
  - Tallas → #uniformes
- Acción: crear páginas reales /envios/, /cambios/, /tallas/, /contacto/
  o consolidar las 4 a una sola página /info/ con secciones, y eliminar
  las labels redundantes.
- Fix elegido: nueva página `/info/` con anchors reales:
  `#envios`, `#cambios`, `#tallas`, `#contacto`. Copy boutique-real
  (Starken/Chilexpress, 30 días corridos, guía de tallas linkeada al
  catálogo, dirección + horario). Footer del landing y del shop ya
  apuntan a las 4 secciones específicas. "Sucursal" reutiliza
  `#contacto`. El bloque WhatsApp queda condicional a
  `{% if PUBLIC_WHATSAPP %}` para que BUG-009 lo cablée.
- ✅ Resuelto en commit pendiente:
  - Nueva vista `edTech.views.info` + URL `/info/`.
  - Nuevo template `edTech/templates/info.html`.
  - Footer actualizado en `ecommerce/templates/ecommerce/_shop_footer.html`
    y en el landing (`edTech/templates/index.html`).
  - Tests: `edTech.tests.PaginaInfoTests` (4 tests).

### BUG-009 · "WhatsApp directo" no es enlace
- Home, sección Visítanos: el texto "WhatsApp directo / Pedidos y reservas"
  es un <span>/<div>, no un <a href="https://wa.me/56XXXXXXXXX">.
- Acción: convertir en link real con el número de la tienda.
- Fix: nueva env var opcional `PUBLIC_WHATSAPP` (formato E.164 sin `+`,
  ej `56912345678`). El context processor `public_settings` la expone a
  los templates. Si está seteada, el bloque WhatsApp en `index.html`
  (sección Visítanos) y en `info.html` (sección #contacto) se renderiza
  como `<a href="https://wa.me/...">` con `target="_blank" rel="noopener"`.
  Si está vacía, sigue como texto plano (default conservador).
- Acción manual (Blanca): setear `PUBLIC_WHATSAPP=569XXXXXXXX` en `.env`
  de producción para activar el link.
- ✅ Resuelto en commit pendiente — `edTech/settings.py`,
  `edTech/context_processors.py`, `edTech/templates/index.html`,
  `edTech/templates/info.html`.
  Tests: `edTech.tests.WhatsAppLinkTests` (3 tests).

### BUG-010 · CTA "Elegir y agregar" del modal Vista rápida es engañoso
- Ruta: /tienda/?cat=intima → Click en "Vista rápida" → modal
- "Elegir y agregar →" es un <a href="/tienda/p/14/">: no permite elegir
  talla ni agregar nada desde el modal, solo redirige.
- Opciones:
  a) Renombrar a "Ver producto" (cambio rápido).
  b) Implementar selección de talla + add-to-cart real en el modal.
- Fix elegido: (a) variante refinada. Label cambia a **"Elegir talla y
  agregar →"** que mantiene el call-to-action pero aclara que la elección
  y el agregar pasan en la ficha completa. También elimina el botón
  outline secundario "Ver detalle completo" cuando hay variantes (era
  redundante: ambos botones llevaban al mismo PDP). Para productos sin
  variantes el modal mantiene el form HTMX real "Agregar al carrito"
  como CTA primario y "Ver detalle" como outline.
- ✅ Resuelto en commit pendiente —
  `ecommerce/templates/ecommerce/_quick_view.html`.
  Test actualizado: `ecommerce/tests/test_quick_view.py
  · test_producto_con_variantes_redirige_a_pdp_para_elegir`.

### BUG-011 · /cuenta/dashboard/ redirige al backoffice
- Footer "Mi cuenta" → /cuenta/dashboard/ → redirige a /reportes/ cuando el
  user es staff. Verificar el flujo para usuarios no-staff y decidir si
  "Mi cuenta" debe llevar a /tienda/cuenta/pedidos/.
- Causa raíz: `accounts.views.dashboard` rotea según rol (admin/cajero/
  bodeguero), pero el caso default — cliente normal sin rol staff —
  intentaba renderizar `accounts/sin_rol.html` con HTTP 403. Y ese
  template ni siquiera existía en el repo, asi que un cliente que
  hubiera entrado a /cuenta/dashboard/ se hubiera comido un
  TemplateDoesNotExist (500).
- Fix: el caso default ahora redirige a `ecommerce:mis_pedidos`
  (`/tienda/cuenta/pedidos/`), que es la "Mi cuenta" natural para el
  cliente. Roles staff siguen igual.
- ✅ Resuelto en commit pendiente — `accounts/views.py`.
  Test nuevo: `accounts/tests_dashboard.py · DashboardRoutingTests`
  (6 tests, uno por cada rol + anonimo + cliente sin rol).

### BUG-012 · Número de pedido no accesible
- /tienda/cuenta/pedidos/: los "#8" / "#9" se muestran visualmente pero no
  están en el accessibility tree.
- Acción: incluirlos dentro del <a> con texto o aria-label.
- Fix: doble cobertura para AT:
  1. El wrapper (`<a>` cuando hay `payment_reference`, `<span role="group">`
     cuando no) ahora lleva un `aria-label` con el contexto completo del
     pedido: "Pedido número N, DD-MM-YYYY, X productos, $T CLP, estado X".
  2. Visualmente, el "#N" ahora tiene un prefijo
     `<span class="visually-hidden">Pedido número </span>` para que las
     AT que prefieren el texto contenido (en vez del aria-label) también
     lean el contexto.
  3. El ícono SVG de "Pagado" ahora tiene `aria-hidden="true"` para no
     leer "imagen pagado pagado" duplicado.
- ✅ Resuelto en commit pendiente —
  `ecommerce/templates/ecommerce/cuenta/mis_pedidos.html`.
  Test de regresión: `ecommerce/tests/test_cuenta.py
  · MisPedidosListadoTests.test_numero_pedido_accesible_a_screen_readers`.

## P3 — Visual / Admin

### BUG-013 · Saldo de caja negativo en verde
- /reportes/ Dashboard: SALDO DE CAJA $-909.628 en verde.
- /reportes/caja/ mismo valor en azul.
- Esperado: negativo siempre en rojo (o al menos consistente entre páginas).
- Fix: ambas tarjetas ahora tienen clase condicional. Saldo < 0 → `is-danger`
  (rojo). Saldo ≥ 0 → `is-success` (Dashboard, verde) o `is-primary`
  (Caja, azul) — mantienen su tonalidad cuando no son negativos.
  Mismo patrón que ya usaba `eerr.html` para `utilidad_neta`.
- ✅ Resuelto en commit pendiente — `reportes/templates/reportes/dashboard.html`,
  `reportes/templates/reportes/caja.html`.

### BUG-014 · Orden de tallas inconsistente
- Modal Vista rápida de Calzón básico algodón: L M S XL.
- Ficha completa Polera básica unisex: S M L XL.
- Acción: ordenar siempre por talla canónica (XS, S, M, L, XL, XXL y numéricas
  ascendentes).
- Causa raíz: `ecommerce.views.quick_view` ordenaba por `sku` (alfabético:
  L < M < S < XL → mostraba L, M, S, XL). El PDP completo (`producto_view`)
  ordenaba correctamente por `orden_talla / orden_volumen / orden_concentracion`
  derivados de `ValorAtributo.orden` (canónico).
- Fix: replicar el mismo `annotate(orden_talla=...).order_by(...)` del PDP
  en el quick_view. Ahora ambos muestran el mismo orden canónico.
- ✅ Resuelto en commit pendiente — `ecommerce/views.py`.
  Test de regresión: `ecommerce/tests/test_quick_view.py
  · test_variantes_ordenadas_por_talla_canonica`.

### BUG-015 · Tarjeta "Margen Potencial" se sale del contenedor
- /reportes/produccion/ a 1500px de ancho: la cuarta KPI queda recortada.
- Acción: revisar grid-template-columns / overflow del bloque KPIs.
- Causa raíz: `.bo-grid.cols-4 { grid-template-columns: repeat(4, 1fr); }`
  respeta el `min-content` intrínseco de cada columna por default. Si el
  valor de la KPI es largo (ej. $155.234.567 con `font-size: 26px`), su
  min-content crece y empuja la columna fuera del contenedor.
- Fix: cambiar `1fr` por `minmax(0, 1fr)` en los 3 layouts (cols-2, cols-3,
  cols-4) — permite shrinkear por debajo del min-content. También
  agregué `overflow-wrap: anywhere` al `.bo-kpi .value` por si el monto
  necesita partirse en pantallas estrechas.
- ✅ Resuelto en commit pendiente — `edTech/static/css/backoffice.css`.
  Aplica al Dashboard, EERR, Caja, Balance y Producción (todas usan el
  mismo helper de grid).

### BUG-016 · Plurales del Admin Django mal castellanizados
- /admin/: Proveedors, Materials, Movimiento materials, Movimiento stocks,
  Stock materials, Stock tiendas.
- Acción: setear verbose_name y verbose_name_plural en cada Meta de los models.
- Fix: agregado `verbose_name` + `verbose_name_plural` en 6 modelos de
  bodega + 2 obvios de catalogo (que tenían el mismo defecto):
  - `Proveedor` → "proveedor" / "proveedores"
  - `Material` → "material" / "materiales"
  - `StockTienda` → "stock por tienda" / "stocks por tienda"
  - `StockMaterial` → "stock de material" / "stocks de material"
  - `MovimientoMaterial` → "movimiento de material" / "movimientos de material"
  - `MovimientoStock` → "movimiento de stock" / "movimientos de stock"
  - `ValorAtributo` → "valor de atributo" / "valores de atributo"
  - `ProductoVariante` → "variante de producto" / "variantes de producto"
- Migraciones:
  - `bodega/migrations/0006_verbose_names_plurales.py`
  - `catalogo/migrations/0009_verbose_names_plurales.py`
  Solo modifican Meta options (no tocan schema); idempotentes.
- ✅ Resuelto en commit pendiente.

## Notas para mantenimiento
- No hay tests automatizados conocidos; verificación es manual en el navegador.
- El admin login es `admin` (ya estoy logueado en cookies; si trabajas en otro
  entorno, pediremos credenciales aparte — no las pegues en el repo).
- Antes de cerrar un bug, deja un comentario en este archivo con "✅ Resuelto
  en commit <hash>" debajo del bug correspondiente.