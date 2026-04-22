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
    qs = (
        ReciboVenta.objects
        .select_related('tienda', 'vendedor')
        .order_by('-creado')
    )
    if not request.user.is_superuser and not request.user.groups.filter(name='admin').exists():
        qs = qs.filter(vendedor=request.user)
    return render(request, 'pos/ventas.html', {'ventas': qs[:200]})


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
