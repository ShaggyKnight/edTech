"""Vistas públicas de la tienda online.

Rutas:
    /tienda/                     catálogo
    /tienda/p/<id>/              detalle de producto
    /tienda/carrito/             ver carrito
    POST /tienda/agregar/
    POST /tienda/actualizar/
    POST /tienda/quitar/<key>/
    POST /tienda/vaciar/
    /tienda/checkout/            formulario de datos del cliente
    POST /tienda/checkout/iniciar/  crea pedido y redirige al gateway
    /tienda/checkout/retorno/    vuelta desde el gateway
    /tienda/pedido/<token>/      recibo online
    /tienda/mock-pago/           simulador de pasarela (solo si gateway=mock)
"""

from __future__ import annotations

import logging

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Exists, OuterRef, Q, Subquery
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from bodega.models import StockTienda
from catalogo.models import Colegio, Familia, Producto, ProductoVariante, ValorAtributo
from ecommerce.cart import CANAL, Cart
from ecommerce.emails import enviar_boleta
from ecommerce.forms import ActualizarCantidadForm, AgregarForm, CheckoutForm
from ecommerce.payments import get_online_gateway
from ecommerce.services import (
    ItemPedido,
    PedidoNoEncontrado,
    StockInsuficienteOnline,
    TiendaOnlineNoConfigurada,
    confirmar_pedido,
    get_tienda_online,
    iniciar_pedido,
)
from pos.models import ReciboVenta
from pos.payments import PaymentGatewayError

log = logging.getLogger(__name__)


# Slug → (título para el header, descripción, tintes de acento).
# Permite que la landing enlace a `/tienda/?cat=uniformes` sin conocer la pk
# de la familia correspondiente.
CAT_SLUGS = {
    'uniformes': {
        'title': 'Uniformes Escolares',
        'desc':  'Buzos, chalecos y remeras de tu colegio',
        'accent': '#7A1E2B',
        'match':  ['uniform'],
    },
    'perfumes': {
        'title': 'Perfumes',
        'desc':  'Fragancias originales y decants',
        'accent': '#C9A96E',
        # 'fragan' (no 'fragranc') matchea 'Fragancia(s)' en español.
        'match':  ['perfum', 'fragan'],
    },
    'moda': {
        'title': 'Moda',
        'desc':  'Ropa casual y formal',
        'accent': '#2B3140',
        'match':  ['moda', 'ropa'],
    },
    'intima': {
        'title': 'Ropa Íntima',
        'desc':  'Lencería y ropa interior',
        'accent': '#A03853',
        'match':  ['intim', 'lenc'],
    },
}


def _familias_por_slug(slug: str):
    """Devuelve el queryset de familias que corresponden al slug de categoría."""
    info = CAT_SLUGS.get(slug)
    if not info:
        return Familia.objects.none()
    q = Familia.objects.none()
    for term in info['match']:
        q = q | Familia.objects.filter(nombre__icontains=term)
    return q


