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
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from bodega.models import StockTienda
from catalogo.models import Colegio, Familia, Oferta, Producto, ProductoVariante, ValorAtributo
from ecommerce.cart import CANAL, Cart
from ecommerce.emails import enviar_boleta, notificar_dueno_nueva_orden
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


SORT_OPTIONS = {
    # slug -> tupla de campos para order_by()
    'relevant': ('familia__nombre', 'nombre'),
    'low':      ('precio_base', 'nombre'),
    'high':     ('-precio_base', 'nombre'),
    'new':      ('-creado',),
}


def _seo_context_catalogo(*, cat_info, colegio):
    """Devuelve dict con seo_titulo / seo_descripcion / seo_h1 cuando aplica.

    Sprint 3 · 3.3: cuando el visitante llega filtrando por colegio,
    Google ve un H1 y un title locales ("Uniformes Colegio San Francisco
    Javier Los Vilos") en vez del genérico "Uniformes Escolares". Es la
    query de mayor intención de compra de la zona; vale el SEO.
    """
    if colegio and cat_info and cat_info['title'].startswith('Uniformes'):
        # Sufijo geográfico explícito para el match local de "los vilos".
        return {
            'seo_titulo': f'Uniformes {colegio.nombre} · Los Vilos · Ideas Boutique',
            'seo_h1': f'Uniformes {colegio.nombre}',
            'seo_descripcion': (
                f'Buzos, chalecos y poleras del {colegio.nombre} en Ideas Boutique '
                f'(Caupolicán 437-B, Los Vilos). Telas duraderas, ajustes sin '
                f'costo. Tres generaciones vistiendo a las familias de la zona.'
            ),
        }
    return {}


def catalogo(request):
    """Listado público de productos con stock > 0 en la tienda online.

    Filtros vía querystring:
      cat=<slug> | familia=<pk> | colegio=<pk> | talla=<valor>
      precio_min, precio_max | q=<texto>  (accent + case insensitive)
      sort=relevant|low|high|new
      oferta=1  → solo productos con al menos una oferta vigente online
    """
    from django.utils import timezone
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
    solo_ofertas = (request.GET.get('oferta') or '').strip() == '1'
    sort = (request.GET.get('sort') or 'relevant').strip()
    if sort not in SORT_OPTIONS:
        sort = 'relevant'

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

    # El filtro por colegio solo aplica a uniformes — perfumes, moda y
    # ropa íntima no tienen colegio asociado, así que combinar
    # `cat=perfumes&colegio=X` daría 0 resultados. Cuando el usuario
    # cambia de categoría manteniendo un colegio seleccionado, ignoramos
    # silenciosamente el filtro y limpiamos `colegio_activo` para que el
    # sidebar tampoco lo muestre como activo.
    colegio_aplicable = cat_slug in ('', 'uniformes')
    aplicar_filtro_colegio = colegio_id.isdigit() and colegio_aplicable
    if aplicar_filtro_colegio:
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

    if solo_ofertas:
        # "Solo ofertas vigentes" del header de la tienda. Vigente =
        # activa + en ventana de fechas + canal online o ambos.
        # La oferta puede apuntar al producto o a una variante del
        # producto — ambos casos lo hacen "estar en oferta".
        ahora = timezone.now()
        ofertas_vigentes = Oferta.objects.filter(
            activa=True,
            fecha_inicio__lte=ahora,
            fecha_fin__gte=ahora,
            canal__in=(Oferta.CANAL_ONLINE, Oferta.CANAL_AMBOS),
        )
        oferta_directa = ofertas_vigentes.filter(producto=OuterRef('pk'))
        oferta_via_variante = ofertas_vigentes.filter(
            variante__producto=OuterRef('pk'),
        )
        productos_qs = productos_qs.annotate(
            tiene_oferta_directa=Exists(oferta_directa),
            tiene_oferta_via_variante=Exists(oferta_via_variante),
        ).filter(
            Q(tiene_oferta_directa=True) | Q(tiene_oferta_via_variante=True)
        )

    cart = Cart(request.session)

    categorias = [
        {'slug': slug, 'title': info['title'], 'desc': info['desc'], 'accent': info['accent']}
        for slug, info in CAT_SLUGS.items()
    ]
    cat_info = CAT_SLUGS.get(cat_slug) if cat_slug in CAT_SLUGS else None

    # Tallas disponibles para el filtro lateral. Solo de los productos
    # actualmente visibles en el catálogo filtrado — así el filtro no
    # aparece en /tienda/?cat=perfumes (donde no aplica) y solo se ven
    # tallas que el cliente realmente puede comprar.
    productos_visibles_ids = list(
        productos_qs.distinct().values_list('pk', flat=True)
    )
    tallas_disponibles = list(
        ValorAtributo.objects
        .filter(
            atributo__nombre__iexact='Talla',
            variantes__activa=True,
            variantes__producto_id__in=productos_visibles_ids,
            variantes__stock_tienda__tienda=tienda,
            variantes__stock_tienda__cantidad__gt=0,
        )
        .order_by('orden', 'valor')
        .values_list('valor', flat=True)
        .distinct()
    )

    # Paginacion para scroll infinito. La primera carga trae PAGE_SIZE
    # productos; las siguientes paginas se cargan via HTMX cuando el
    # cliente llega al final de la grilla.
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
    PAGE_SIZE = 12  # 3 columnas x 4 filas en desktop, equilibrado movil
    productos_ordenados = productos_qs.order_by(*SORT_OPTIONS[sort]).distinct()
    paginator = Paginator(productos_ordenados, PAGE_SIZE)
    page_num = (request.GET.get('page') or '1').strip()
    try:
        page_obj = paginator.page(int(page_num) if page_num.isdigit() else 1)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    # URL de la pagina siguiente preservando todos los filtros activos.
    next_page_url = ''
    if page_obj.has_next():
        qd = request.GET.copy()
        qd['page'] = page_obj.next_page_number()
        next_page_url = f'{request.path}?{qd.urlencode()}'

    # Cuando HTMX pide una pagina > 1, devolvemos solo el fragment de
    # productos (mas el sentinel de la siguiente pagina si existe). El
    # cliente lo intercala en la grilla via hx-swap=outerHTML del sentinel.
    if request.htmx and page_obj.number > 1:
        return render(request, 'ecommerce/_catalogo_pagina.html', {
            'productos': page_obj.object_list,
            'next_page_url': next_page_url,
        })

    return render(request, 'ecommerce/catalogo.html', {
        'productos': page_obj.object_list,
        'next_page_url': next_page_url,
        'page_obj': page_obj,
        'total_productos': paginator.count,
        'sort': sort,
        'familias': Familia.objects.all(),
        'familia_activa': int(familia_id) if familia_id.isdigit() else None,
        'categorias': categorias,
        'cat_activa': cat_slug if cat_slug in CAT_SLUGS else '',
        'cat_info': cat_info,
        'colegios': Colegio.objects.filter(activo=True).order_by('nombre'),
        'colegio_activo': int(colegio_id) if aplicar_filtro_colegio else None,
        'colegio_aplicable': colegio_aplicable,
        'tallas_disponibles': tallas_disponibles,
        'talla_activa': talla,
        'precio_min': precio_min,
        'precio_max': precio_max,
        'query': query,
        'solo_ofertas': solo_ofertas,
        'items_count': cart.items_count,
        **_seo_context_catalogo(
            cat_info=cat_info,
            colegio=(
                Colegio.objects.filter(pk=int(colegio_id)).first()
                if aplicar_filtro_colegio else None
            ),
        ),
    })


