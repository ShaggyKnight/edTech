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

from bodega.models import StockTienda, Tienda
from catalogo.models import Producto, ProductoVariante
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


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
def home(request):
    tienda = get_active_tienda(request)
    if tienda is None:
        return render(request, 'pos/sin_tienda.html', {
            'tiendas': Tienda.objects.filter(activa=True),
        }, status=200)

    query = request.GET.get('q', '').strip()

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
        productos_qs = productos_qs.filter(
            Q(nombre__icontains=query) | Q(descripcion__icontains=query)
        )
        variantes_qs = variantes_qs.filter(
            Q(producto__nombre__icontains=query)
            | Q(sku__icontains=query)
            | Q(valores__valor__icontains=query)
        ).distinct()

    cart = Cart(request.session)
    lineas = list(cart.lineas(canal=CANAL))
    subtotal_bruto, descuento_total, total_neto = cart.totales(canal=CANAL)

    return render(request, 'pos/home.html', {
        'tienda': tienda,
        'tiendas_disponibles': Tienda.objects.filter(activa=True).exclude(pk=tienda.pk),
        'query': query,
        'productos': productos_qs.order_by('nombre'),
        'variantes': variantes_qs.order_by('producto__nombre', 'sku'),
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
        return redirect('pos:home')

    cart = Cart(request.session)
    tipo = form.cleaned_data['tipo']
    item_id = form.cleaned_data['item_id']
    cantidad = form.cleaned_data['cantidad']

    if tipo == 'v':
        if not ProductoVariante.objects.filter(pk=item_id, activa=True).exists():
            messages.error(request, 'Variante no disponible.')
            return redirect('pos:home')
        cart.add_variante(item_id, cantidad)
    else:
        if not Producto.objects.filter(pk=item_id, activo=True, tiene_variantes=False).exists():
            messages.error(request, 'Producto no disponible.')
            return redirect('pos:home')
        cart.add_producto(item_id, cantidad)

    return redirect('pos:home')


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def actualizar(request):
    form = ActualizarCantidadForm(request.POST)
    if form.is_valid():
        Cart(request.session).set_cantidad(form.cleaned_data['key'], form.cleaned_data['cantidad'])
    return redirect('pos:home')


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def quitar(request, key: str):
    Cart(request.session).remove(key)
    return redirect('pos:home')


@login_required
@permission_required('pos.add_reciboventa', raise_exception=True)
@require_POST
def vaciar(request):
    Cart(request.session).clear()
    return redirect('pos:home')


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
