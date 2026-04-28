from django.contrib import admin

from .models import (
    Bodega,
    Inventario,
    InventarioLinea,
    Material,
    MovimientoMaterial,
    MovimientoStock,
    Proveedor,
    Rendimiento,
    StockMaterial,
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
    list_display = ['nombre', 'descripcion', 'proveedor', 'costo_unitario_referencia', 'activo']
    list_filter = ['activo', 'proveedor']
    search_fields = ['nombre', 'descripcion']


@admin.register(StockMaterial)
class StockMaterialAdmin(admin.ModelAdmin):
    list_display = ['bodega', 'material', 'cantidad', 'modificado']
    list_filter = ['bodega']
    search_fields = ['material__nombre', 'bodega__nombre']
    readonly_fields = ['creado', 'modificado']


@admin.register(MovimientoMaterial)
class MovimientoMaterialAdmin(admin.ModelAdmin):
    list_display = ['creado', 'bodega', 'tipo', 'material', 'cantidad', 'costo_total', 'usuario']
    list_filter = ['tipo', 'bodega', 'material']
    search_fields = ['referencia', 'material__nombre']
    readonly_fields = ['creado']


@admin.register(Rendimiento)
class RendimientoAdmin(admin.ModelAdmin):
    list_display = ['material', 'variante', 'unidades_por_rollo']
    list_filter = ['material']
    search_fields = ['material__nombre', 'variante__sku', 'variante__producto__nombre']


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
