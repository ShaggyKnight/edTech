"""Vistas del POS presencial.

Flujo:
  /pos/              -> home (lista productos + carrito)
  POST /pos/agregar/ -> añade variante o producto al carrito
  POST /pos/actualizar/ -> cambia cantidad
  POST /pos/quitar/  -> elimina línea
  POST /pos/vaciar/  -> vacía carrito
  POST /pos/checkout/ -> procesa venta (cobro + stock) y redirige al recibo
  /pos/recibo/<pk>/  -> detalle de un recibo
  /pos/ventas/       -> listado de ventas del cajero
  POST /pos/tienda/seleccionar/ -> setea la sucursal activa en sesión
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import OuterRef, Q, Subquery
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Familia, Producto, ProductoVariante
from pos.cart import Cart
from pos.forms import (
    ActualizarCantidadForm,
    AgregarForm,
    CheckoutForm,
    SeleccionarTiendaForm,
)
from pos.models import ReciboVenta
from pos.services import (
    SESSION_TIENDA_KEY,
    CobroFallido,
    ItemVenta,
    StockInsuficiente,
    get_active_tienda,
    procesar_venta,
)

CANAL = ReciboVenta.CANAL_PRESENCIAL


def _stock_subquery(tienda, campo):
    """Subquery para annotate: stock en la tienda activa para el producto/variante."""
    filtros = {'tienda': tienda, campo: OuterRef('pk')}
    return Subquery(
        StockTienda.objects
        .filter(**filtros)
        .values('cantidad')[:1]
    )


def _puede_admin_stock(user) -> bool:
    """¿Este user puede agregar stock desde el POS?

    Solo superusers o miembros del grupo `admin`. Cajeros y bodegueros
    NO pueden — el cajero opera ventas, el bodeguero usa el admin Django.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='admin').exists()


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
def home(request):
    tienda = get_active_tienda(request)
    if tienda is None:
        return render(request, 'pos/sin_tienda.html', {
            'tiendas': Tienda.objects.filter(activa=True),
        }, status=200)

    query = request.GET.get('q', '').strip()
    familia_id = (request.GET.get('familia') or '').strip()
    # Default: solo con stock. `?stock=todos` para ver agotados también.
    mostrar_todos = request.GET.get('stock') == 'todos'

    productos_qs = (
        Producto.objects
        .filter(activo=True, tiene_variantes=False)
        .select_related('familia')
        .annotate(stock=_stock_subquery(tienda, 'producto'))
    )
    variantes_qs = (
        ProductoVariante.objects
        .filter(activa=True, producto__activo=True, producto__tiene_variantes=True)
        .select_related('producto__familia')
        .prefetch_related('valores__atributo')
        .annotate(stock=_stock_subquery(tienda, 'variante'))
    )
    if query:
        # Busqueda multi-token: el cajero tipea "buzo 10" o "chaqueta 14"
        # y queremos matchear las variantes que tienen TODOS los tokens
        # en cualquiera de sus campos (nombre, sku, valor de atributo).
        # Asi "buzo 10" devuelve solo el Buzo SFJ talla 10, no todos los
        # buzos ni todas las prendas talla 10.
        #
        # Sinonimos de colegios (Los Vilos): `pos.search` expande
        # apodos locales como "liceo" -> "lohse", "fraga" -> "javier",
        # "parro/parroquial" -> "providencia", "publica" -> "almagro".
        # Asi el cajero busca como en la calle y matchea los colegios
        # con su nombre formal.
        from pos.search import (
            es_token_corto,
            normalizar_y_expandir,
            q_valor_exacto,
        )
        tokens_expandidos = normalizar_y_expandir(query)

        # Los productos SIN variantes no tienen tallas / volúmenes /
        # concentraciones. Si TODOS los tokens del query son "cortos"
        # (talla-letra, talla numérica, concentración o volumen sin
        # unidad), no tiene sentido buscar entre productos sin variantes
        # — los excluimos al final.
        hay_loose_token = any(
            not es_token_corto(t)
            for grupo in tokens_expandidos
            for t in grupo
        )

        for variantes_token in tokens_expandidos:
            # Cada token (con sus expansiones) reduce el queryset.
            # Adentro del token, OR entre las variantes (ej. "liceo"
            # OR "lohse"). Entre tokens, AND (cada filter encadenado).
            q_producto = Q()
            q_variante = Q()
            for term in variantes_token:
                if es_token_corto(term):
                    # Token "corto" (S/M/XL/EDT/EDP, o numérico de
                    # 1-4 dígitos): SOLO match exacto contra el valor.
                    # Esto distingue:
                    #   "s" matchea ValorAtributo "S" (no "gris")
                    #   "30" matchea "30" y "30 ml" (no "130 ml" ni "300 ml")
                    #   "edt" matchea "EDT" (no productos con "edt..." en el nombre)
                    q_variante |= q_valor_exacto(term)
                    # No contribuye a productos sin variantes.
                else:
                    # Token genérico (palabra larga): substring match
                    # en nombre / descripcion / colegio / sku / valor.
                    q_producto |= (
                        Q(nombre_buscable__contains=term)
                        | Q(descripcion_buscable__contains=term)
                        | Q(colegio__nombre_buscable__contains=term)
                    )
                    q_variante |= (
                        Q(producto__nombre_buscable__contains=term)
                        | Q(producto__colegio__nombre_buscable__contains=term)
                        | Q(sku__icontains=term)
                        | Q(valores__valor__icontains=term)
                    )
            # Si todos los términos del grupo eran cortos, q_producto
            # queda vacío; `filter(Q())` es no-op — está OK porque el
            # guard `hay_loose_token` excluye productos abajo.
            if q_producto.children:
                productos_qs = productos_qs.filter(q_producto)
            variantes_qs = variantes_qs.filter(q_variante)

        if not hay_loose_token:
            productos_qs = productos_qs.none()

        # distinct al final porque los JOINs multiples pueden duplicar.
        variantes_qs = variantes_qs.distinct()
        productos_qs = productos_qs.distinct()
    if familia_id.isdigit():
        f = int(familia_id)
        productos_qs = productos_qs.filter(familia_id=f)
        variantes_qs = variantes_qs.filter(producto__familia_id=f)
    if not mostrar_todos:
        # Default ON: filtra agotados (stock NULL o 0).
        productos_qs = productos_qs.filter(stock__gt=0)
        variantes_qs = variantes_qs.filter(stock__gt=0)

    cart = Cart(request.session)
    lineas = list(cart.lineas(canal=CANAL))
    subtotal_bruto, descuento_total, total_neto = cart.totales(canal=CANAL)

    contexto = {
        'tienda': tienda,
        'tiendas_disponibles': Tienda.objects.filter(activa=True).exclude(pk=tienda.pk),
        'query': query,
        'familias': Familia.objects.order_by('nombre'),
        'familia_activa': int(familia_id) if familia_id.isdigit() else None,
        'mostrar_todos': mostrar_todos,
        'productos': productos_qs.order_by('nombre'),
        'variantes': variantes_qs.order_by('producto__nombre', 'sku'),
        'lineas': lineas,
        'subtotal_bruto': subtotal_bruto,
        'descuento_total': descuento_total,
        'total_neto': total_neto,
        'items_count': cart.items_count,
        'puede_agregar_stock': _puede_admin_stock(request.user),
    }

    # Live search: si la request viene de HTMX, devolvemos solo el tbody.
    # Es lo unico que el cliente necesita reemplazar — ahorra render del
    # resto de la pagina y reduce el payload.
    if request.htmx:
        return render(request, 'pos/_pos_productos_tbody.html', contexto)
    return render(request, 'pos/home.html', contexto)


