from django.conf import settings
from django.db import models


class MovimientoCaja(models.Model):
    """Entrada o salida de dinero de la caja/cuenta del negocio."""

    ENTRADA = 'entrada'
    SALIDA = 'salida'
    TIPO_CHOICES = [
        (ENTRADA, 'Entrada'),
        (SALIDA, 'Salida'),
    ]

    tienda = models.ForeignKey(
        'bodega.Tienda', on_delete=models.PROTECT, related_name='movimientos_caja'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    concepto = models.CharField(max_length=200)
    recibo_venta = models.ForeignKey(
        'pos.ReciboVenta',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movimientos_caja',
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movimientos_caja',
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.tipo} ${self.monto} · {self.concepto}'
