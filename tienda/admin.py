from django.contrib import admin

from .models import HistoriaVentas, ReciboVenta, ReciboVentaDetalle, StockTienda, Tienda


class ReciboVentaDetalleInline(admin.TabularInline):
    model = ReciboVentaDetalle
    extra = 0


@admin.register(ReciboVenta)
class ReciboVentaAdmin(admin.ModelAdmin):
    list_display = ('id', 'fecha_hora_venta', 'tienda', 'vendedor', 'total')
    list_filter = ('tienda', 'fecha_hora_venta')
    inlines = [ReciboVentaDetalleInline]


@admin.register(StockTienda)
class StockTiendaAdmin(admin.ModelAdmin):
    list_display = ('tienda', 'producto', 'cantidad', 'fecha_hora_modificacion')
    list_filter = ('tienda',)
    search_fields = ('producto__nombre',)


admin.site.register(Tienda)
admin.site.register(HistoriaVentas)
