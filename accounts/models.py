"""Modelos de cuenta — un perfil OneToOne con `auth.User` para guardar
preferencias que no caben en el User estandar (ej. flag de notificaciones
para despachadores que rotan).

No usamos un AbstractUser custom porque migrar despues sin downtime es
penoso. Un OneToOneField es suficiente para este nivel de extension.
"""
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class PerfilUsuario(models.Model):
    """Extension del User para flags operativos.

    Se crea automaticamente al crearse el User (signal abajo). Para apagar
    notificaciones a un despachador que esta de vacaciones / rotacion,
    se toca `recibe_notif_ecommerce=False` desde el admin sin desactivar
    el user (mantiene su acceso al sistema, solo deja de recibir mails).
    """
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil',
        primary_key=True,
    )
    recibe_notif_ecommerce = models.BooleanField(
        default=True,
        help_text=(
            'Si está prendido y el usuario tiene rol DESPACHADOR + esta '
            'activo, recibe email cada vez que entra una venta online. '
            'Apagalo para pausar notificaciones sin desactivar la cuenta.'
        ),
        verbose_name='Recibe email de pedidos online',
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'perfil de usuario'
        verbose_name_plural = 'perfiles de usuario'

    def __str__(self):
        return f'Perfil de {self.usuario}'


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def _crear_perfil_al_crear_user(sender, instance, created, **kwargs):
    """Garantiza que TODO User tenga su PerfilUsuario. Idempotente."""
    if created:
        PerfilUsuario.objects.get_or_create(usuario=instance)
