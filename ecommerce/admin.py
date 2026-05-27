from django.contrib import admin

from .models import AvisoStockReposicion, Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'apellido', 'email', 'rut', 'telefono']
    search_fields = ['nombre', 'apellido', 'email', 'rut']


@admin.register(AvisoStockReposicion)
class AvisoStockReposicionAdmin(admin.ModelAdmin):
    list_display = ['email', 'variante', 'estado', 'creado',
                    'notificado', 'cancelado']
    list_filter = ['notificado', 'cancelado', 'creado']
    search_fields = ['email', 'variante__sku',
                     'variante__producto__nombre']
    autocomplete_fields = ['variante']
    readonly_fields = ['token', 'creado']
    list_per_page = 50

    fieldsets = (
        (None, {
            'fields': ('variante', 'email'),
        }),
        ('Estado', {
            'fields': ('creado', 'notificado', 'cancelado'),
            'description': (
                'Pendiente = todavía esperando reposición. '
                'Notificado = email enviado (sin reenvío automático). '
                'Cancelado = el cliente clickeó unsubscribe.'
            ),
        }),
        ('Diagnóstico', {
            'fields': ('token',),
            'classes': ('collapse',),
            'description': 'Token del link de cancelación en el email.',
        }),
    )

    def estado(self, obj):
        if obj.cancelado:
            return '🚫 cancelado'
        if obj.notificado:
            return '✓ enviado'
        return '⏳ pendiente'
    estado.short_description = 'Estado'
