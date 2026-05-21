from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
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
    fields = ['sku', 'valores', 'precio_override', 'activa', 'codigo_barras']
    # SKU auto-llenado: si el cajero deja vacio, lo generamos en
    # ProductoVariante.save() (ver hook abajo). Tambien tiene un boton
    # explicito "Generar SKU" en el form de ProductoVariante admin.


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
    list_display = ['thumb', 'nombre', 'marca', 'familia', 'colegio', 'precio_base', 'tiene_variantes', 'activo']
    list_display_links = ['nombre']
    list_filter = ['familia', 'colegio', 'genero', 'concentracion', 'activo', 'tiene_variantes']
    search_fields = ['nombre', 'descripcion', 'marca', 'familia_olfativa']
    inlines = [ProductoImagenInline, ProductoVarianteInline]
    readonly_fields = ['preview']

    def get_queryset(self, request):
        # Bloque 6 (perf): list_display incluye familia + colegio. Sin
        # select_related serian 2N queries por pagina del admin.
        return super().get_queryset(request).select_related('familia', 'colegio')
    fieldsets = (
        (None, {'fields': ('nombre', 'familia', 'colegio', 'descripcion', 'activo')}),
        ('Precios', {'fields': ('precio_base', 'precio_costo')}),
        ('Imagen', {'fields': ('imagen', 'preview')}),
        ('Perfumeria (opcional)', {
            'classes': ('collapse',),
            'fields': ('marca', 'concentracion', 'medida_ml', 'genero',
                       'familia_olfativa', 'notas_clave'),
            'description': (
                'Metadata especifica de perfumes (vacio en uniformes y otras '
                'familias). Si el producto tiene varias presentaciones, '
                'usar variantes para la combinacion volumen + concentracion.'
            ),
        }),
        ('Variantes', {
            'fields': ('tiene_variantes',),
            'description': (
                'Marcar SI el producto se vende en varias combinaciones '
                '(ej. talla, color, volumen). Al guardar, si esta marcado y '
                'aun no hay variantes configuradas, vas a ser redirigido a '
                'configurarlas (paso siguiente del wizard).'
            ),
        }),
    )

    def response_change(self, request, obj):
        # Wizard: si tiene_variantes esta marcado y no hay variantes
        # creadas todavia, mostramos un mensaje claro y dejamos al usuario
        # en la misma pagina para que use el inline de abajo. Si quiere
        # crear via el admin separado, le damos un link directo.
        if obj.tiene_variantes and not obj.variantes.exists():
            messages.warning(
                request,
                format_html(
                    'Marcaste "tiene variantes" pero todavia no agregaste '
                    'ninguna. Configurá las combinaciones en la seccion '
                    '<b>Variantes de producto</b> al final de esta pagina, '
                    'o <a href="{}?producto={}">crear una variante por separado</a>.',
                    reverse('admin:catalogo_productovariante_add'),
                    obj.pk,
                ),
            )
        return super().response_change(request, obj)

    response_add = response_change

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
    actions = ['regenerar_sku']
    change_form_template = 'admin/catalogo/productovariante/change_form.html'

    class Media:
        js = ('admin/js/sku_generator.js',)

    def get_queryset(self, request):
        # Bloque 6 (perf): `producto` se muestra en list_display.
        return super().get_queryset(request).select_related('producto')

    def save_related(self, request, form, formsets, change):
        """Si el SKU quedo en blanco, autogeneramos despues de guardar
        los valores de atributo (M2M). save_related corre DESPUES que
        Django persiste el M2M, asi que `valores` ya esta disponible.
        """
        super().save_related(request, form, formsets, change)
        variante = form.instance
        if not variante.sku:
            from catalogo.sku import sugerir_desde_variante
            variante.sku = sugerir_desde_variante(variante)
            variante.save(update_fields=['sku'])

    @admin.action(description='Regenerar SKU desde marca + nombre + valores')
    def regenerar_sku(self, request, queryset):
        from catalogo.sku import sugerir_desde_variante
        actualizadas = 0
        for v in queryset:
            nuevo = sugerir_desde_variante(v)
            if nuevo != v.sku:
                v.sku = nuevo
                v.save(update_fields=['sku'])
                actualizadas += 1
        self.message_user(
            request, f'{actualizadas} variante(s) con SKU regenerado.'
        )


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

    def get_queryset(self, request):
        # Bloque 6 (perf): producto se muestra en list_display.
        return super().get_queryset(request).select_related('producto')

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
