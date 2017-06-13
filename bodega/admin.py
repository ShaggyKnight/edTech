from django.contrib import admin

from .models import Bodega, Producto, ProductoLinea, Familia, Material
# Register your models here.
admin.site.register(Bodega)
admin.site.register(Producto)
admin.site.register(ProductoLinea)
admin.site.register(Familia)
admin.site.register(Material)