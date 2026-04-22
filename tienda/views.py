from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views import generic

from .models import StockTienda


class IndexView(LoginRequiredMixin, PermissionRequiredMixin, generic.ListView):
    permission_required = 'tienda.view_stocktienda'
    template_name = 'tienda/index.html'
    context_object_name = 'stock_productos'
    queryset = StockTienda.objects.select_related('producto', 'tienda').all()
