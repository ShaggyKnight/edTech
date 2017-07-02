from django.contrib import admin

from .models import Bodega, Producto, Familia, Material, Inventario, Inventariolinea
admin.site.register(Bodega)
admin.site.register(Producto)
admin.site.register(Familia)
admin.site.register(Material)
admin.site.register(Inventario)
admin.site.register(Inventariolinea)