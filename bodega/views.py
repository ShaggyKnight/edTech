from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views import generic

from .models import Familia, Producto


class IndexView(LoginRequiredMixin, PermissionRequiredMixin, generic.ListView):
    permission_required = 'bodega.view_producto'
    template_name = 'bodega/index.html'
    context_object_name = 'inventario'
    queryset = Producto.objects.select_related('familia').all()


class FamiliasView(LoginRequiredMixin, PermissionRequiredMixin, generic.ListView):
    permission_required = 'bodega.view_familia'
    model = Familia
    template_name = 'bodega/familias.html'


class ProductoView(LoginRequiredMixin, PermissionRequiredMixin, generic.ListView):
    permission_required = 'bodega.view_producto'
    template_name = 'bodega/productos.html'
    context_object_name = 'lista_productos'
    queryset = Producto.objects.select_related('familia').all()


class DetallesView(LoginRequiredMixin, PermissionRequiredMixin, generic.DetailView):
    permission_required = 'bodega.view_producto'
    model = Producto
    template_name = 'bodega/detalles.html'