def catalogo(request):
    """Listado público de productos con stock > 0 en la tienda online.

    Filtros vía querystring:
      cat=<slug> | familia=<pk> | colegio=<pk> | talla=<valor>
      precio_min, precio_max | q=<texto>  (accent + case insensitive)
    """
    from edTech.search import normalize_text

    try:
        tienda = get_tienda_online()
    except TiendaOnlineNoConfigurada:
        return render(request, 'ecommerce/sin_tienda.html', status=503)

    familia_id = (request.GET.get('familia') or '').strip()
    cat_slug = (request.GET.get('cat') or '').strip().lower()
    colegio_id = (request.GET.get('colegio') or '').strip()
    talla = (request.GET.get('talla') or '').strip()
    precio_min = (request.GET.get('precio_min') or '').strip()
    precio_max = (request.GET.get('precio_max') or '').strip()
    query = (request.GET.get('q') or '').strip()

    tiene_stock_variante = StockTienda.objects.filter(
        tienda=tienda, variante__producto=OuterRef('pk'), cantidad__gt=0
    )
    tiene_stock_directo = StockTienda.objects.filter(
        tienda=tienda, producto=OuterRef('pk'), cantidad__gt=0
    )

    productos_qs = (
        Producto.objects
        .filter(activo=True)
        .select_related('familia', 'colegio')
        .annotate(
            hay_stock_variante=Exists(tiene_stock_variante),
            hay_stock_directo=Exists(tiene_stock_directo),
        )
    )
    productos_qs = productos_qs.filter(hay_stock_variante=True) | productos_qs.filter(
        hay_stock_directo=True
    )

    if familia_id.isdigit():
        productos_qs = productos_qs.filter(familia_id=int(familia_id))
    elif cat_slug in CAT_SLUGS:
        productos_qs = productos_qs.filter(familia__in=_familias_por_slug(cat_slug))

    if colegio_id.isdigit():
        productos_qs = productos_qs.filter(colegio_id=int(colegio_id))

    if talla:
        # Solo productos con al menos una variante de esa talla, activa, y
        # con stock > 0 en la tienda online.
        variantes_con_talla = StockTienda.objects.filter(
            tienda=tienda, cantidad__gt=0,
            variante__activa=True,
            variante__producto=OuterRef('pk'),
            variante__valores__atributo__nombre__iexact='Talla',
            variante__valores__valor__iexact=talla,
        )
        productos_qs = productos_qs.annotate(
            hay_stock_talla=Exists(variantes_con_talla),
        ).filter(hay_stock_talla=True)

    if precio_min:
        try:
            productos_qs = productos_qs.filter(precio_base__gte=Decimal(precio_min))
        except (InvalidOperation, ValueError):
            pass
    if precio_max:
        try:
            productos_qs = productos_qs.filter(precio_base__lte=Decimal(precio_max))
        except (InvalidOperation, ValueError):
            pass

    if query:
        # Accent-insensitive: comparamos contra los campos buscables que
        # mantenemos normalizados al guardar (lowercase + sin acentos).
        q_norm = normalize_text(query)
        productos_qs = productos_qs.filter(
            Q(nombre_buscable__contains=q_norm)
            | Q(descripcion_buscable__contains=q_norm)
        )

    cart = Cart(request.session)

    categorias = [
        {'slug': slug, 'title': info['title'], 'desc': info['desc'], 'accent': info['accent']}
        for slug, info in CAT_SLUGS.items()
    ]
    cat_info = CAT_SLUGS.get(cat_slug) if cat_slug in CAT_SLUGS else None

    # Tallas disponibles según stock real en la tienda — no listamos
    # tallas que no existen para nada o están agotadas.
    tallas_disponibles = list(
        ValorAtributo.objects
        .filter(
            atributo__nombre__iexact='Talla',
            variantes__activa=True,
            variantes__stock_tienda__tienda=tienda,
            variantes__stock_tienda__cantidad__gt=0,
        )
        .order_by('orden', 'valor')
        .values_list('valor', flat=True)
        .distinct()
    )

    return render(request, 'ecommerce/catalogo.html', {
        'productos': productos_qs.order_by('familia__nombre', 'nombre').distinct(),
        'familias': Familia.objects.all(),
        'familia_activa': int(familia_id) if familia_id.isdigit() else None,
        'categorias': categorias,
        'cat_activa': cat_slug if cat_slug in CAT_SLUGS else '',
        'cat_info': cat_info,
        'colegios': Colegio.objects.filter(activo=True).order_by('nombre'),
        'colegio_activo': int(colegio_id) if colegio_id.isdigit() else None,
        'tallas_disponibles': tallas_disponibles,
        'talla_activa': talla,
        'precio_min': precio_min,
        'precio_max': precio_max,
        'query': query,
        'items_count': cart.items_count,
    })


def detalle_producto(request, pk: int):
    producto = get_object_or_404(Producto, pk=pk, activo=True)
    try:
        tienda = get_tienda_online()
    except TiendaOnlineNoConfigurada:
        return render(request, 'ecommerce/sin_tienda.html', status=503)

    stock_directo = (
        StockTienda.objects
        .filter(tienda=tienda, producto=producto)
        .values_list('cantidad', flat=True)
        .first()
        or 0
    )

    if producto.tiene_variantes:
        from django.db.models import Min
        stock_sq = StockTienda.objects.filter(
            tienda=tienda, variante=OuterRef('pk')
        ).values('cantidad')[:1]
        # Annotate `orden_talla` con el `orden` del valor cuyo atributo es
        # "Talla" — eso permite mostrar 4,6,8,10,12,14,16,S,M,L,XL,XXL en
        # el orden natural en lugar de orden alfabético del SKU.
        variantes = (
            producto.variantes.filter(activa=True)
            .prefetch_related('valores__atributo')
            .annotate(
                stock=Subquery(stock_sq),
                orden_talla=Min(
                    'valores__orden',
                    filter=Q(valores__atributo__nombre__iexact='Talla'),
                ),
            )
            .order_by('orden_talla', 'sku')
        )
    else:
        variantes = producto.variantes.none()

    cart = Cart(request.session)
    return render(request, 'ecommerce/producto.html', {
        'producto': producto,
        'variantes': variantes,
        'stock_directo': stock_directo,
        'items_count': cart.items_count,
    })