@login_required
@require_POST
def agregar_stock(request):
    """Suma stock a un producto/variante en la tienda activa.

    Endpoint operativo para admins: cuando llega mercadería al POS, en
    vez de ir al Django admin, se carga directo desde la tabla.
    Cajero y bodeguero no tienen acceso (los gates están acá adentro).
    """
    if not _puede_admin_stock(request.user):
        messages.error(request, 'No tenés permisos para cargar stock desde el POS.')
        return redirect('pos:home')

    tienda = get_active_tienda(request)
    if tienda is None:
        messages.error(request, 'Seleccioná una tienda primero.')
        return redirect('pos:home')

    tipo = request.POST.get('tipo', '')
    try:
        item_id = int(request.POST.get('item_id', 0))
        cantidad = int(request.POST.get('cantidad', 0))
    except (TypeError, ValueError):
        messages.error(request, 'Datos inválidos.')
        return redirect('pos:home')

    if cantidad <= 0:
        messages.error(request, 'La cantidad a sumar debe ser mayor a 0.')
        return redirect('pos:home')

    from django.db import transaction
    from django.db.models import F

    with transaction.atomic():
        if tipo == 'v':
            if not ProductoVariante.objects.filter(pk=item_id, activa=True).exists():
                messages.error(request, 'Variante no disponible.')
                return redirect('pos:home')
            fila, _ = StockTienda.objects.select_for_update().get_or_create(
                tienda=tienda, variante_id=item_id, defaults={'cantidad': 0},
            )
        elif tipo == 'p':
            if not Producto.objects.filter(
                pk=item_id, activo=True, tiene_variantes=False,
            ).exists():
                messages.error(request, 'Producto no disponible.')
                return redirect('pos:home')
            fila, _ = StockTienda.objects.select_for_update().get_or_create(
                tienda=tienda, producto_id=item_id, defaults={'cantidad': 0},
            )
        else:
            messages.error(request, 'Tipo inválido.')
            return redirect('pos:home')

        StockTienda.objects.filter(pk=fila.pk).update(
            cantidad=F('cantidad') + cantidad,
        )
        mov_kwargs = {
            'tienda': tienda, 'tipo': MovimientoStock.ENTRADA,
            'cantidad': cantidad, 'usuario': request.user,
            'referencia': f'Carga rápida POS por {request.user.username}',
        }
        if tipo == 'v':
            mov_kwargs['variante_id'] = item_id
        else:
            mov_kwargs['producto_id'] = item_id
        MovimientoStock.objects.create(**mov_kwargs)

    messages.success(request, f'+{cantidad} unidades agregadas al stock.')
    # Preserva los filtros/query del referer si los hay.
    qs = request.META.get('HTTP_REFERER', '')
    if qs and 'pos' in qs:
        return redirect(qs)
    return redirect('pos:home')


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def escanear(request):
    """Recibe un codigo de barras y agrega 1 unidad al carrito del POS.

    El input es el clasico escaner USB que actua como teclado (los
    digitos + Enter llegan como un POST normal con el codigo en el
    body), o un input manual del cajero si no encuentra el item.

    Optimizacion: si el codigo fue generado por nosotros
    (parsear_codigo_interno != None) sabemos directo la tabla y pk
    sin escanear toda la columna. Caemos a busqueda por codigo_barras
    plano para EAN-13 de fabrica (perfumes con codigo comercial).
    """
    from catalogo.barcode import parsear_codigo_interno

    codigo = (request.POST.get('codigo') or '').strip()
    if not codigo:
        messages.error(request, 'Falta el código.')
        return _respuesta_scan(request)

    tienda = get_active_tienda(request)
    if tienda is None:
        messages.error(request, 'Seleccioná una tienda antes de escanear.')
        return _respuesta_scan(request)

    cart = Cart(request.session)

    # Optimizacion: si es codigo interno (prefijo 200), salteamos los
    # SELECT por columna.
    parsed = parsear_codigo_interno(codigo)
    if parsed:
        tipo_p, pk = parsed
        if tipo_p == 'p':
            p = Producto.objects.filter(
                pk=pk, activo=True, tiene_variantes=False, codigo_barras=codigo,
            ).first()
            if p:
                cart.add_producto(p.pk, 1)
                messages.success(request, f'+ {p.nombre}')
                return _respuesta_scan(request)
        else:
            v = ProductoVariante.objects.filter(
                pk=pk, activa=True, producto__activo=True, codigo_barras=codigo,
            ).select_related('producto').first()
            if v:
                cart.add_variante(v.pk, 1)
                messages.success(request, f'+ {v.producto.nombre} [{v.sku}]')
                return _respuesta_scan(request)

    # Fallback: busqueda por la columna codigo_barras (codigos externos).
    v = (
        ProductoVariante.objects
        .filter(codigo_barras=codigo, activa=True, producto__activo=True)
        .select_related('producto')
        .first()
    )
    if v:
        cart.add_variante(v.pk, 1)
        messages.success(request, f'+ {v.producto.nombre} [{v.sku}]')
        return _respuesta_scan(request)

    p = Producto.objects.filter(
        codigo_barras=codigo, activo=True, tiene_variantes=False,
    ).first()
    if p:
        cart.add_producto(p.pk, 1)
        messages.success(request, f'+ {p.nombre}')
        return _respuesta_scan(request)

    messages.error(request, f'Código no encontrado: {codigo}')
    return _respuesta_scan(request)


