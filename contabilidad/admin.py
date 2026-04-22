from django.contrib import admin

from .models import MovimientoCaja


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'tienda', 'tipo', 'monto', 'concepto', 'usuario']
    list_filter = ['tipo', 'tienda']
    search_fields = ['concepto']
    date_hierarchy = 'fecha'