def ver_carrito(request):
    cart = Cart(request.session)
    subtotal_bruto, descuento_total, total_neto = cart.totales()
    return render(request, 'ecommerce/carrito.html', {
        'lineas': list(cart.lineas()),
        'subtotal_bruto': subtotal_bruto,
        'descuento_total': descuento_total,
        'total_neto': total_neto,
        'items_count': cart.items_count,
    })


@require_POST
def agregar(request):
    form = AgregarForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Datos inválidos.')
        return redirect('ecommerce:catalogo')

    cart = Cart(request.session)
    tipo = form.cleaned_data['tipo']
    item_id = form.cleaned_data['item_id']
    cantidad = form.cleaned_data['cantidad']

    if tipo == 'v':
        if not ProductoVariante.objects.filter(pk=item_id, activa=True).exists():
            messages.error(request, 'Variante no disponible.')
            return redirect('ecommerce:catalogo')
        cart.add_variante(item_id, cantidad)
    else:
        if not Producto.objects.filter(
            pk=item_id, activo=True, tiene_variantes=False
        ).exists():
            messages.error(request, 'Producto no disponible.')
            return redirect('ecommerce:catalogo')
        cart.add_producto(item_id, cantidad)

    return redirect('ecommerce:carrito')


@require_POST
def actualizar(request):
    form = ActualizarCantidadForm(request.POST)
    if form.is_valid():
        Cart(request.session).set_cantidad(form.cleaned_data['key'], form.cleaned_data['cantidad'])
    return redirect('ecommerce:carrito')


@require_POST
def quitar(request, key: str):
    Cart(request.session).remove(key)
    return redirect('ecommerce:carrito')


@require_POST
def vaciar(request):
    Cart(request.session).clear()
    return redirect('ecommerce:carrito')


def checkout(request):
    cart = Cart(request.session)
    if cart.is_empty():
        return redirect('ecommerce:carrito')
    subtotal_bruto, descuento_total, total_neto = cart.totales()
    return render(request, 'ecommerce/checkout.html', {
        'lineas': list(cart.lineas()),
        'subtotal_bruto': subtotal_bruto,
        'descuento_total': descuento_total,
        'total_neto': total_neto,
        'items_count': cart.items_count,
        'form': CheckoutForm(initial=_checkout_initial(request)),
    })


def _checkout_initial(request) -> dict:
    """Prefill del checkout para clientes logueados."""
    if not request.user.is_authenticated:
        return {}
    user = request.user
    nombre = (f'{user.first_name} {user.last_name}'.strip()) or user.username
    return {
        'cliente_nombre': nombre,
        'cliente_email': user.email or '',
    }