def _respuesta_scan(request):
    """Devuelve la respuesta apropiada despues de un scan.

    - Si vino de HTMX, header HX-Refresh para que el browser recargue
      la pagina entera (asi el carrito y los toasts aparecen).
    - Si vino de un POST tradicional, redirect a home.
    """
    from django.http import HttpResponse
    if request.htmx:
        resp = HttpResponse('')
        resp['HX-Refresh'] = 'true'
        return resp
    return redirect('pos:home')


def _respuesta_carrito_pos(request):
    """Helper: si la request es HTMX, devuelve el partial OOB del
    carrito + toasts. Si no, redirect tradicional a home (fallback
    no-JS).

    Asi `agregar` / `actualizar` / `quitar` / `vaciar` actualizan la
    UI sin recargar la pagina: el cajero sigue viendo el listado de
    productos, no pierde scroll ni foco, y el carrito refleja el
    estado nuevo + toast con el feedback del servidor.
    """
    if not request.htmx:
        return redirect('pos:home')

    cart = Cart(request.session)
    lineas = list(cart.lineas(canal=CANAL))
    subtotal_bruto, descuento_total, total_neto = cart.totales(canal=CANAL)
    return render(request, 'pos/_pos_oob_update.html', {
        'lineas': lineas,
        'subtotal_bruto': subtotal_bruto,
        'descuento_total': descuento_total,
        'total_neto': total_neto,
        'items_count': cart.items_count,
    })


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def agregar(request):
    form = AgregarForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Datos inválidos para agregar al carrito.')
        return _respuesta_carrito_pos(request)

    cart = Cart(request.session)
    tipo = form.cleaned_data['tipo']
    item_id = form.cleaned_data['item_id']
    cantidad = form.cleaned_data['cantidad']

    if tipo == 'v':
        variante = ProductoVariante.objects.select_related('producto').filter(
            pk=item_id, activa=True,
        ).first()
        if not variante:
            messages.error(request, 'Variante no disponible.')
            return _respuesta_carrito_pos(request)
        cart.add_variante(item_id, cantidad)
        messages.success(
            request, f'+ {variante.producto.nombre} ({variante.sku}) al carrito.',
        )
    else:
        producto = Producto.objects.filter(
            pk=item_id, activo=True, tiene_variantes=False,
        ).first()
        if not producto:
            messages.error(request, 'Producto no disponible.')
            return _respuesta_carrito_pos(request)
        cart.add_producto(item_id, cantidad)
        messages.success(request, f'+ {producto.nombre} al carrito.')

    return _respuesta_carrito_pos(request)


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def actualizar(request):
    form = ActualizarCantidadForm(request.POST)
    if form.is_valid():
        Cart(request.session).set_cantidad(form.cleaned_data['key'], form.cleaned_data['cantidad'])
    return _respuesta_carrito_pos(request)


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def quitar(request, key: str):
    Cart(request.session).remove(key)
    return _respuesta_carrito_pos(request)


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def vaciar(request):
    Cart(request.session).clear()
    messages.success(request, 'Carrito vacío.')
    return _respuesta_carrito_pos(request)


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def checkout(request):
    tienda = get_active_tienda(request)
    if tienda is None:
        messages.error(request, 'Selecciona una tienda antes de cobrar.')
        return redirect('pos:home')

    cart = Cart(request.session)
    if cart.is_empty():
        messages.error(request, 'El carrito está vacío.')
        return redirect('pos:home')

    form = CheckoutForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Datos del cliente inválidos.')
        return redirect('pos:home')

    items = [
        ItemVenta(
            tipo=linea['tipo'],
            item_id=linea['item'].pk,
            cantidad=linea['cantidad'],
            precio_unitario=linea['precio_unitario'],
            descuento_total=linea['descuento_total'],
        )
        for linea in cart.lineas(canal=CANAL)
    ]
    if not items:
        messages.error(request, 'El carrito quedó vacío al validar.')
        return redirect('pos:home')

    try:
        recibo = procesar_venta(
            tienda=tienda,
            vendedor=request.user,
            items=items,
            cliente_nombre=form.cleaned_data.get('cliente_nombre', ''),
            cliente_email=form.cleaned_data.get('cliente_email', ''),
            cliente_rut=form.cleaned_data.get('cliente_rut', ''),
            dte_tipo=form.cleaned_data.get('dte_tipo') or None,
        )
    except StockInsuficiente as exc:
        messages.error(
            request,
            f'Stock insuficiente para {exc.item}: quedan {exc.disponible}, se pidieron {exc.solicitado}.',
        )
        return redirect('pos:home')
    except CobroFallido as exc:
        messages.error(request, f'Cobro rechazado: {exc}')
        return redirect('pos:home')

    cart.clear()
    messages.success(request, f'Venta #{recibo.pk} procesada por ${recibo.total}.')
    return redirect('pos:recibo', pk=recibo.pk)


