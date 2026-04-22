from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from .models import ReciboVenta, ReciboVentaDetalle


class ReciboVentaDetalleInline(admin.TabularInline):
    model = ReciboVentaDetalle
    extra = 0
    readonly_fields = ['descripcion', 'precio_unitario', 'cantidad', 'descuento']


@admin.register(ReciboVenta)
class ReciboVentaAdmin(admin.ModelAdmin):
    list_display = [
        'pk', 'creado', 'canal', 'tienda', 'vendedor',
        'cliente_nombre', 'total', 'estado_coloreado',
    ]
    list_filter = ['canal', 'estado', 'tienda', 'creado']
    search_fields = [
        'pk', 'cliente_nombre', 'cliente_email', 'cliente_rut',
        'payment_reference', 'payment_idempotency_key',
    ]
    date_hierarchy = 'creado'
    readonly_fields = [
        'creado', 'modificado', 'payment_idempotency_key',
        'payment_provider', 'payment_reference', 'movimientos_caja_links',
    ]
    inlines = [ReciboVentaDetalleInline]
    autocomplete_fields = ['tienda', 'vendedor']
    fieldsets = [
        (None, {'fields': ['canal', 'estado', 'tienda', 'vendedor']}),
        ('Cliente', {'fields': ['cliente_nombre', 'cliente_email', 'cliente_rut']}),
        ('Montos', {'fields': ['subtotal', 'descuento', 'total']}),
        ('Pago', {
            'fields': [
                'payment_provider', 'payment_reference', 'payment_idempotency_key',
            ],
        }),
        ('SII', {
            'fields': ['dte_tipo', 'dte_folio', 'dte_timbre_xml'],
            'classes': ['collapse'],
        }),
        ('Contabilidad', {'fields': ['movimientos_caja_links']}),
        ('Auditoría', {'fields': ['creado', 'modificado']}),
    ]

    @admin.display(description='Estado', ordering='estado')
    def estado_coloreado(self, obj):
        colores = {
            ReciboVenta.ESTADO_PAGADO: 'green',
            ReciboVenta.ESTADO_FALLIDO: '#c00',
            ReciboVenta.ESTADO_CANCELADO: '#888',
            ReciboVenta.ESTADO_PENDIENTE: '#d90',
        }
        return format_html(
            '<b style="color:{};">{}</b>',
            colores.get(obj.estado, 'black'),
            obj.get_estado_display(),
        )

    @admin.display(description='Movimientos de caja')
    def movimientos_caja_links(self, obj):
        if not obj.pk:
            return '—'
        movs = list(obj.movimientos_caja.all())
        if not movs:
            return '—'
        filas = [
            (
                reverse('admin:contabilidad_movimientocaja_change', args=[m.pk]),
                m.get_tipo_display(),
                m.monto,
            )
            for m in movs
        ]
        return format_html_join(
            '\n', '<a href="{}">{} ${}</a><br>', filas,
        )
