from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import MovimientoCaja


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(admin.ModelAdmin):
    list_display = [
        'fecha', 'tienda', 'tipo', 'monto_fmt', 'concepto', 'recibo_link', 'usuario',
    ]
    list_filter = ['tipo', 'tienda', 'fecha']
    search_fields = ['concepto', 'recibo_venta__cliente_nombre']
    date_hierarchy = 'fecha'
    autocomplete_fields = ['tienda', 'recibo_venta', 'usuario']
    readonly_fields = ['fecha']

    @admin.display(description='Monto', ordering='monto')
    def monto_fmt(self, obj):
        prefijo = '+' if obj.tipo == MovimientoCaja.ENTRADA else '−'
        return f'{prefijo}${obj.monto}'

    @admin.display(description='Recibo')
    def recibo_link(self, obj):
        if not obj.recibo_venta_id:
            return '—'
        url = reverse('admin:pos_reciboventa_change', args=[obj.recibo_venta_id])
        return format_html('<a href="{}">#{}</a>', url, obj.recibo_venta_id)
