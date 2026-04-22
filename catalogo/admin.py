from django.contrib import admin

from .models import Atributo, Familia, Oferta, Producto, ProductoVariante, ValorAtributo


class ValorAtributoInline(admin.TabularInline):
    model = ValorAtributo
    extra = 1


@admin.register(Atributo)
class AtributoAdmin(admin.ModelAdmin):
    inlines = [ValorAtributoInline]
    list_display = ['nombre']


class ProductoVarianteInline(admin.TabularInline):
    model = ProductoVariante
    extra = 0
    filter_horizontal = ['valores']


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'familia', 'precio_base', 'precio_costo', 'tiene_variantes', 'activo']
    list_filter = ['familia', 'activo', 'tiene_variantes']
    search_fields = ['nombre', 'descripcion']
    inlines = [ProductoVarianteInline]


@admin.register(Familia)
class FamiliaAdmin(admin.ModelAdmin):
    list_display = ['nombre']
    search_fields = ['nombre']


@admin.register(ProductoVariante)
class ProductoVarianteAdmin(admin.ModelAdmin):
    list_display = ['sku', 'producto', 'precio_override', 'activa']
    list_filter = ['activa']
    search_fields = ['sku', 'producto__nombre']
    filter_horizontal = ['valores']


@admin.register(Oferta)
class OfertaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'tipo', 'valor', 'canal', 'fecha_inicio', 'fecha_fin', 'activa']
    list_filter = ['canal', 'tipo', 'activa']
    search_fields = ['nombre']