@require_POST
def checkout_iniciar(request):
    cart = Cart(request.session)
    if cart.is_empty():
        return redirect('ecommerce:carrito')

    form = CheckoutForm(request.POST)
    if not form.is_valid():
        subtotal_bruto, descuento_total, total_neto = cart.totales()
        return render(request, 'ecommerce/checkout.html', {
            'lineas': list(cart.lineas()),
            'subtotal_bruto': subtotal_bruto,
            'descuento_total': descuento_total,
            'total_neto': total_neto,
            'items_count': cart.items_count,
            'form': form,
        }, status=400)

    items = [
        ItemPedido(
            tipo=linea['tipo'],
            item_id=linea['item'].pk,
            cantidad=linea['cantidad'],
            precio_unitario=linea['precio_unitario'],
            descuento_total=linea['descuento_total'],
        )
        for linea in cart.lineas()
    ]

    return_url = request.build_absolute_uri(reverse('ecommerce:checkout_retorno'))
    try:
        recibo, init = iniciar_pedido(
            items=items,
            cliente_nombre=form.cleaned_data['cliente_nombre'],
            cliente_email=form.cleaned_data['cliente_email'],
            cliente_rut=form.cleaned_data.get('cliente_rut', ''),
            cliente_telefono=form.cleaned_data.get('cliente_telefono', ''),
            cliente_direccion=form.cleaned_data.get('cliente_direccion', ''),
            cliente_usuario=request.user if request.user.is_authenticated else None,
            return_url=return_url,
        )
    except StockInsuficienteOnline as exc:
        messages.error(request, f'Stock insuficiente para {exc.descripcion}: quedan {exc.disponible}.')
        return redirect('ecommerce:carrito')
    except TiendaOnlineNoConfigurada:
        messages.error(request, 'La tienda online no está configurada todavía.')
        return redirect('ecommerce:carrito')
    except PaymentGatewayError as exc:
        messages.error(request, f'No pudimos iniciar el pago: {exc}')
        return redirect('ecommerce:carrito')

    # Guardamos el token en sesión para poder retomarlo si el cliente vuelve sin query string.
    request.session['ecommerce_token_pendiente'] = init.token
    request.session.modified = True

    return HttpResponseRedirect(init.redirect_url)


@require_GET
def checkout_retorno(request):
    """Vuelta del gateway. Webpay manda `token_ws`; el mock usa `token`."""
    token = (
        request.GET.get('token_ws')
        or request.GET.get('token')
        or request.session.get('ecommerce_token_pendiente', '')
    )
    if not token:
        return render(request, 'ecommerce/retorno.html', {
            'error': 'No se recibió token de la pasarela.',
        }, status=400)

    try:
        recibo = confirmar_pedido(token=token)
    except PedidoNoEncontrado:
        return render(request, 'ecommerce/retorno.html', {
            'error': 'No encontramos el pedido asociado a este pago.',
        }, status=404)

    # Limpieza del carrito y notificación si quedó pagado.
    if recibo.estado == ReciboVenta.ESTADO_PAGADO:
        Cart(request.session).clear()
        request.session.pop('ecommerce_token_pendiente', None)
        try:
            enviar_boleta(recibo)
        except Exception:  # noqa: BLE001 — el flujo de compra no debe romperse por email.
            log.exception('Error enviando boleta recibo %s', recibo.pk)
        return redirect('ecommerce:pedido', token=recibo.payment_reference)

    return render(request, 'ecommerce/retorno.html', {
        'recibo': recibo,
        'error': None,
    })


def ver_pedido(request, token: str):
    recibo = get_object_or_404(
        ReciboVenta.objects.prefetch_related('detalles'),
        canal=ReciboVenta.CANAL_ONLINE,
        payment_reference=token,
    )
    return render(request, 'ecommerce/pedido.html', {'recibo': recibo})


def mock_pago(request):
    """Simulador de pasarela para el gateway 'mock'.

    Sólo se expone si el gateway activo es el mock; con otros gateways
    (p.ej. webpay real) esta vista devuelve 404.
    """
    gateway = get_online_gateway()
    if gateway.provider != 'mock-online':
        raise Http404('Mock deshabilitado')

    token = request.GET.get('token', '')
    return_url = request.GET.get('return_url', '')
    if not token or not return_url:
        return render(request, 'ecommerce/retorno.html', {
            'error': 'Mock pago sin token o return_url.',
        }, status=400)

    if request.method == 'POST':
        decision = request.POST.get('decision', 'aprobar')
        sufijo = ''
        if decision == 'rechazar':
            sufijo = ':fail'
        elif decision == 'cancelar':
            sufijo = ':cancel'

        if sufijo:
            # Reescribimos el payment_reference del recibo para que el retorno
            # lo ubique y el gateway le devuelva el estado coherente.
            nuevo_token = token + sufijo
            ReciboVenta.objects.filter(payment_reference=token).update(
                payment_reference=nuevo_token
            )
            token_efectivo = nuevo_token
        else:
            token_efectivo = token

        # Webpay manda ?token_ws=...; replicamos ese contrato.
        sep = '&' if '?' in return_url else '?'
        return HttpResponseRedirect(f'{return_url}{sep}token_ws={token_efectivo}')

    return render(request, 'ecommerce/mock_pago.html', {
        'token': token,
        'return_url': return_url,
    })