@require_GET
def buscar_json(request):
    """Endpoint para el live search dropdown de la tienda.

    Devuelve hasta 6 productos y hasta 2 colegios que coincidan con el
    query, accent + case insensitive. Solo productos con stock visible
    en la tienda online configurada.

    Esquema:
        {
          "productos": [{id, nombre, categoria, colegio, precio, img}],
          "colegios":  [{id, nombre}]
        }
    """
    from django.http import JsonResponse
    from django.templatetags.static import static
    from edTech.search import normalize_text
    from catalogo.templatetags.catalogo_extras import imagen_producto

    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse({'productos': [], 'colegios': []})

    try:
        tienda = get_tienda_online()
    except TiendaOnlineNoConfigurada:
        return JsonResponse({'productos': [], 'colegios': []})

    q_norm = normalize_text(q)

    # Productos con stock real en la tienda online.
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
        .filter(
            Q(hay_stock_variante=True) | Q(hay_stock_directo=True)
        )
        .filter(
            Q(nombre_buscable__contains=q_norm)
            | Q(descripcion_buscable__contains=q_norm)
        )
        .distinct()[:12]  # tomamos un poco mas para poder rankear
    )

    # Score: prefix-match en nombre suma muchos puntos; match en
    # descripcion suma uno. Asi "buzo" rankea Buzo SFJ Completo arriba
    # antes que un perfume cuya descripcion mencione "buzo".
    productos_score = []
    for p in productos_qs:
        nombre_n = p.nombre_buscable or ''
        score = 0
        if nombre_n.startswith(q_norm):
            score += 10
        elif q_norm in nombre_n:
            score += 5
        if q_norm in (p.descripcion_buscable or ''):
            score += 1
        productos_score.append((score, p))
    productos_score.sort(key=lambda x: -x[0])
    top = [p for _, p in productos_score[:6]]

    productos_data = [{
        'id': p.pk,
        'nombre': p.nombre,
        'categoria': p.familia.nombre,
        'colegio': p.colegio.nombre if p.colegio_id else '',
        'precio': float(p.precio_minimo),
        'precios_varian': p.precios_varian_por_variante,
        'img': imagen_producto(p),
        'url': f'/tienda/p/{p.pk}/',
    } for p in top]

    colegios_qs = (
        Colegio.objects
        .filter(activo=True, nombre_buscable__contains=q_norm)[:2]
    )
    colegios_data = [
        {'id': c.pk, 'nombre': c.nombre, 'url': f'/tienda/?colegio={c.pk}'}
        for c in colegios_qs
    ]

    return JsonResponse({'productos': productos_data, 'colegios': colegios_data})


