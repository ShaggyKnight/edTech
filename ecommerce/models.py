import secrets

from django.conf import settings
from django.db import models


class Cliente(models.Model):
    """Cliente de la tienda online. Opcionalmente asociado a un User de Django."""
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cliente',
    )
    email = models.EmailField(unique=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100, blank=True)
    rut = models.CharField(max_length=20, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['apellido', 'nombre']

    def __str__(self):
        return f'{self.nombre} {self.apellido}'.strip() or self.email


def _generar_token_aviso() -> str:
    """Token urlsafe de ~24 chars para el link de cancelacion del aviso."""
    return secrets.token_urlsafe(18)


class AvisoStockReposicion(models.Model):
    """Suscripcion de un cliente para ser avisado cuando vuelve stock.

    Semantica explicita pedida por la dueña: UN aviso = UN mail.
    Si el cliente quiere recibir otro aviso debe volver a marcarlo en
    el PDP. NO se reenvia automaticamente cada vez que vuelve stock.

    Estados (no es enum por simplicidad — combinacion de 2 datetimes):
      - pendiente: notificado=None y cancelado=None
        -> Aparece en el queryset que el signal post_save chequea.
      - enviado:   notificado=set, cancelado=None
        -> El cliente recibio el mail. Si vuelve a perderse stock y
           luego entra de nuevo, NO recibe segundo aviso a menos que
           se vuelva a suscribir (resucitando este row o creando otro).
      - cancelado: cancelado=set
        -> El cliente uso el link de unsubscribe. No se envia mas.

    Idempotencia del POST desde el PDP:
      get_or_create((variante, email)) — si ya existe un row en
      cualquier estado, lo "resucita" reseteando notificado=None y
      cancelado=None. El usuario quiere otro aviso, se lo damos.
    """
    variante = models.ForeignKey(
        'catalogo.ProductoVariante',
        on_delete=models.CASCADE,
        related_name='avisos_stock',
    )
    email = models.EmailField()
    token = models.CharField(
        max_length=32,
        unique=True,
        default=_generar_token_aviso,
        help_text='Para construir el link de unsubscribe en el email.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    notificado = models.DateTimeField(
        null=True, blank=True,
        help_text='Cuando se envio el email. Null = pendiente.',
    )
    cancelado = models.DateTimeField(
        null=True, blank=True,
        help_text='Si el cliente uso el link de unsubscribe. No se borra '
                  'para tener metricas — solo se marca como cerrado.',
    )

    class Meta:
        unique_together = [('variante', 'email')]
        ordering = ['-creado']
        verbose_name = 'aviso de reposición'
        verbose_name_plural = 'avisos de reposición'
        indexes = [
            # Signal hace lookup por variante + pendiente. Compound
            # cubre el query principal.
            models.Index(fields=['variante', 'notificado']),
        ]

    def __str__(self):
        estado = 'enviado' if self.notificado else 'pendiente'
        if self.cancelado:
            estado = 'cancelado'
        return f'{self.email} → {self.variante} ({estado})'

    @property
    def pendiente(self) -> bool:
        """True si el row representa una suscripcion activa que aun no
        recibio mail. Lo que el signal busca."""
        return self.notificado is None and self.cancelado is None