@login_required
@permission_required('pos.view_reciboventa', raise_exception=True)
def ver_recibo(request, pk: int):
    recibo = get_object_or_404(
        ReciboVenta.objects.select_related('tienda', 'vendedor').prefetch_related(
            'detalles__variante__producto',
            'detalles__producto',
        ),
        pk=pk,
    )
    return render(request, 'pos/recibo.html', {'recibo': recibo})


@login_required
@permission_required('pos.view_reciboventa', raise_exception=True)
def ventas(request):
    """Listado de ventas con filtros por tienda, canal, estado y fechas.

    Cajero ve sólo sus ventas; admin/superuser ven todo. KPIs y serie
    diaria se calculan sobre el queryset YA filtrado para que reflejen
    lo que ven en la tabla.
    """
    from datetime import timedelta
    from decimal import Decimal as D
    from django.db.models import Count, Sum, Value, DecimalField
    from django.db.models.functions import Coalesce, TruncDate
    from django.utils import timezone

    qs = (
        ReciboVenta.objects
        .select_related('tienda', 'vendedor')
        .order_by('-creado')
    )
    es_admin = request.user.is_superuser or request.user.groups.filter(name='admin').exists()
    if not es_admin:
        qs = qs.filter(vendedor=request.user)

    # Filtros desde querystring.
    tienda_id = (request.GET.get('tienda') or '').strip()
    canal = (request.GET.get('canal') or '').strip()
    estado = (request.GET.get('estado') or '').strip()
    desde_str = (request.GET.get('desde') or '').strip()
    hasta_str = (request.GET.get('hasta') or '').strip()

    if tienda_id.isdigit():
        qs = qs.filter(tienda_id=int(tienda_id))
    if canal in {ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.CANAL_ONLINE}:
        qs = qs.filter(canal=canal)
    if estado in {'pagado', 'pendiente', 'fallido', 'cancelado'}:
        qs = qs.filter(estado=estado)
    if desde_str:
        try:
            desde_dt = timezone.make_aware(
                timezone.datetime.strptime(desde_str, '%Y-%m-%d')
            )
            qs = qs.filter(creado__gte=desde_dt)
        except (ValueError, TypeError):
            pass
    if hasta_str:
        try:
            hasta_dt = timezone.make_aware(
                timezone.datetime.strptime(hasta_str, '%Y-%m-%d')
                + timedelta(days=1)  # incluye todo el día seleccionado
            )
            qs = qs.filter(creado__lt=hasta_dt)
        except (ValueError, TypeError):
            pass

    # KPIs sobre el queryset filtrado, contando solo ventas pagadas para totales
    # pero todas para el conteo (así el dueño ve cuántos recibos había en total).
    pagados = qs.filter(estado=ReciboVenta.ESTADO_PAGADO)
    n_pagados = pagados.count()
    n_total = qs.count()
    n_fallidos = qs.filter(estado__in=[
        ReciboVenta.ESTADO_FALLIDO, ReciboVenta.ESTADO_CANCELADO,
    ]).count()
    n_pendientes = qs.filter(estado=ReciboVenta.ESTADO_PENDIENTE).count()
    kpi = {
        'total': pagados.aggregate(
            t=Coalesce(Sum('total'), Value(D('0')), output_field=DecimalField())
        )['t'],
        'n_pagados': n_pagados,
        'n_total': n_total,
        'n_fallidos': n_fallidos,
        'n_pendientes': n_pendientes,
    }
    kpi['ticket'] = (kpi['total'] / n_pagados) if n_pagados else D('0')

    # Serie diaria para chart (solo pagados).
    serie = list(
        pagados.annotate(dia=TruncDate('creado'))
        .values('dia')
        .annotate(
            n=Count('id'),
            total=Coalesce(Sum('total'), Value(D('0')), output_field=DecimalField()),
        )
        .order_by('dia')
    )

    return render(request, 'pos/ventas.html', {
        'ventas': qs[:200],
        'kpi': kpi,
        'serie': [{'fecha': r['dia'].isoformat() if r['dia'] else '',
                   'n': r['n'],
                   'total': float(r['total'])} for r in serie],
        'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
        'filtros': {
            'tienda': tienda_id,
            'canal': canal,
            'estado': estado,
            'desde': desde_str,
            'hasta': hasta_str,
        },
        'es_admin': es_admin,
    })


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def seleccionar_tienda(request):
    form = SeleccionarTiendaForm(request.POST)
    if form.is_valid():
        tienda_id = form.cleaned_data['tienda_id']
        if Tienda.objects.filter(pk=tienda_id, activa=True).exists():
            request.session[SESSION_TIENDA_KEY] = tienda_id
            request.session.modified = True
        else:
            messages.error(request, 'Tienda inválida.')
    return redirect('pos:home')


