from django.contrib import admin

from .models import (
    Atributo,
    Bodega,
    Familia,
    Grupo,
    Inventario,
    Inventariolinea,
    Material,
    Producto,
    ProductoAtributo,
    ProductoAtributoValor,
    Proveedor,
)


class ProductoAtributoInline(admin.TabularInline):
    model = ProductoAtributo
    extra = 1


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'familia', 'precio', 'talla')
    list_filter = ('familia', 'talla')
    search_fields = ('nombre', 'descripcion')
    inlines = [ProductoAtributoInline]


class InventariolineaInline(admin.TabularInline):
    model = Inventariolinea
    extra = 1


@admin.register(Inventario)
class InventarioAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'bodega', 'creado')
    list_filter = ('bodega',)
    inlines = [InventariolineaInline]


admin.site.register(Bodega)
admin.site.register(Familia)
admin.site.register(Grupo)
admin.site.register(Atributo)
admin.site.register(ProductoAtributoValor)
admin.site.register(Material)
admin.site.register(Proveedor)