@require_GET
def quick_view(request, pk: int):
    """Vista rápida del producto: fragment HTML que se carga en un
    modal de la página del catálogo sin que el cliente pierda su lugar.

    Devuelve solo el resumen necesario para decidir: imagen, nombre,
    familia, precio (con descuento si aplica), descripción corta,
    chips de variantes disponibles, y un link "Ver detalle completo".
    El "Agregar al carrito" rápido es un formulario HTMX que reutiliza
    `/tienda/agregar/`.
    """
    try:
        tienda = get_tienda_online()
    except TiendaOnlineNoConfigurada:
        return HttpResponse(status=503)

    producto = get_object_or_404(
        Producto.objects.select_related('familia', 'colegio'),
        pk=pk, activo=True,
    )

    # Variantes activas con stock — solo lo mínimo para el chip.
    variantes = []
    if producto.tiene_variantes:
        stock_sq = StockTienda.objects.filter(
            tienda=tienda, variante=OuterRef('pk'),
        ).values('cantidad')[:1]
        variantes = list(
            producto.variantes
            .filter(activa=True)
            .prefetch_related('valores__atributo')
            .annotate(stock=Subquery(stock_sq))
            .order_by('sku')
        )

    return render(request, 'ecommerce/_quick_view.html', {
        'producto': producto,
        'variantes': variantes,
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
        # Annotate los `orden` de cada valor por atributo — eso permite
        # mostrar las variantes en orden natural en vez de alfabético del
        # SKU. Tallas: 4,6,8,10,12,14,16,S,M,L,XL,XXL. Perfumes: por
        # volumen creciente (5ml -> 200ml) y dentro de cada volumen por
        # concentración (Cologne -> Elixir).
        variantes = (
            producto.variantes.filter(activa=True)
            .prefetch_related('valores__atributo')
            .annotate(
                stock=Subquery(stock_sq),
                orden_talla=Min(
                    'valores__orden',
                    filter=Q(valores__atributo__nombre__iexact='Talla'),
                ),
                orden_volumen=Min(
                    'valores__orden',
                    filter=Q(valores__atributo__nombre__iexact='Volumen'),
                ),
                orden_concentracion=Min(
                    'valores__orden',
                    filter=Q(valores__atributo__nombre__iexact='Concentración'),
                ),
            )
            .order_by('orden_talla', 'orden_volumen', 'orden_concentracion', 'sku')
        )
    else:
        variantes = producto.variantes.none()

    # Label dinámico para el selector. Una polera tiene atributos {Talla},
    # un perfume {Volumen, Concentración} — el cliente pelo "Elegí tu talla"
    # como si fuera el mismo producto, así que adaptamos el copy.
    nombres_atributos = set()
    for v in variantes:
        for val in v.valores.all():
            nombres_atributos.add(val.atributo.nombre)
    if not nombres_atributos:
        label_eleccion = 'variante'
    elif nombres_atributos == {'Talla'}:
        label_eleccion = 'talla'
    elif nombres_atributos == {'Volumen'}:
        label_eleccion = 'formato'
    elif nombres_atributos == {'Volumen', 'Concentración'}:
        label_eleccion = 'formato'
    elif len(nombres_atributos) == 1:
        # Único atributo desconocido: usar su nombre minúsculo.
        label_eleccion = next(iter(nombres_atributos)).lower()
    else:
        label_eleccion = 'variante'

    # ¿Las variantes tienen labels largos? Sirve para que el template aplique
    # estilos más anchos en el chip (perfumes con "30 ml Eau de Parfum").
    chips_anchos = any(
        len(' · '.join(str(val.valor) for val in v.valores.all())) > 5
        for v in variantes
    )

    cart = Cart(request.session)
    # Bloque 8: galeria real. Cargamos las imagenes adicionales del PDP.
    # `imagenes_galeria` solo se llama una vez en el template; prefetch
    # no aporta porque es una relacion 1->N que el template itera plano.
    imagenes_galeria = list(producto.imagenes.all())
    return render(request, 'ecommerce/producto.html', {
        'producto': producto,
        'variantes': variantes,
        'stock_directo': stock_directo,
        'items_count': cart.items_count,
        'label_eleccion': label_eleccion,
        'chips_anchos': chips_anchos,
        'imagenes_galeria': imagenes_galeria,
    })


def ver_carrito(request):
    cart = Cart(request.session)
    subtotal_bruto, descuento_total, total_neto = cart.totales()

    # Sprint 2 · 2.1: si hay errores guardados del intento de checkout,
    # los inyectamos en las lineas correspondientes. Se consumen y se
    # borran al renderizar — no queremos mostrar el error eternamente.
    cart_errors = request.session.pop('cart_errors', {}) or {}
    request.session.modified = True

    lineas = list(cart.lineas())
    for linea in lineas:
        err = cart_errors.get(linea['key'])
        if err:
            linea['error'] = err

    return render(request, 'ecommerce/carrito.html', {
        'lineas': lineas,
        'subtotal_bruto': subtotal_bruto,
        'descuento_total': descuento_total,
        'total_neto': total_neto,
        'items_count': cart.items_count,
    })


@require_POST
def agregar(request):
    """Agrega un item al carrito.

    Comportamiento dual:
    - Request HTMX: agrega al cart y devuelve un fragment con
      `hx-swap-oob` que actualiza el badge del carrito + inyecta los
      toasts del messages framework. El cliente queda donde estaba
      (catalogo / PDP), ve "+ Yara al carrito" y el contador sube.
    - Request tradicional (no JS): agrega y redirige al carrito.
    """
    form = AgregarForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Datos inválidos.')
        return _respuesta_agregar(request)

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
            return _respuesta_agregar(request)
        cart.add_variante(item_id, cantidad)
        messages.success(
            request,
            f'+ {variante.producto.nombre} ({variante.sku}) agregado al carrito.',
        )
    else:
        producto = Producto.objects.filter(
            pk=item_id, activo=True, tiene_variantes=False,
        ).first()
        if not producto:
            messages.error(request, 'Producto no disponible.')
            return _respuesta_agregar(request)
        cart.add_producto(item_id, cantidad)
        messages.success(
            request, f'+ {producto.nombre} agregado al carrito.',
        )

    return _respuesta_agregar(request)


def _respuesta_agregar(request):
    """Devuelve la respuesta adecuada para `agregar`:
    - HTMX: fragment con OOB del badge + toasts.
    - Otro: redirect al carrito.
    """
    if request.htmx:
        cart = Cart(request.session)
        return render(request, 'ecommerce/_cart_oob_update.html', {
            'items_count': cart.items_count,
        })
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
def validar_rut_inline(request):
    """Endpoint HTMX para validar RUT chileno mientras el cliente
    completa el checkout (hx-trigger="change delay:300ms").

    Devuelve fragment HTML chico con clase css indicando el estado:
    - .field-msg.field-msg-ok    -> verde, "RUT válido"
    - .field-msg.field-msg-error -> vino, mensaje del error
    - vacío si el campo está vacío (no hay nada que mostrar).
    """
    from ecommerce.validators import validar_rut_chileno
    from django.core.exceptions import ValidationError

    rut = (request.POST.get('cliente_rut') or '').strip()
    if not rut:
        return render(request, 'ecommerce/_field_msg.html', {})

    try:
        normalizado = validar_rut_chileno(rut)
        return render(request, 'ecommerce/_field_msg.html', {
            'estado': 'ok',
            'texto': f'RUT válido: {normalizado}',
        })
    except ValidationError as exc:
        return render(request, 'ecommerce/_field_msg.html', {
            'estado': 'error',
            'texto': exc.messages[0],
        })


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
        # Sprint 2 · 2.1: marcar la linea conflictiva en sesion para que
        # el carrito la renderice con borde rojo + CTA de ajuste. Toast
        # corto, el detalle vive en la linea.
        if exc.tipo and exc.item_id:
            request.session['cart_errors'] = {
                f'{exc.tipo}:{exc.item_id}': {
                    'codigo': 'stock_insuficiente',
                    'titulo': 'Stock insuficiente',
                    'mensaje': (
                        f'Quedan {exc.disponible} unidades — tienes '
                        f'{exc.solicitado} en el carrito.'
                    ),
                    'accion': {
                        'label': f'Ajustar a {exc.disponible}',
                        'cantidad': exc.disponible,
                    } if exc.disponible > 0 else None,
                },
            }
            request.session.modified = True
        messages.error(
            request,
            f'Stock insuficiente para {exc.descripcion}. Revisa la línea marcada en rojo.',
        )
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
        try:
            # Sprint 3 · 3.5: avisar a Blanca apenas entra la venta.
            notificar_dueno_nueva_orden(recibo)
        except Exception:  # noqa: BLE001 — idem, no bloqueante.
            log.exception('Error notificando al dueño sobre recibo %s', recibo.pk)
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
