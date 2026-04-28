"""Vistas de bodega: stock por tienda con filtros y alertas."""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import render
from django.views import generic

from bodega.models import StockMaterial, StockTienda, Tienda
from catalogo.models import Familia


# Umbrales para clasificar stock terminado.
STOCK_AGOTADO = 0
STOCK_BAJO = 5  # ≤5 = bajo


class StockView(LoginRequiredMixin, PermissionRequiredMixin, generic.TemplateView):
    """Stock de productos terminados por tienda con filtros y alertas.

    Filtros (vía querystring):
      ?tienda=<pk>     — filtrar por tienda
      ?familia=<pk>    — filtrar por familia del producto
      ?solo=bajo|cero  — solo items con stock bajo o agotado
      ?q=...           — búsqueda por nombre / SKU
    """
    permission_required = 'bodega.view_stocktienda'
    template_name = 'bodega/stock.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request

        qs = (
            StockTienda.objects
            .select_related('tienda', 'variante__producto', 'variante__producto__familia',
                            'producto', 'producto__familia')
            .order_by('tienda__nombre_organizacion', 'producto__nombre',
                      'variante__producto__nombre', 'variante__sku')
        )

        tienda_id = (request.GET.get('tienda') or '').strip()
        familia_id = (request.GET.get('familia') or '').strip()
        solo = (request.GET.get('solo') or '').strip()
        q = (request.GET.get('q') or '').strip()

        if tienda_id.isdigit():
            qs = qs.filter(tienda_id=int(tienda_id))
        if familia_id.isdigit():
            f = int(familia_id)
            from django.db.models import Q
            qs = qs.filter(Q(producto__familia_id=f) | Q(variante__producto__familia_id=f))
        if solo == 'cero':
            qs = qs.filter(cantidad=STOCK_AGOTADO)
        elif solo == 'bajo':
            qs = qs.filter(cantidad__lte=STOCK_BAJO)
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(producto__nombre__icontains=q)
                | Q(variante__producto__nombre__icontains=q)
                | Q(variante__sku__icontains=q)
            )

        # KPIs sobre el queryset YA filtrado (qué está mostrando la tabla).
        items = list(qs)
        n_total = len(items)
        n_agotado = sum(1 for s in items if s.cantidad == STOCK_AGOTADO)
        n_bajo = sum(1 for s in items if 0 < s.cantidad <= STOCK_BAJO)
        n_ok = n_total - n_agotado - n_bajo
        unidades = sum(s.cantidad for s in items)

        # Alertas: items con stock bajo (no agotado y ≤5) — para el chart.
        alertas = sorted(
            (s for s in items if 0 < s.cantidad <= STOCK_BAJO),
            key=lambda s: s.cantidad,
        )[:15]
        chart_alertas = [{
            'nombre': (s.variante and f'{s.variante.producto.nombre} ({s.variante.sku})')
                      or (s.producto and s.producto.nombre) or '?',
            'cantidad': s.cantidad,
            'tienda': s.tienda.nombre_organizacion,
        } for s in alertas]

        # Stock de materiales (rollos en bodega) — KPI extra.
        rollos_total = sum(
            sm.cantidad for sm in StockMaterial.objects.all()
        )

        ctx.update({
            'stock': items,
            'kpi': {
                'n_total': n_total,
                'n_ok': n_ok,
                'n_bajo': n_bajo,
                'n_agotado': n_agotado,
                'unidades': unidades,
                'rollos_total': rollos_total,
            },
            'chart_alertas': chart_alertas,
            'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
            'familias': Familia.objects.order_by('nombre'),
            'filtros': {
                'tienda': tienda_id, 'familia': familia_id, 'solo': solo, 'q': q,
            },
            'umbral_bajo': STOCK_BAJO,
        })
        return ctx
