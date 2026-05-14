from django.contrib import admin
from django.utils.html import format_html

from .models import Atributo, Colegio, Familia, Oferta, Producto, ProductoImagen, ProductoVariante, Resena, ValorAtributo


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


class ProductoImagenInline(admin.TabularInline):
    """Galeria de imagenes adicionales del PDP.

    La imagen principal (`Producto.imagen`) sigue en el fieldset
    "Imagen" del Producto. Estas aparecen solo en el detalle online.
    """
    model = ProductoImagen
    extra = 1
    fields = ['imagen', 'orden', 'alt', 'preview']
    readonly_fields = ['preview']

    def preview(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" style="height:60px;width:60px;object-fit:cover;border-radius:4px;" />',
                obj.imagen.url,
            )
        return '—'
    preview.short_description = 'Preview'


@admin.register(Colegio)
class ColegioAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'direccion', 'telefono_contacto', 'activo']
    list_filter = ['activo']
    search_fields = ['nombre']


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['thumb', 'nombre', 'familia', 'colegio', 'precio_base', 'precio_costo', 'tiene_variantes', 'activo']
    list_display_links = ['nombre']
    list_filter = ['familia', 'colegio', 'activo', 'tiene_variantes']
    search_fields = ['nombre', 'descripcion']
    inlines = [ProductoImagenInline, ProductoVarianteInline]
    readonly_fields = ['preview']
    fieldsets = (
        (None, {'fields': ('nombre', 'familia', 'colegio', 'descripcion', 'activo')}),
        ('Precios', {'fields': ('precio_base', 'precio_costo')}),
        ('Imagen', {'fields': ('imagen', 'preview')}),
        ('Variantes', {'fields': ('tiene_variantes',)}),
    )

    def thumb(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" style="height:36px;width:36px;object-fit:cover;border-radius:4px;" />',
                obj.imagen.url,
            )
        return '—'
    thumb.short_description = 'Img'

    def preview(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" style="max-height:240px;max-width:320px;border-radius:6px;" />',
                obj.imagen.url,
            )
        return 'Sin imagen'
    preview.short_description = 'Vista previa'


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


@admin.register(Resena)
class ResenaAdmin(admin.ModelAdmin):
    """Moderacion manual de resenas. La duena aprueba/rechaza desde aca;
    solo las aprobadas se ven en el PDP publico (Bloque 9)."""
    list_display = ['producto', 'estrellas', 'nombre_publico', 'estado', 'creado']
    list_filter = ['estado', 'estrellas', 'producto__familia']
    search_fields = ['producto__nombre', 'nombre_publico', 'cliente_email', 'texto']
    readonly_fields = ['creado', 'cliente_email', 'recibo']
    fieldsets = (
        ('Contenido', {'fields': ('producto', 'estrellas', 'titulo', 'texto', 'nombre_publico')}),
        ('Cliente', {'fields': ('cliente_email', 'recibo')}),
        ('Moderacion', {'fields': ('estado', 'moderada', 'creado')}),
    )
    actions = ['aprobar_resenas', 'rechazar_resenas']

    @admin.action(description='Aprobar resenas seleccionadas')
    def aprobar_resenas(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(estado=Resena.ESTADO_APROBADA, moderada=timezone.now())
        self.message_user(request, f'{updated} resenas aprobadas.')

    @admin.action(description='Rechazar resenas seleccionadas')
    def rechazar_resenas(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(estado=Resena.ESTADO_RECHAZADA, moderada=timezone.now())
        self.message_user(request, f'{updated} resenas rechazadas.')
