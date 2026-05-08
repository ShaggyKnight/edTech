"""Vistas de bodega: stock por tienda + CRUD de catálogo desde el backoffice.

La intención es que el bodeguero/admin no tenga que entrar al Django admin
para gestionar productos día a día — esos son flujos repetitivos del
negocio. /admin/ queda para el superusuario en casos especiales.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
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
        solo = (request.GET.get('solo') or '').strip()
        mostrar_todos = request.GET.get('stock') == 'todos'
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
        elif not mostrar_todos:
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
        })
        return ctx


@login_required
@require_POST
def reponer_stock(request):
    """Suma stock de un producto/variante en una tienda.

    Acceso: admin / bodeguero (no cajero). El cajero opera ventas; el
    bodeguero/dueño reponen mercadería.
    """
    if not _puede_reponer(request.user):
        messages.error(request, 'No tenés permisos para reponer stock.')
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

    return render(request, 'bodega/productos_lista.html', {
        'productos': qs.order_by('familia__nombre', 'nombre'),
        'familias': Familia.objects.order_by('nombre'),
        'colegios': Colegio.objects.filter(activo=True).order_by('nombre'),
        'filtros': {
            'q': q, 'familia': familia_id, 'colegio': colegio_id, 'estado': estado,
        },
    })


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

    return render(request, 'bodega/producto_form.html', {
        'form': form, 'modo': 'editar', 'producto': p,
        'titulo': f'Editar — {p.nombre}',
        'ofertas': ofertas,
        'puede_gestionar_ofertas': _puede_gestionar_ofertas(request.user),
    })


@login_required
@reponer_required
def variantes_lista(request, pk):
    """Lista las variantes de un producto y permite agregar/editar/eliminar."""
    p = get_object_or_404(Producto, pk=pk)
    variantes = (
        p.variantes.all()
        .prefetch_related('valores__atributo')
        .order_by('sku')
    )
    return render(request, 'bodega/variantes_lista.html', {
        'producto': p,
        'variantes': variantes,
    })


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
    return render(request, 'bodega/materiales_lista.html', {
        'materiales': qs.order_by('nombre'),
        'filtros': {'q': q, 'estado': estado},
    })


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

    return render(request, 'bodega/ofertas_lista.html', {
        'ofertas': ofertas,
        'filtros': {'q': q, 'estado': estado, 'canal': canal},
        'canal_choices': Oferta.CANAL_CHOICES,
    })


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
