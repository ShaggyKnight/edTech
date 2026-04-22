from django.contrib import admin

from .models import ReciboVenta, ReciboVentaDetalle


class ReciboVentaDetalleInline(admin.TabularInline):
    model = ReciboVentaDetalle
    extra = 0
    readonly_fields = ['descripcion', 'precio_unitario', 'cantidad', 'descuento']


@admin.register(ReciboVenta)
class ReciboVentaAdmin(admin.ModelAdmin):
    list_display = ['pk', 'creado', 'canal', 'tienda', 'vendedor', 'total', 'estado']
    list_filter = ['canal', 'estado', 'tienda']
    search_fields = ['cliente_nombre', 'cliente_email', 'cliente_rut', 'payment_reference']
    date_hierarchy = 'creado'
    readonly_fields = ['creado', 'modificado', 'payment_idempotency_key']
    inlines = [ReciboVentaDetalleInline]
