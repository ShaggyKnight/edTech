"""Vistas de bodega: stock por tienda con filtros + reposición."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import F, Q, Sum
from django.shortcuts import redirect, render
from django.views import generic
from django.views.decorators.http import require_POST

from bodega.models import (
    MovimientoStock,
    StockMaterial,
    StockTienda,
    Tienda,
)
from catalogo.models import Colegio, Familia, Producto, ProductoVariante


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
            qs = qs.filter(
                Q(producto__nombre__icontains=q)
                | Q(variante__producto__nombre__icontains=q)
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
