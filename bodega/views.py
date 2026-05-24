"""Vistas de bodega: stock por tienda + CRUD de catálogo desde el backoffice.

La intención es que el bodeguero/admin no tenga que entrar al Django admin
para gestionar productos día a día — esos son flujos repetitivos del
negocio. /admin/ queda para el superusuario en casos especiales.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import generic
from django.views.decorators.http import require_POST

from bodega.forms import (
    MaterialForm, OfertaForm, ProductoForm, ProductoVarianteForm,
    RendimientoForm, StockInicialForm,
)
from bodega.models import (
    Material,
    MovimientoStock,
    Rendimiento,
    StockMaterial,
    StockTienda,
    Tienda,
)
from catalogo.models import Colegio, Familia, Oferta, Producto, ProductoVariante


# Umbrales de alerta de stock.
STOCK_AGOTADO = 0
STOCK_BAJO = 5


def _puede_reponer(user) -> bool:
    """Bodeguero, admin (grupo) o superuser pueden reponer stock.

    Cajeros NO — el cajero solo opera ventas. La idea es que el
    bodeguero use exclusivamente la pantalla de bodega para reponer.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=['admin', 'bodeguero']).exists()


def _puede_gestionar_ofertas(user) -> bool:
    """Solo admin (grupo) o superuser. El bodeguero no decide ofertas —
    es una decisión comercial, no de stock."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='admin').exists()


class StockView(LoginRequiredMixin, PermissionRequiredMixin, generic.TemplateView):
    """Stock de productos por tienda con filtros y carga de reposición.

    Filtros vía querystring:
      ?tienda=<pk>     — tienda específica
      ?familia=<pk>    — familia (Buzos, Perfumes, etc)
      ?colegio=<pk>    — colegio (uniformes)
      ?solo=bajo|cero  — solo bajos o agotados
      ?stock=todos     — incluir agotados (default: solo con stock)
      ?q=...           — búsqueda por nombre / SKU
    """
    permission_required = 'bodega.view_stocktienda'
    template_name = 'bodega/stock.html'

    def get(self, request, *args, **kwargs):
        # Si la request es HTMX, devolvemos solo el partial de la
        # tabla (mismo patron que productos/ofertas/materiales).
        if getattr(request, 'htmx', False):
            self.template_name = 'bodega/_stock_tabla.html'
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request

        qs = (
            StockTienda.objects
            .select_related(
                'tienda',
                'variante__producto', 'variante__producto__familia',
                'variante__producto__colegio',
                'producto', 'producto__familia', 'producto__colegio',
            )
            .order_by('tienda__nombre_organizacion', 'producto__nombre',
                      'variante__producto__nombre', 'variante__sku')
        )

        tienda_id = (request.GET.get('tienda') or '').strip()
        familia_id = (request.GET.get('familia') or '').strip()
        colegio_id = (request.GET.get('colegio') or '').strip()
        # Filtro unificado de visibilidad de stock. Antes habian dos
        # selectores ("Mostrar" y "Stock") que se pisaban — `solo` ahora
        # tiene 4 opciones que cubren todos los casos. Retrocompat: el
        # viejo `stock=todos` se sigue aceptando.
        solo = (request.GET.get('solo') or '').strip()
        if request.GET.get('stock') == 'todos' and not solo:
            solo = 'todos'  # retrocompat con URLs viejas
        mostrar_todos = (solo == 'todos')
        q = (request.GET.get('q') or '').strip()

        if tienda_id.isdigit():
            qs = qs.filter(tienda_id=int(tienda_id))
        if familia_id.isdigit():
            f = int(familia_id)
            qs = qs.filter(Q(producto__familia_id=f) | Q(variante__producto__familia_id=f))
        if colegio_id.isdigit():
            c = int(colegio_id)
            qs = qs.filter(Q(producto__colegio_id=c) | Q(variante__producto__colegio_id=c))
        if solo == 'cero':
            qs = qs.filter(cantidad=STOCK_AGOTADO)
        elif solo == 'bajo':
            qs = qs.filter(cantidad__lte=STOCK_BAJO, cantidad__gt=0)
        elif solo == 'todos':
            # No aplica filtro de cantidad — muestra TODO.
            pass
        else:
            # Default: oculta agotados.
            qs = qs.filter(cantidad__gt=0)
        if q:
            from edTech.search import normalize_text
            q_norm = normalize_text(q)
            qs = qs.filter(
                Q(producto__nombre_buscable__contains=q_norm)
                | Q(variante__producto__nombre_buscable__contains=q_norm)
                | Q(variante__sku__icontains=q)
            )

        items = list(qs)

        # KPIs sobre el set completo (no solo el filtrado), para que reflejen
        # el estado real del negocio sin importar qué filtro hay puesto.
        global_qs = StockTienda.objects.all()
        if tienda_id.isdigit():
            global_qs = global_qs.filter(tienda_id=int(tienda_id))
        n_total_global = global_qs.count()
        n_agotado = global_qs.filter(cantidad=STOCK_AGOTADO).count()
        n_bajo = global_qs.filter(cantidad__lte=STOCK_BAJO, cantidad__gt=0).count()
        n_ok = n_total_global - n_agotado - n_bajo
        unidades_totales = (
            global_qs.aggregate(s=Sum('cantidad'))['s'] or 0
        )
        rollos_total = (
            StockMaterial.objects.aggregate(s=Sum('cantidad'))['s'] or 0
        )

        ctx.update({
            'stock': items,
            'kpi': {
                'n_ok': n_ok,
                'n_bajo': n_bajo,
                'n_agotado': n_agotado,
                'unidades_totales': unidades_totales,
                'rollos_total': rollos_total,
            },
            'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
            'familias': Familia.objects.order_by('nombre'),
            'colegios': Colegio.objects.filter(activo=True).order_by('nombre'),
            'filtros': {
                'tienda': tienda_id, 'familia': familia_id, 'colegio': colegio_id,
                'solo': solo, 'q': q,
            },
            'mostrar_todos': mostrar_todos,
            'umbral_bajo': STOCK_BAJO,
            'puede_reponer': _puede_reponer(request.user),
            # Carga masiva: solo admin. Mucho poder en una sola operacion.
            'puede_bulk_stock': _puede_gestionar_ofertas(request.user),
        })
        return ctx


@login_required
@require_POST
def set_stock(request, pk):
    """Setea el stock absoluto de una fila StockTienda existente.

    Pensado para edicion inline desde la pantalla de stock: el usuario
    clickea el numero, lo edita, presiona Enter. La diferencia con la
    cantidad anterior se registra como MovimientoStock (ENTRADA o
    SALIDA segun signo) para preservar la auditoria.

    Si el request viene de HTMX, devuelve solo la fila actualizada.
    """
    if not _puede_reponer(request.user):
        messages.error(request, 'No tienes permisos para editar stock.')
        return redirect('bodega:stock')

    fila = get_object_or_404(
        StockTienda.objects.select_related('tienda', 'producto', 'variante__producto'),
        pk=pk,
    )

    try:
        nueva = int(request.POST.get('cantidad', '-1'))
    except (TypeError, ValueError):
        messages.error(request, 'Cantidad inválida.')
        return redirect('bodega:stock')

    if nueva < 0 or nueva > 99999:
        messages.error(request, 'La cantidad debe estar entre 0 y 99.999.')
        return redirect('bodega:stock')

    with transaction.atomic():
        bloqueada = StockTienda.objects.select_for_update().get(pk=fila.pk)
        delta = nueva - bloqueada.cantidad
        StockTienda.objects.filter(pk=fila.pk).update(cantidad=nueva)
        if delta != 0:
            MovimientoStock.objects.create(
                tienda=bloqueada.tienda,
                variante=bloqueada.variante,
                producto=bloqueada.producto,
                tipo=MovimientoStock.ENTRADA if delta > 0 else MovimientoStock.SALIDA,
                cantidad=abs(delta),
                referencia=f'Ajuste manual por {request.user.username}',
                usuario=request.user,
            )

    fila.refresh_from_db()
    messages.success(
        request,
        f'Stock actualizado: {fila.cantidad} unidad{"es" if fila.cantidad != 1 else ""}.',
    )

    if request.htmx:
        return render(request, 'bodega/_stock_fila.html', {
            's': fila,
            'umbral_bajo': STOCK_BAJO,
            'puede_reponer': True,
        })
    return redirect('bodega:stock')


@login_required
@require_POST
def reponer_stock(request):
    """Suma stock de un producto/variante en una tienda.

    Acceso: admin / bodeguero (no cajero). El cajero opera ventas; el
    bodeguero/dueño reponen mercadería.
    """
    if not _puede_reponer(request.user):
        messages.error(request, 'No tienes permisos para reponer stock.')
        return redirect('bodega:stock')

    tipo = request.POST.get('tipo', '')
    try:
        item_id = int(request.POST.get('item_id', 0))
        tienda_id = int(request.POST.get('tienda_id', 0))
        cantidad = int(request.POST.get('cantidad', 0))
    except (TypeError, ValueError):
        messages.error(request, 'Datos inválidos.')
        return redirect('bodega:stock')

    if cantidad <= 0:
        messages.error(request, 'La cantidad a sumar debe ser mayor a 0.')
        return redirect('bodega:stock')

    try:
        tienda = Tienda.objects.get(pk=tienda_id, activa=True)
    except Tienda.DoesNotExist:
        messages.error(request, 'Tienda no válida.')
        return redirect('bodega:stock')

    with transaction.atomic():
        if tipo == 'v':
            if not ProductoVariante.objects.filter(pk=item_id, activa=True).exists():
                messages.error(request, 'Variante no disponible.')
                return redirect('bodega:stock')
            fila, _ = StockTienda.objects.select_for_update().get_or_create(
                tienda=tienda, variante_id=item_id, defaults={'cantidad': 0},
            )
        elif tipo == 'p':
            if not Producto.objects.filter(
                pk=item_id, activo=True, tiene_variantes=False,
            ).exists():
                messages.error(request, 'Producto no disponible.')
                return redirect('bodega:stock')
            fila, _ = StockTienda.objects.select_for_update().get_or_create(
                tienda=tienda, producto_id=item_id, defaults={'cantidad': 0},
            )
        else:
            messages.error(request, 'Tipo inválido.')
            return redirect('bodega:stock')

        StockTienda.objects.filter(pk=fila.pk).update(
            cantidad=F('cantidad') + cantidad,
        )
        mov_kwargs = {
            'tienda': tienda, 'tipo': MovimientoStock.ENTRADA,
            'cantidad': cantidad, 'usuario': request.user,
            'referencia': f'Reposición por {request.user.username}',
        }
        if tipo == 'v':
            mov_kwargs['variante_id'] = item_id
        else:
            mov_kwargs['producto_id'] = item_id
        MovimientoStock.objects.create(**mov_kwargs)

    messages.success(request, f'+{cantidad} unidades agregadas al stock.')
    qs = request.META.get('HTTP_REFERER', '')
    if qs and '/bodega/' in qs:
        return redirect(qs)
    return redirect('bodega:stock')


@login_required
def stock_agregar(request):
    """Pantalla para cargar stock inicial de productos que aun no
    tienen ninguna fila en StockTienda.

    Bug que motivo la feature: tras `seed_perfumes_real` se cargaron
    43 perfumes nuevos. Como `/bodega/` lista solo filas existentes
    de StockTienda, los nuevos eran invisibles. Esta pantalla
    permite seleccionar tienda + variante (con optgroup por
    producto, alfabetico) o producto-sin-variantes y registrar la
    primera reposicion en una sola operacion.

    POST reusa `reponer_stock` via redirect interno para mantener
    la audit trail (MovimientoStock con tipo=ENTRADA).
    """
    if not _puede_reponer(request.user):
        messages.error(request, 'No tienes permisos para cargar stock.')
        return redirect('bodega:stock')

    tiendas = Tienda.objects.filter(activa=True).order_by('nombre_organizacion')

    if request.method == 'POST':
        tipo = request.POST.get('tipo', '')
        try:
            item_id = int(request.POST.get('item_id', 0))
            tienda_id = int(request.POST.get('tienda_id', 0))
            cantidad = int(request.POST.get('cantidad', 0))
        except (TypeError, ValueError):
            messages.error(request, 'Datos inválidos.')
            return redirect('bodega:stock_agregar')

        if cantidad <= 0:
            messages.error(request, 'La cantidad a sumar debe ser mayor a 0.')
            return redirect('bodega:stock_agregar')

        try:
            tienda = tiendas.get(pk=tienda_id)
        except Tienda.DoesNotExist:
            messages.error(request, 'Tienda no válida.')
            return redirect('bodega:stock_agregar')

        with transaction.atomic():
            if tipo == 'v':
                if not ProductoVariante.objects.filter(pk=item_id, activa=True).exists():
                    messages.error(request, 'Variante no disponible.')
                    return redirect('bodega:stock_agregar')
                fila, _ = StockTienda.objects.select_for_update().get_or_create(
                    tienda=tienda, variante_id=item_id, defaults={'cantidad': 0},
                )
            elif tipo == 'p':
                if not Producto.objects.filter(
                    pk=item_id, activo=True, tiene_variantes=False,
                ).exists():
                    messages.error(request, 'Producto no disponible.')
                    return redirect('bodega:stock_agregar')
                fila, _ = StockTienda.objects.select_for_update().get_or_create(
                    tienda=tienda, producto_id=item_id, defaults={'cantidad': 0},
                )
            else:
                messages.error(request, 'Tipo inválido.')
                return redirect('bodega:stock_agregar')

            StockTienda.objects.filter(pk=fila.pk).update(
                cantidad=F('cantidad') + cantidad,
            )
            mov_kwargs = {
                'tienda': tienda, 'tipo': MovimientoStock.ENTRADA,
                'cantidad': cantidad, 'usuario': request.user,
                'referencia': f'Stock inicial cargado por {request.user.username}',
            }
            if tipo == 'v':
                mov_kwargs['variante_id'] = item_id
            else:
                mov_kwargs['producto_id'] = item_id
            MovimientoStock.objects.create(**mov_kwargs)

        messages.success(
            request,
            f'+{cantidad} unidades cargadas. Seguí agregando o volvé al stock.',
        )
        # Volvemos a la misma pantalla con el form limpio para cargar
        # el siguiente producto sin tener que navegar.
        return redirect('bodega:stock_agregar')

    # GET: construir las opciones del selector.
    # Variantes activas agrupadas por producto (alfabetico).
    variantes = (
        ProductoVariante.objects
        .filter(activa=True, producto__activo=True)
        .select_related('producto', 'producto__familia')
        .prefetch_related('valores__atributo')
        .order_by('producto__familia__nombre', 'producto__nombre', 'sku')
    )
    # Productos sin variantes (tipo=p).
    productos_directos = (
        Producto.objects
        .filter(activo=True, tiene_variantes=False)
        .select_related('familia')
        .order_by('familia__nombre', 'nombre')
    )

    # Agrupar por familia para mostrar `<optgroup>` nativo (mejor UX
    # con 100+ items que un select plano).
    opciones_por_familia = {}
    for v in variantes:
        fam = v.producto.familia.nombre if v.producto.familia else 'Sin familia'
        opciones_por_familia.setdefault(fam, []).append({
            'tipo': 'v',
            'item_id': v.pk,
            'label': _label_variante(v),
            'producto_pk': v.producto.pk,
        })
    for p in productos_directos:
        fam = p.familia.nombre if p.familia else 'Sin familia'
        opciones_por_familia.setdefault(fam, []).append({
            'tipo': 'p',
            'item_id': p.pk,
            'label': f'{p.nombre} (sin variantes)',
            'producto_pk': p.pk,
        })

    return render(request, 'bodega/stock_agregar.html', {
        'tiendas': tiendas,
        'opciones_por_familia': sorted(opciones_por_familia.items()),
        'tienda_preseleccionada': tiendas.first(),
    })


@login_required
def stock_bulk_agregar(request):
    """Carga masiva de stock — admin only.

    Una sola pantalla con TODAS las variantes activas + productos sin
    variantes. Por cada uno: stock actual + input "Sumar". Submit
    procesa todas las filas con cantidad > 0 en una transaccion.

    Casos de uso:
    1. Llego un lote de 43 perfumes — agregar +X a cada uno sin
       hacer 43 operaciones individuales.
    2. Resetear / inicializar stock al empezar la temporada.
    3. "Marca con +1 todos los que no tienen stock" (quick win).

    Permisos: solo admin/superuser. Mucho poder en una operacion.
    """
    if not _puede_gestionar_ofertas(request.user):
        messages.error(request, 'Solo administradores pueden hacer cargas masivas.')
        return redirect('bodega:stock')

    tiendas = Tienda.objects.filter(activa=True).order_by('nombre_organizacion')

    if request.method == 'POST':
        try:
            tienda_id = int(request.POST.get('tienda_id', 0))
        except (TypeError, ValueError):
            messages.error(request, 'Tienda inválida.')
            return redirect('bodega:stock_bulk_agregar')
        try:
            tienda = tiendas.get(pk=tienda_id)
        except Tienda.DoesNotExist:
            messages.error(request, 'Tienda no válida.')
            return redirect('bodega:stock_bulk_agregar')

        # Recoger filas del POST: claves `qty_v_<id>` o `qty_p_<id>`.
        actualizaciones = []  # [(tipo, item_id, cantidad), ...]
        for key, raw in request.POST.items():
            if not (key.startswith('qty_v_') or key.startswith('qty_p_')):
                continue
            try:
                cantidad = int(raw)
            except (TypeError, ValueError):
                continue
            if cantidad <= 0:
                continue
            tipo = 'v' if key.startswith('qty_v_') else 'p'
            try:
                item_id = int(key.split('_')[-1])
            except (TypeError, ValueError):
                continue
            actualizaciones.append((tipo, item_id, cantidad))

        if not actualizaciones:
            messages.warning(
                request,
                'No ingresaste ninguna cantidad mayor a 0. Completa al menos un input.',
            )
            return redirect('bodega:stock_bulk_agregar')

        # Cap defensivo: nunca procesar mas de 500 filas en un POST.
        if len(actualizaciones) > 500:
            messages.error(request, 'Demasiadas filas — limite 500 por carga.')
            return redirect('bodega:stock_bulk_agregar')

        creadas, actualizadas_count, ignoradas = 0, 0, 0
        with transaction.atomic():
            for tipo, item_id, cantidad in actualizaciones:
                if tipo == 'v':
                    if not ProductoVariante.objects.filter(
                        pk=item_id, activa=True,
                    ).exists():
                        ignoradas += 1
                        continue
                    fila, creada = StockTienda.objects.select_for_update().get_or_create(
                        tienda=tienda, variante_id=item_id, defaults={'cantidad': 0},
                    )
                else:
                    if not Producto.objects.filter(
                        pk=item_id, activo=True, tiene_variantes=False,
                    ).exists():
                        ignoradas += 1
                        continue
                    fila, creada = StockTienda.objects.select_for_update().get_or_create(
                        tienda=tienda, producto_id=item_id, defaults={'cantidad': 0},
                    )
                StockTienda.objects.filter(pk=fila.pk).update(
                    cantidad=F('cantidad') + cantidad,
                )
                mov_kwargs = {
                    'tienda': tienda, 'tipo': MovimientoStock.ENTRADA,
                    'cantidad': cantidad, 'usuario': request.user,
                    'referencia': f'Carga masiva por {request.user.username}',
                }
                if tipo == 'v':
                    mov_kwargs['variante_id'] = item_id
                else:
                    mov_kwargs['producto_id'] = item_id
                MovimientoStock.objects.create(**mov_kwargs)
                if creada:
                    creadas += 1
                else:
                    actualizadas_count += 1

        msg = (
            f'Carga masiva: {creadas} producto(s) sin stock inicializado(s), '
            f'{actualizadas_count} sumado(s) a stock existente'
        )
        if ignoradas:
            msg += f', {ignoradas} ignorado(s) (inactivos)'
        msg += '.'
        messages.success(request, msg)
        return redirect('bodega:stock_bulk_agregar')

    # GET — construir el grid.
    tienda_seleccionada = tiendas.first()
    if request.GET.get('tienda', '').isdigit():
        tid = int(request.GET['tienda'])
        sel = tiendas.filter(pk=tid).first()
        if sel:
            tienda_seleccionada = sel

    solo_sin_stock = request.GET.get('solo_sin_stock') == '1'

    variantes = (
        ProductoVariante.objects
        .filter(activa=True, producto__activo=True)
        .select_related('producto', 'producto__familia')
        .prefetch_related('valores__atributo')
        .order_by('producto__familia__nombre', 'producto__nombre', 'sku')
    )
    productos_directos = (
        Producto.objects
        .filter(activo=True, tiene_variantes=False)
        .select_related('familia')
        .order_by('familia__nombre', 'nombre')
    )

    # Mapear stock actual por (tipo, id) en la tienda seleccionada.
    stocks_v = {
        s.variante_id: s.cantidad
        for s in StockTienda.objects.filter(
            tienda=tienda_seleccionada, variante__isnull=False,
        )
    }
    stocks_p = {
        s.producto_id: s.cantidad
        for s in StockTienda.objects.filter(
            tienda=tienda_seleccionada, producto__isnull=False,
        )
    }

    filas_por_familia = {}
    for v in variantes:
        stock = stocks_v.get(v.pk, 0)
        if solo_sin_stock and stock > 0:
            continue
        fam = v.producto.familia.nombre if v.producto.familia else 'Sin familia'
        filas_por_familia.setdefault(fam, []).append({
            'tipo': 'v',
            'item_id': v.pk,
            'label': _label_variante(v),
            'stock_actual': stock,
            'qty_name': f'qty_v_{v.pk}',
        })
    for p in productos_directos:
        stock = stocks_p.get(p.pk, 0)
        if solo_sin_stock and stock > 0:
            continue
        fam = p.familia.nombre if p.familia else 'Sin familia'
        filas_por_familia.setdefault(fam, []).append({
            'tipo': 'p',
            'item_id': p.pk,
            'label': f'{p.nombre} (sin variantes)',
            'stock_actual': stock,
            'qty_name': f'qty_p_{p.pk}',
        })

    total_filas = sum(len(items) for items in filas_por_familia.values())
    total_sin_stock = sum(
        1 for items in filas_por_familia.values() for it in items
        if it['stock_actual'] == 0
    )

    return render(request, 'bodega/stock_bulk_agregar.html', {
        'tiendas': tiendas,
        'tienda_seleccionada': tienda_seleccionada,
        'filas_por_familia': sorted(filas_por_familia.items()),
        'total_filas': total_filas,
        'total_sin_stock': total_sin_stock,
        'solo_sin_stock': solo_sin_stock,
    })


def _label_variante(v):
    """Etiqueta legible para una variante en el selector — incluye
    nombre del producto + valores de atributos + SKU."""
    valores = ' · '.join(
        f'{val.atributo.nombre}: {val.valor}'
        for val in v.valores.all()
    )
    if valores:
        return f'{v.producto.nombre} — {valores} ({v.sku})'
    return f'{v.producto.nombre} ({v.sku})'


# ============================================================================
# CRUD de productos desde la pantalla de bodega (Fase Ñ)
# ============================================================================

reponer_required = user_passes_test(_puede_reponer, login_url='login')


@login_required
@reponer_required
def lista_productos(request):
    """Listado de productos con filtros para gestión rápida."""
    qs = (
        Producto.objects.all()
        .select_related('familia', 'colegio')
        .annotate(n_variantes=Count('variantes'))
    )
    q = (request.GET.get('q') or '').strip()
    familia_id = (request.GET.get('familia') or '').strip()
    colegio_id = (request.GET.get('colegio') or '').strip()
    estado = (request.GET.get('estado') or '').strip()

    if q:
        from edTech.search import normalize_text
        q_norm = normalize_text(q)
        qs = qs.filter(
            Q(nombre_buscable__contains=q_norm)
            | Q(descripcion_buscable__contains=q_norm)
        )
    if familia_id.isdigit():
        qs = qs.filter(familia_id=int(familia_id))
    if colegio_id.isdigit():
        qs = qs.filter(colegio_id=int(colegio_id))
    if estado == 'activos':
        qs = qs.filter(activo=True)
    elif estado == 'inactivos':
        qs = qs.filter(activo=False)

    contexto = {
        'productos': qs.order_by('familia__nombre', 'nombre'),
        'familias': Familia.objects.order_by('nombre'),
        'colegios': Colegio.objects.filter(activo=True).order_by('nombre'),
        'filtros': {
            'q': q, 'familia': familia_id, 'colegio': colegio_id, 'estado': estado,
        },
        # La edicion inline de precio + toggle de `activo` son solo
        # para admin / superuser. El bodeguero ve pero no modifica
        # (es decision comercial, no de stock).
        'puede_editar_precio': _puede_gestionar_ofertas(request.user),
        'puede_editar_activo': _puede_gestionar_ofertas(request.user),
    }
    # Filtros AJAX: si la request es HTMX, devolvemos solo la tabla.
    if request.htmx:
        return render(request, 'bodega/_productos_lista_tabla.html', contexto)
    return render(request, 'bodega/productos_lista.html', contexto)


@login_required
@require_POST
def set_precio(request, pk):
    """Edicion inline del precio_base de un producto desde el listado.

    Solo admin / superuser (es un cambio comercial; el bodeguero
    gestiona stock, no precios). Recibe `precio_base` como string,
    valida que sea decimal positivo, persiste y devuelve la celda
    actualizada (para HTMX) o redirige (no-JS).
    """
    if not _puede_gestionar_ofertas(request.user):
        messages.error(request, 'No tienes permisos para editar precios.')
        return redirect('bodega:lista_productos')

    producto = get_object_or_404(Producto, pk=pk)

    try:
        nuevo = Decimal(str(request.POST.get('precio_base', '')).replace(',', '.').strip())
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, 'Precio inválido.')
        return _respuesta_precio(request, producto)

    if nuevo < 0:
        messages.error(request, 'El precio no puede ser negativo.')
        return _respuesta_precio(request, producto)
    if nuevo > Decimal('99999999.99'):
        messages.error(request, 'Precio fuera de rango.')
        return _respuesta_precio(request, producto)

    producto.precio_base = nuevo
    producto.save(update_fields=['precio_base', 'modificado'])
    messages.success(request, f'Precio actualizado: ${nuevo:,.0f}'.replace(',', '.'))
    return _respuesta_precio(request, producto)


def _respuesta_precio(request, producto):
    """HTMX: celda actualizada (inline edit). No-JS: redirect."""
    if request.htmx:
        # Solo admin/superuser llega aca (el require_POST + el if
        # de set_precio ya filtra), asi `puede_editar_precio` siempre
        # es True — pero lo dejamos explicito para el template.
        return render(request, 'bodega/_producto_precio_celda.html', {
            'p': producto,
            'puede_editar_precio': True,
        })
    return redirect('bodega:lista_productos')


@login_required
@require_POST
def productos_bulk_action(request):
    """Aplica una accion en bulk a varios productos seleccionados.

    Bloque 11: complemento del toggle individual — permite cambiar
    el estado de 5/10/20 productos a la vez desde la lista, sin
    tener que clickear uno por uno. Util cuando entra una temporada
    o se discontinua una linea completa.

    Body:
        - accion: 'activar' | 'desactivar'
        - ids: lista de PKs (multivalued)

    Respuesta:
    - HTMX: tabla refrescada con los nuevos estados (re-aplica los
      filtros vigentes del querystring).
    - No-JS: redirect a lista_productos con messages.success.
    """
    if not _puede_gestionar_ofertas(request.user):
        messages.error(request, 'No tienes permisos para cambios masivos.')
        return redirect('bodega:lista_productos')

    accion = (request.POST.get('accion') or '').strip()
    ids = [int(x) for x in request.POST.getlist('ids') if x.isdigit()]

    if accion not in ('activar', 'desactivar'):
        messages.error(request, 'Acción inválida.')
        return redirect('bodega:lista_productos')
    if not ids:
        messages.error(request, 'No seleccionaste ningún producto.')
        return redirect('bodega:lista_productos')

    from django.utils import timezone
    nuevo_estado = (accion == 'activar')
    qs = Producto.objects.filter(pk__in=ids)
    actualizados = qs.update(activo=nuevo_estado, modificado=timezone.now())

    verbo = 'activados' if nuevo_estado else 'desactivados'
    messages.success(request, f'{actualizados} producto(s) {verbo}.')

    # Si fue HTMX, re-renderizamos la tabla preservando los filtros
    # actuales (que el form de bulk envia via hidden inputs).
    if request.htmx:
        # Simulamos los GET params que `lista_productos` espera.
        request.GET = request.POST
        return lista_productos(request)
    return redirect('bodega:lista_productos')


@login_required
@require_POST
def producto_toggle_activo(request, pk):
    """Toggle del campo `activo` desde la lista de productos.

    Bloque 10: misma logica que `set_precio` y `oferta_toggle`, pero
    para activar/desactivar productos sin entrar al form completo.
    Solo admin/superuser (es decision comercial — el bodeguero NO
    discontinua productos).
    """
    if not _puede_gestionar_ofertas(request.user):
        messages.error(request, 'No tienes permisos para cambiar el estado de productos.')
        return redirect('bodega:lista_productos')

    producto = get_object_or_404(Producto, pk=pk)
    producto.activo = not producto.activo
    producto.save(update_fields=['activo', 'modificado'])
    estado = 'activado' if producto.activo else 'desactivado'
    messages.success(request, f'Producto "{producto.nombre}" {estado}.')
    return _respuesta_activo(request, producto)


def _respuesta_activo(request, producto):
    """HTMX: celda actualizada con el nuevo badge + form. No-JS: redirect."""
    if request.htmx:
        return render(request, 'bodega/_producto_activo_celda.html', {
            'p': producto,
            'puede_editar_activo': True,
        })
    return redirect('bodega:lista_productos')


@login_required
@reponer_required
def producto_nuevo(request):
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES)
        if form.is_valid():
            p = form.save()
            messages.success(request, f'Producto "{p.nombre}" creado.')
            if p.tiene_variantes:
                return redirect('bodega:variantes', pk=p.pk)
            return redirect('bodega:lista_productos')
    else:
        form = ProductoForm(initial={'activo': True})
    return render(request, 'bodega/producto_form.html', {
        'form': form, 'modo': 'crear',
        'titulo': 'Nuevo producto',
    })


@login_required
@reponer_required
def producto_editar(request, pk):
    from django.utils import timezone

    p = get_object_or_404(Producto, pk=pk)
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES, instance=p)
        if form.is_valid():
            form.save()
            messages.success(request, f'Producto "{p.nombre}" actualizado.')
            return redirect('bodega:lista_productos')
    else:
        form = ProductoForm(instance=p)

    # Ofertas que afectan a este producto: ya sea directas (Oferta.producto)
    # o vía variante (Oferta.variante.producto). Solo se muestran a quien
    # ya tiene permisos para ver/cambiar ofertas — no es información que
    # un bodeguero de stock necesite ver.
    ofertas = []
    if _puede_gestionar_ofertas(request.user):
        ahora = timezone.now()
        ofertas_qs = (
            Oferta.objects
            .filter(Q(producto=p) | Q(variante__producto=p))
            .select_related('producto', 'variante', 'variante__producto')
            .order_by('-fecha_inicio')
        )
        for o in ofertas_qs:
            o.estado_visual = _estado_oferta(o, ahora)
            ofertas.append(o)

    # Variantes del producto, con sus valores precargados para evitar
    # N+1 al renderizar cada fila.
    variantes = list(
        p.variantes.all()
        .prefetch_related('valores__atributo')
        .order_by('-activa', 'sku')
    )

    return render(request, 'bodega/producto_form.html', {
        'form': form, 'modo': 'editar', 'producto': p,
        'titulo': f'Editar — {p.nombre}',
        'ofertas': ofertas,
        'variantes': variantes,
        'puede_gestionar_ofertas': _puede_gestionar_ofertas(request.user),
    })


@login_required
@reponer_required
def galeria_producto(request, pk):
    """Pantalla de gestion de galeria de imagenes adicionales (Bloque 8).

    Bloque 15: la imagen principal (`Producto.imagen`) se gestiona en
    el form de editar producto. Aca solo las imagenes adicionales que
    aparecen como thumbs en el PDP. Se pueden reordenar via drag-drop
    (admin) y borrar (bodeguero + admin).
    """
    from catalogo.models import ProductoImagen
    p = get_object_or_404(Producto, pk=pk)
    imagenes = list(p.imagenes.all())
    return render(request, 'bodega/galeria_producto.html', {
        'producto': p,
        'imagenes': imagenes,
        'puede_reordenar': _puede_gestionar_ofertas(request.user),
    })


@login_required
@require_POST
def galeria_reorder(request, pk):
    """Recibe el nuevo orden de imagenes de la galeria.

    Body: `orden_ids` = lista de PKs separadas por coma, en el orden
    nuevo. Ej: "12,15,8,3" → imagen 12 con orden=0, etc.

    Defensa: verifica que todos los IDs pertenecen al producto antes
    de actualizar (evita reorder cross-producto via POST forjado).
    """
    if not _puede_gestionar_ofertas(request.user):
        if request.htmx:
            return HttpResponse('Sin permisos', status=403)
        messages.error(request, 'No tienes permisos para reordenar la galería.')
        return redirect('bodega:galeria_producto', pk=pk)

    from catalogo.models import ProductoImagen
    producto = get_object_or_404(Producto, pk=pk)
    raw = (request.POST.get('orden_ids') or '').strip()
    if not raw:
        return HttpResponse('Sin orden recibido', status=400) if request.htmx \
            else redirect('bodega:galeria_producto', pk=pk)

    try:
        ids = [int(x) for x in raw.split(',') if x.strip()]
    except ValueError:
        return HttpResponse('IDs invalidos', status=400) if request.htmx \
            else redirect('bodega:galeria_producto', pk=pk)

    imgs = {i.pk: i for i in producto.imagenes.all()}
    if set(ids) - set(imgs.keys()):
        return HttpResponse('IDs ajenos al producto', status=400) if request.htmx \
            else redirect('bodega:galeria_producto', pk=pk)

    actualizadas = []
    for idx, img_id in enumerate(ids):
        img = imgs[img_id]
        if img.orden != idx:
            img.orden = idx
            actualizadas.append(img)
    if actualizadas:
        ProductoImagen.objects.bulk_update(actualizadas, ['orden'])

    if request.htmx:
        return HttpResponse(f'OK · {len(actualizadas)}', status=200)
    messages.success(
        request, f'Galería reordenada · {len(actualizadas)} imagen(es) actualizada(s).',
    )
    return redirect('bodega:galeria_producto', pk=pk)


@login_required
@require_POST
def galeria_borrar(request, pk, img_pk):
    """Borra una imagen de la galeria. Bodeguero + admin pueden."""
    from catalogo.models import ProductoImagen
    producto = get_object_or_404(Producto, pk=pk)
    img = get_object_or_404(ProductoImagen, pk=img_pk, producto=producto)
    img.delete()
    messages.success(request, 'Imagen eliminada de la galería.')
    return redirect('bodega:galeria_producto', pk=pk)


@login_required
@reponer_required
def variantes_lista(request, pk):
    """Lista las variantes de un producto con filtros AJAX.

    Bloque 16: filtros sobre SKU/valor + estado (activas/inactivas).
    Patron HTMX igual que productos/ofertas/materiales — input
    'Buscar' con debounce 300ms refresca solo la tabla.
    """
    p = get_object_or_404(Producto, pk=pk)
    qs = p.variantes.all().prefetch_related('valores__atributo')

    q = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()

    if q:
        # Busca en SKU + en valores de atributos (talla "10", color "rojo", etc).
        qs = qs.filter(
            Q(sku__icontains=q) | Q(valores__valor__icontains=q)
        ).distinct()
    if estado == 'activas':
        qs = qs.filter(activa=True)
    elif estado == 'inactivas':
        qs = qs.filter(activa=False)

    variantes = qs.order_by('sku')
    contexto = {
        'producto': p,
        'variantes': variantes,
        'filtros': {'q': q, 'estado': estado},
        'total_filtradas': variantes.count(),
        'total_producto': p.variantes.count(),
    }
    if request.htmx:
        return render(request, 'bodega/_variantes_lista_tabla.html', contexto)
    return render(request, 'bodega/variantes_lista.html', contexto)


@login_required
@reponer_required
def variante_nueva(request, pk):
    p = get_object_or_404(Producto, pk=pk)
    if request.method == 'POST':
        form = ProductoVarianteForm(request.POST)
        if form.is_valid():
            v = form.save(producto=p)
            messages.success(request, f'Variante {v.sku} creada.')
            return redirect('bodega:variantes', pk=p.pk)
    else:
        form = ProductoVarianteForm()
    return render(request, 'bodega/variante_form.html', {
        'form': form, 'producto': p, 'modo': 'crear',
        'titulo': f'Nueva variante de {p.nombre}',
    })


@login_required
@reponer_required
def variante_editar(request, pk, var_pk):
    p = get_object_or_404(Producto, pk=pk)
    v = get_object_or_404(ProductoVariante, pk=var_pk, producto=p)
    if request.method == 'POST':
        form = ProductoVarianteForm(request.POST, instance=v)
        if form.is_valid():
            form.save(producto=p)
            messages.success(request, f'Variante {v.sku} actualizada.')
            return redirect('bodega:variantes', pk=p.pk)
    else:
        form = ProductoVarianteForm(instance=v)
    return render(request, 'bodega/variante_form.html', {
        'form': form, 'producto': p, 'modo': 'editar', 'variante': v,
        'titulo': f'Editar variante {v.sku}',
    })


@login_required
@reponer_required
@require_POST
def variante_borrar(request, pk, var_pk):
    """Borra (o desactiva si tiene movimientos asociados) una variante."""
    p = get_object_or_404(Producto, pk=pk)
    v = get_object_or_404(ProductoVariante, pk=var_pk, producto=p)
    # Si tiene stock o movimientos, desactivamos en lugar de borrar para no
    # romper integridad histórica.
    tiene_historia = (
        v.stock_tienda.exists() or v.movimientostock_set.exists() if hasattr(v, 'movimientostock_set') else False
    )
    if v.stock_tienda.exists():
        v.activa = False
        v.save(update_fields=['activa'])
        messages.warning(request, f'{v.sku} tiene stock — se marcó como inactiva en lugar de borrar.')
    else:
        nombre = v.sku
        v.delete()
        messages.success(request, f'Variante {nombre} eliminada.')
    return redirect('bodega:variantes', pk=p.pk)


# ============================================================================
# CRUD de materiales y rendimientos (Fase Ñ.2)
# ============================================================================

@login_required
@reponer_required
def lista_materiales(request):
    """Listado de materiales con stock total, costo y rendimientos."""
    qs = (
        Material.objects.all()
        .select_related('proveedor')
        .annotate(
            stock_total=Coalesce(Sum('stock_bodegas__cantidad'), 0),
            n_rendimientos=Count('rendimientos', distinct=True),
        )
    )
    q = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()
    if q:
        from edTech.search import normalize_text
        q_norm = normalize_text(q)
        # Material no tiene descripcion_buscable porque es CharField corto;
        # buscamos por nombre_buscable y por descripción case-insensitive.
        qs = qs.filter(
            Q(nombre_buscable__contains=q_norm)
            | Q(descripcion__icontains=q)
        )
    if estado == 'activos':
        qs = qs.filter(activo=True)
    elif estado == 'inactivos':
        qs = qs.filter(activo=False)
    contexto = {
        'materiales': qs.order_by('nombre'),
        'filtros': {'q': q, 'estado': estado},
        # Bloque 14: bulk action — bodeguero y admin pueden.
        'puede_bulk_materiales': _puede_reponer(request.user),
    }
    if request.htmx:
        return render(request, 'bodega/_materiales_lista_tabla.html', contexto)
    return render(request, 'bodega/materiales_lista.html', contexto)


@login_required
@reponer_required
@require_POST
def materiales_bulk_action(request):
    """Bulk action para materiales: activar/desactivar varios a la vez.

    Bloque 14. Permisos: bodeguero + admin (mismo que el resto del
    CRUD de materiales).
    """
    from django.utils import timezone

    accion = (request.POST.get('accion') or '').strip()
    ids = [int(x) for x in request.POST.getlist('ids') if x.isdigit()]

    if accion not in ('activar', 'desactivar'):
        messages.error(request, 'Acción inválida.')
        return redirect('bodega:lista_materiales')
    if not ids:
        messages.error(request, 'No seleccionaste ningún material.')
        return redirect('bodega:lista_materiales')

    nuevo_activo = (accion == 'activar')
    actualizados = (
        Material.objects.filter(pk__in=ids)
        .update(activo=nuevo_activo, modificado=timezone.now())
    )
    verbo = 'activados' if nuevo_activo else 'desactivados'
    messages.success(request, f'{actualizados} material(es) {verbo}.')

    if request.htmx:
        request.GET = request.POST
        return lista_materiales(request)
    return redirect('bodega:lista_materiales')


@login_required
@reponer_required
def material_nuevo(request):
    if request.method == 'POST':
        form = MaterialForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, f'Material "{m.nombre}" creado.')
            return redirect('bodega:lista_materiales')
    else:
        form = MaterialForm(initial={'activo': True})
    return render(request, 'bodega/material_form.html', {
        'form': form, 'modo': 'crear',
        'titulo': 'Nuevo material',
    })


@login_required
@reponer_required
def material_editar(request, pk):
    m = get_object_or_404(Material, pk=pk)
    if request.method == 'POST':
        form = MaterialForm(request.POST, instance=m)
        if form.is_valid():
            form.save()
            messages.success(request, f'Material "{m.nombre}" actualizado.')
            return redirect('bodega:lista_materiales')
    else:
        form = MaterialForm(instance=m)
    return render(request, 'bodega/material_form.html', {
        'form': form, 'modo': 'editar', 'material': m,
        'titulo': f'Editar — {m.nombre}',
    })


@login_required
@reponer_required
def rendimientos_lista(request, pk):
    """Lista los rendimientos de un material (qué variantes y cuántas u/rollo)."""
    m = get_object_or_404(Material, pk=pk)
    rendimientos = (
        m.rendimientos.all()
        .select_related('variante__producto', 'variante__producto__colegio')
        .prefetch_related('variante__valores__atributo')
        .order_by('variante__producto__nombre', 'variante__sku')
    )
    return render(request, 'bodega/rendimientos_lista.html', {
        'material': m,
        'rendimientos': rendimientos,
    })


@login_required
@reponer_required
def rendimiento_nuevo(request, pk):
    m = get_object_or_404(Material, pk=pk)
    if request.method == 'POST':
        form = RendimientoForm(request.POST, material=m)
        if form.is_valid():
            r = form.save()
            messages.success(request, f'Rendimiento agregado: {r.unidades_por_rollo} u/rollo.')
            return redirect('bodega:rendimientos', pk=m.pk)
    else:
        form = RendimientoForm(material=m)
    return render(request, 'bodega/rendimiento_form.html', {
        'form': form, 'material': m, 'modo': 'crear',
        'titulo': f'Nuevo rendimiento de {m.nombre}',
    })


@login_required
@reponer_required
def rendimiento_editar(request, pk, rend_pk):
    m = get_object_or_404(Material, pk=pk)
    r = get_object_or_404(Rendimiento, pk=rend_pk, material=m)
    if request.method == 'POST':
        form = RendimientoForm(request.POST, instance=r, material=m)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rendimiento actualizado.')
            return redirect('bodega:rendimientos', pk=m.pk)
    else:
        form = RendimientoForm(instance=r, material=m)
    return render(request, 'bodega/rendimiento_form.html', {
        'form': form, 'material': m, 'modo': 'editar', 'rendimiento': r,
        'titulo': 'Editar rendimiento',
    })


@login_required
@reponer_required
@require_POST
def rendimiento_borrar(request, pk, rend_pk):
    m = get_object_or_404(Material, pk=pk)
    r = get_object_or_404(Rendimiento, pk=rend_pk, material=m)
    r.delete()
    messages.success(request, 'Rendimiento eliminado.')
    return redirect('bodega:rendimientos', pk=m.pk)


# ============================================================================
# CRUD de ofertas (Fase O.1)
# ============================================================================

ofertas_required = user_passes_test(_puede_gestionar_ofertas, login_url='login')


def _estado_oferta(oferta, ahora):
    """Calcula el estado visible de una oferta para el badge."""
    if not oferta.activa:
        return 'pausada'
    if oferta.fecha_fin < ahora:
        return 'vencida'
    if oferta.fecha_inicio > ahora:
        return 'programada'
    return 'vigente'


@login_required
@ofertas_required
def lista_ofertas(request):
    """Listado de ofertas con filtros por estado / canal / búsqueda libre."""
    from django.utils import timezone
    ahora = timezone.now()

    qs = (
        Oferta.objects
        .select_related('producto', 'producto__familia',
                        'variante', 'variante__producto')
    )

    q = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()
    canal = (request.GET.get('canal') or '').strip()

    if q:
        qs = qs.filter(
            Q(nombre__icontains=q)
            | Q(producto__nombre__icontains=q)
            | Q(variante__sku__icontains=q)
            | Q(variante__producto__nombre__icontains=q)
        )
    if canal in (Oferta.CANAL_PRESENCIAL, Oferta.CANAL_ONLINE, Oferta.CANAL_AMBOS):
        qs = qs.filter(canal=canal)
    if estado == 'vigentes':
        qs = qs.filter(activa=True, fecha_inicio__lte=ahora, fecha_fin__gte=ahora)
    elif estado == 'programadas':
        qs = qs.filter(activa=True, fecha_inicio__gt=ahora)
    elif estado == 'vencidas':
        qs = qs.filter(fecha_fin__lt=ahora)
    elif estado == 'pausadas':
        qs = qs.filter(activa=False)

    ofertas = []
    for o in qs.order_by('-fecha_inicio'):
        o.estado_visual = _estado_oferta(o, ahora)
        ofertas.append(o)

    contexto = {
        'ofertas': ofertas,
        'filtros': {'q': q, 'estado': estado, 'canal': canal},
        'canal_choices': Oferta.CANAL_CHOICES,
        # Bloque 13: bulk action solo para admin (mismo helper que
        # toggle individual). El bodeguero NO ve la columna de check.
        'puede_bulk_ofertas': _puede_gestionar_ofertas(request.user),
    }
    if request.htmx:
        return render(request, 'bodega/_ofertas_lista_tabla.html', contexto)
    return render(request, 'bodega/ofertas_lista.html', contexto)


@login_required
@ofertas_required
def oferta_nueva(request):
    if request.method == 'POST':
        form = OfertaForm(request.POST)
        if form.is_valid():
            o = form.save()
            messages.success(request, f'Oferta "{o.nombre}" creada.')
            return redirect('bodega:lista_ofertas')
    else:
        # Permite que la pantalla de editar producto enlace a
        # `?producto=<pk>` y caigamos con el producto pre-seleccionado.
        initial = {
            'activa': True,
            'canal': Oferta.CANAL_AMBOS,
            'tipo': Oferta.TIPO_PORCENTAJE,
        }
        producto_pk = (request.GET.get('producto') or '').strip()
        if producto_pk.isdigit():
            if Producto.objects.filter(pk=producto_pk, activo=True).exists():
                initial['producto'] = int(producto_pk)
        form = OfertaForm(initial=initial)
    return render(request, 'bodega/oferta_form.html', {
        'form': form, 'modo': 'crear',
        'titulo': 'Nueva oferta',
    })


@login_required
@ofertas_required
def oferta_editar(request, pk):
    o = get_object_or_404(Oferta, pk=pk)
    if request.method == 'POST':
        form = OfertaForm(request.POST, instance=o)
        if form.is_valid():
            form.save()
            messages.success(request, f'Oferta "{o.nombre}" actualizada.')
            return redirect('bodega:lista_ofertas')
    else:
        form = OfertaForm(instance=o)
    return render(request, 'bodega/oferta_form.html', {
        'form': form, 'modo': 'editar', 'oferta': o,
        'titulo': f'Editar — {o.nombre}',
    })


@login_required
@ofertas_required
@require_POST
def oferta_borrar(request, pk):
    o = get_object_or_404(Oferta, pk=pk)
    nombre = o.nombre
    o.delete()
    messages.success(request, f'Oferta "{nombre}" eliminada.')
    return redirect('bodega:lista_ofertas')


@login_required
@ofertas_required
@require_POST
@login_required
@ofertas_required
@require_POST
def ofertas_bulk_action(request):
    """Bulk action para ofertas: pausar / reactivar varias a la vez.

    Bloque 13: mismo patron que `productos_bulk_action`. Solo admin /
    superuser (decorator `@ofertas_required`).

    Body:
      - accion: 'pausar' | 'reactivar'
      - ids: lista de PKs (multivalued)
    """
    from django.utils import timezone

    accion = (request.POST.get('accion') or '').strip()
    ids = [int(x) for x in request.POST.getlist('ids') if x.isdigit()]

    if accion not in ('pausar', 'reactivar'):
        messages.error(request, 'Acción inválida.')
        return redirect('bodega:lista_ofertas')
    if not ids:
        messages.error(request, 'No seleccionaste ninguna oferta.')
        return redirect('bodega:lista_ofertas')

    nueva_activa = (accion == 'reactivar')
    actualizadas = (
        Oferta.objects.filter(pk__in=ids)
        .update(activa=nueva_activa, modificado=timezone.now())
    )
    verbo = 'reactivadas' if nueva_activa else 'pausadas'
    messages.success(request, f'{actualizadas} oferta(s) {verbo}.')

    if request.htmx:
        request.GET = request.POST
        return lista_ofertas(request)
    return redirect('bodega:lista_ofertas')


def oferta_toggle(request, pk):
    """Pausa o reactiva una oferta sin tener que entrar al form."""
    o = get_object_or_404(Oferta, pk=pk)
    o.activa = not o.activa
    o.save(update_fields=['activa', 'modificado'])
    messages.success(
        request,
        f'Oferta "{o.nombre}" {"reactivada" if o.activa else "pausada"}.',
    )
    return redirect('bodega:lista_ofertas')


# ============================================================================
# Etiquetas imprimibles con código de barras
# ============================================================================

@login_required
@reponer_required
def etiquetas_seleccionar(request):
    """Pantalla con filtros + checkboxes para elegir qué items y cuántas
    etiquetas imprimir.

    Lista variantes activas y productos sin variantes con stock > 0 en
    cualquier tienda. El bodeguero filtra por familia/colegio, elige
    cuántas copias de cada uno, y dispara la vista imprimible."""
    familia_id = (request.GET.get('familia') or '').strip()
    colegio_id = (request.GET.get('colegio') or '').strip()
    q = (request.GET.get('q') or '').strip()

    productos_qs = Producto.objects.filter(
        activo=True, tiene_variantes=False,
    ).select_related('familia', 'colegio')

    variantes_qs = (
        ProductoVariante.objects.filter(
            activa=True, producto__activo=True, producto__tiene_variantes=True,
        )
        .select_related('producto__familia', 'producto__colegio')
        .prefetch_related('valores__atributo')
    )

    if familia_id.isdigit():
        productos_qs = productos_qs.filter(familia_id=int(familia_id))
        variantes_qs = variantes_qs.filter(producto__familia_id=int(familia_id))
    if colegio_id.isdigit():
        productos_qs = productos_qs.filter(colegio_id=int(colegio_id))
        variantes_qs = variantes_qs.filter(producto__colegio_id=int(colegio_id))
    if q:
        from edTech.search import normalize_text
        q_norm = normalize_text(q)
        productos_qs = productos_qs.filter(nombre_buscable__contains=q_norm)
        variantes_qs = variantes_qs.filter(
            Q(producto__nombre_buscable__contains=q_norm)
            | Q(sku__icontains=q),
        )

    return render(request, 'bodega/etiquetas_seleccionar.html', {
        'productos': productos_qs.order_by('familia__nombre', 'nombre'),
        'variantes': variantes_qs.order_by('producto__nombre', 'sku'),
        'familias': Familia.objects.order_by('nombre'),
        'colegios': Colegio.objects.filter(activo=True).order_by('nombre'),
        'filtros': {'familia': familia_id, 'colegio': colegio_id, 'q': q},
    })


@login_required
@reponer_required
@require_POST
def etiquetas_imprimir(request):
    """Renderiza la vista imprimible con los códigos seleccionados.

    POST recibe pares `p_<pk>=N` y `v_<pk>=N` donde N es la cantidad de
    etiquetas a imprimir de ese item. La página resultante usa CSS
    @page A4 y un grid de 30 etiquetas (3 cols x 10 filas), compatible
    con plantillas Avery L7651 / similar.
    """
    from catalogo.barcode import render_svg_ean13

    items = []  # list de dicts {nombre, variante_txt, precio, codigo, svg}

    for key, valor in request.POST.items():
        if not valor or not valor.isdigit() or int(valor) < 1:
            continue
        copias = min(int(valor), 99)  # tope de seguridad

        if key.startswith('p_'):
            try:
                pk = int(key[2:])
            except ValueError:
                continue
            try:
                p = Producto.objects.select_related('familia').get(
                    pk=pk, activo=True, tiene_variantes=False,
                )
            except Producto.DoesNotExist:
                continue
            if not p.codigo_barras:
                continue
            etiqueta = {
                'nombre': p.nombre,
                'variante_txt': '',
                'precio': p.precio_base,
                'codigo': p.codigo_barras,
                'svg': render_svg_ean13(p.codigo_barras),
            }
            for _ in range(copias):
                items.append(etiqueta)

        elif key.startswith('v_'):
            try:
                pk = int(key[2:])
            except ValueError:
                continue
            try:
                v = ProductoVariante.objects.select_related(
                    'producto__familia',
                ).prefetch_related('valores__atributo').get(
                    pk=pk, activa=True, producto__activo=True,
                )
            except ProductoVariante.DoesNotExist:
                continue
            if not v.codigo_barras:
                continue
            valores_txt = ' · '.join(
                str(val.valor) for val in v.valores.all()
            )
            etiqueta = {
                'nombre': v.producto.nombre,
                'variante_txt': valores_txt or v.sku,
                'precio': v.precio,
                'codigo': v.codigo_barras,
                'svg': render_svg_ean13(v.codigo_barras),
            }
            for _ in range(copias):
                items.append(etiqueta)

    if not items:
        messages.error(request, 'Seleccioná al menos un item con cantidad > 0.')
        return redirect('bodega:etiquetas_seleccionar')

    # Agrupamos las etiquetas en hojas de 30 (3 cols × 10 filas) para que
    # cada hoja sea su propia pagina con page-break controlado por CSS.
    POR_HOJA = 30
    hojas = [items[i:i + POR_HOJA] for i in range(0, len(items), POR_HOJA)]

    return render(request, 'bodega/etiquetas_imprimir.html', {
        'hojas': hojas,
        'total': len(items),
        'total_hojas': len(hojas),
    })
