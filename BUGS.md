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
- Sospecha: el handler de selección no actualiza data-state del submit cuando
  el formato pasa de seleccionado → otro seleccionado. Falta toggling correcto.

## P1 — Datos / cálculos

### BUG-003 · "DESDE $X" del listado no respeta la oferta vigente
- Ruta: /tienda/ (listado) → Oud Royal Elixir
- Listado dice: "DESDE $38.491".
- Real (oferta -10% sobre Oud, ver /bodega/ofertas/):
  - 30 ml $44.990 → $40.491
  - 100 ml $64.990 → $58.491
- Esperado: "DESDE $40.491".
- Sospecha: el "desde" se calcula con otro % o sobre otra variante; revisar
  el queryset/annotate del catálogo y el cálculo de min(price_after_discount).

### BUG-004 · Cuota mostrada antes de elegir variante usa el precio sin descuento
- Ruta: /tienda/p/11/ (estado inicial, sin formato elegido)
- Muestra: "$38.491 (con $44.990 tachado) · 3 cuotas sin interés de $14997"
- 14997 = 44990 / 3. Debería ser 38491 / 3 = 12.830 (o, si "desde" se corrige
  a 40.491, sería 13.497).
- Acción: que la cuota se calcule sobre el mismo precio que muestra "desde".

### BUG-005 · Formato monetario inconsistente
- Casos detectados:
  - /tienda/p/11/ estado inicial: "$14997" sin separador.
  - /reportes/ (Dashboard): "Promedio por venta $34437" sin separador
    (mismo dato en /pos/ventas/ aparece "$34.437" bien formateado).
  - /tienda/pedido/<uuid>/: precios como "$64990.00", "$58491.00",
    "-$6499.00" con dos decimales y sin punto de miles.
- Esperado: formato CLP `$XX.XXX` sin decimales en todo el sitio.
- Acción: centralizar en un template filter (ej. `|clp`) y reemplazar.

### BUG-006 · Discrepancia de métricas Dashboard vs EERR
- Dashboard "últimos 30 días": Ventas totales $344.372
- EERR "Mayo 2026": Ingresos $314.392
- No es bug de cálculo (ventanas distintas) pero el copy debería aclararlo.

### BUG-007 · Margen bruto con doble unidad
- /reportes/eerr/ → "Margen bruto $126.892 · 0.40% — 40% del ingreso"
- Mostrar solo "40,4 % del ingreso" (o el ratio, no ambos).

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

### BUG-009 · "WhatsApp directo" no es enlace
- Home, sección Visítanos: el texto "WhatsApp directo / Pedidos y reservas"
  es un <span>/<div>, no un <a href="https://wa.me/56XXXXXXXXX">.
- Acción: convertir en link real con el número de la tienda.

### BUG-010 · CTA "Elegir y agregar" del modal Vista rápida es engañoso
- Ruta: /tienda/?cat=intima → Click en "Vista rápida" → modal
- "Elegir y agregar →" es un <a href="/tienda/p/14/">: no permite elegir
  talla ni agregar nada desde el modal, solo redirige.
- Opciones:
  a) Renombrar a "Ver producto" (cambio rápido).
  b) Implementar selección de talla + add-to-cart real en el modal.

### BUG-011 · /cuenta/dashboard/ redirige al backoffice
- Footer "Mi cuenta" → /cuenta/dashboard/ → redirige a /reportes/ cuando el
  user es staff. Verificar el flujo para usuarios no-staff y decidir si
  "Mi cuenta" debe llevar a /tienda/cuenta/pedidos/.

### BUG-012 · Número de pedido no accesible
- /tienda/cuenta/pedidos/: los "#8" / "#9" se muestran visualmente pero no
  están en el accessibility tree.
- Acción: incluirlos dentro del <a> con texto o aria-label.

## P3 — Visual / Admin

### BUG-013 · Saldo de caja negativo en verde
- /reportes/ Dashboard: SALDO DE CAJA $-909.628 en verde.
- /reportes/caja/ mismo valor en azul.
- Esperado: negativo siempre en rojo (o al menos consistente entre páginas).

### BUG-014 · Orden de tallas inconsistente
- Modal Vista rápida de Calzón básico algodón: L M S XL.
- Ficha completa Polera básica unisex: S M L XL.
- Acción: ordenar siempre por talla canónica (XS, S, M, L, XL, XXL y numéricas
  ascendentes).

### BUG-015 · Tarjeta "Margen Potencial" se sale del contenedor
- /reportes/produccion/ a 1500px de ancho: la cuarta KPI queda recortada.
- Acción: revisar grid-template-columns / overflow del bloque KPIs.

### BUG-016 · Plurales del Admin Django mal castellanizados
- /admin/: Proveedors, Materials, Movimiento materials, Movimiento stocks,
  Stock materials, Stock tiendas.
- Acción: setear verbose_name y verbose_name_plural en cada Meta de los models.

## Notas para Claude Code
- No hay tests automatizados conocidos; verificación es manual en el navegador.
- El admin login es `admin` (ya estoy logueado en cookies; si trabajás en otro
  entorno, pediremos credenciales aparte — no las pegues en el repo).
- Antes de cerrar un bug, dejá un comentario en este archivo con "✅ Resuelto
  en commit <hash>" debajo del bug correspondiente.