# ============================================================================
# PWA: manifest + service worker
# ============================================================================

# Subir esta version cada vez que se cambia el shell del POS para forzar
# que los clientes refresquen el cache. El SW lo lee y compara contra el
# de su cache para decidir si invalida.
PWA_CACHE_VERSION = 'v1-2026.05'


def pwa_manifest(request):
    """Web App Manifest del POS.

    Servido por Django (no como static) para poder inyectar URLs de
    Django dinamicamente y mantener una sola fuente de verdad.
    """
    from django.http import JsonResponse
    from django.urls import reverse
    from django.templatetags.static import static
    manifest = {
        'name': 'Ideas Boutique POS',
        'short_name': 'Ideas POS',
        'description': 'Punto de venta de Ideas Boutique — Los Vilos',
        'start_url': reverse('pos:home'),
        'scope': '/pos/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#1B1F2A',
        'theme_color': '#1B1F2A',
        'lang': 'es-CL',
        'icons': [
            {
                'src': static('img/pwa/icon.svg'),
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'any maskable',
            },
        ],
    }
    resp = JsonResponse(manifest)
    resp['Content-Type'] = 'application/manifest+json'
    return resp


def pwa_service_worker(request):
    """Service Worker del POS.

    Estrategia:
      - Precache de la shell minima al instalar.
      - Network-first para HTML (paginas frescas si hay red, cacheadas
        si no).
      - Cache-first para assets staticos versionados.
      - Skip-cache para POSTs y endpoints AJAX (carrito, checkout,
        agregar, etc) — esos siempre tienen que pegar al server.
    """
    from django.http import HttpResponse
    from django.urls import reverse
    from django.templatetags.static import static

    paths_a_precache = [
        reverse('pos:home'),
        static('css/backoffice.css'),
        static('lib/htmx/htmx.min.js'),
        static('lib/alpine/alpine.min.js'),
        static('img/pwa/icon.svg'),
    ]

    sw_js = (
        f"const CACHE_VERSION = {PWA_CACHE_VERSION!r};\n"
        f"const CACHE_NAME = 'ideas-pos-' + CACHE_VERSION;\n"
        f"const PRECACHE_PATHS = {paths_a_precache!r};\n"
        """
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_PATHS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith('ideas-pos-') && k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Solo GET — los POST (agregar al carrito, checkout) deben pegar al server.
  if (req.method !== 'GET') return;
  // Skip endpoints transaccionales: agregar/actualizar/quitar/vaciar/checkout.
  const url = new URL(req.url);
  if (url.pathname.startsWith('/pos/checkout') ||
      url.pathname === '/pos/agregar/' ||
      url.pathname === '/pos/actualizar/' ||
      url.pathname.startsWith('/pos/quitar/') ||
      url.pathname === '/pos/vaciar/') {
    return;
  }
  // Network-first para HTML (asi el cajero ve siempre lo ultimo si hay red).
  const isHtml = req.headers.get('accept')?.includes('text/html');
  if (isHtml) {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
          return resp;
        })
        .catch(() => caches.match(req).then((c) => c || caches.match('/pos/')))
    );
    return;
  }
  // Cache-first para CSS/JS/imagenes.
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req).then((resp) => {
      if (resp.ok) {
        const copy = resp.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy));
      }
      return resp;
    }))
  );
});
"""
    )
    resp = HttpResponse(sw_js, content_type='application/javascript')
    # El SW debe servirse con scope que cubre toda la app POS.
    resp['Service-Worker-Allowed'] = '/pos/'
    # No cachear el SW en si — la version va embebida y el browser
    # debe verificar nuevas versiones de SW.
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp
