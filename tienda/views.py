from django.views import generic

from .models import StockTienda


class IndexView(generic.ListView):
    template_name = 'tienda/index.html'
    context_object_name = 'stock_productos'
    queryset = StockTienda.objects.select_related('producto', 'tienda').all()
