from django.views import generic

from .models import Familia, Producto


class IndexView(generic.ListView):
    template_name = 'bodega/index.html'
    context_object_name = 'inventario'
    queryset = Producto.objects.select_related('familia').all()


class FamiliasView(generic.ListView):
    model = Familia
    template_name = 'bodega/familias.html'


class ProductoView(generic.ListView):
    template_name = 'bodega/productos.html'
    context_object_name = 'lista_productos'
    queryset = Producto.objects.select_related('familia').all()


class DetallesView(generic.DetailView):
    model = Producto
    template_name = 'bodega/detalles.html'
