from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views import generic

from .models import StockTienda


class StockView(LoginRequiredMixin, PermissionRequiredMixin, generic.ListView):
    """Listado de stock por tienda — placeholder, se expandirá en Fase D (admin)."""
    permission_required = 'bodega.view_stocktienda'
    template_name = 'bodega/stock.html'
    context_object_name = 'stock'
    queryset = (
        StockTienda.objects
        .select_related('tienda', 'variante__producto', 'producto')
        .order_by('tienda__nombre_organizacion')
    )
