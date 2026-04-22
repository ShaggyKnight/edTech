from django.contrib import admin

from .models import (
    Bodega,
    Inventario,
    InventarioLinea,
    Material,
    MovimientoStock,
    Proveedor,
    StockTienda,
    Tienda,
)


@admin.register(Tienda)
class TiendaAdmin(admin.ModelAdmin):
    list_display = ['nombre_organizacion', 'rut_organizacion', 'activa']
    search_fields = ['nombre_organizacion', 'rut_organizacion']
    list_filter = ['activa']


@admin.register(Bodega)
class BodegaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'tienda', 'ubicacion']
    list_filter = ['tienda']
    search_fields = ['nombre']


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ['nombre_proveedor', 'rut_proveedor', 'telefono', 'correo']
    search_fields = ['nombre_proveedor', 'rut_proveedor']


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'producto', 'proveedor', 'precio', 'comerciable']
    list_filter = ['comerciable', 'proveedor']
    search_fields = ['nombre', 'descripcion']


@admin.register(StockTienda)
class StockTiendaAdmin(admin.ModelAdmin):
    list_display = ['tienda', 'variante', 'producto', 'cantidad', 'modificado']
    list_filter = ['tienda']
    search_fields = ['variante__sku', 'producto__nombre']


class InventarioLineaInline(admin.TabularInline):
    model = InventarioLinea
    extra = 0


@admin.register(Inventario)
class InventarioAdmin(admin.ModelAdmin):
    list_display = ['bodega', 'creado', 'es_reciente']
    list_filter = ['bodega']
    inlines = [InventarioLineaInline]


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ['creado', 'tienda', 'tipo', 'cantidad', 'variante', 'producto', 'usuario']
    list_filter = ['tipo', 'tienda']
    search_fields = ['referencia', 'variante__sku', 'producto__nombre']
    readonly_fields = ['creado']
