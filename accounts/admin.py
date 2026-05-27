"""Admin custom para extender UserAdmin con el PerfilUsuario inline.

Permite a Blanca apagar las notificaciones de un despachador sin
desactivar la cuenta (caso: rotacion de personal, vacaciones, etc).
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import PerfilUsuario


class PerfilUsuarioInline(admin.StackedInline):
    """Editor inline del perfil dentro de la pagina de User."""
    model = PerfilUsuario
    can_delete = False
    verbose_name_plural = 'Notificaciones'
    fk_name = 'usuario'
    fields = ('recibe_notif_ecommerce',)
    extra = 0
    max_num = 1


class UserAdmin(DjangoUserAdmin):
    """UserAdmin extendido con el inline de PerfilUsuario."""
    inlines = (PerfilUsuarioInline,)
    # Columna extra en la lista de users para ver el flag de un vistazo
    list_display = DjangoUserAdmin.list_display + ('recibe_notif',)

    def recibe_notif(self, obj):
        try:
            return obj.perfil.recibe_notif_ecommerce
        except PerfilUsuario.DoesNotExist:
            return False
    recibe_notif.boolean = True
    recibe_notif.short_description = 'Notif. pedidos'

    def get_inline_instances(self, request, obj=None):
        # No mostrar el inline en /add/ (todavia no hay User pk → el
        # OneToOne falla). Despues del primer save, el signal crea el
        # perfil y al re-abrir el user ya aparece.
        if not obj:
            return []
        return super().get_inline_instances(request, obj)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
