from django.conf import settings
from django.db import models


class MovimientoCaja(models.Model):
    """Entrada o salida de dinero de la caja/cuenta del negocio.

    `categoria` permite separar EERR (Estado de Resultados) de los
    movimientos puros de caja:
      - INGRESO_VENTA: ingresos del EERR.
      - COSTO_INVENTARIO: compra de materia prima → salida de caja, NO
        gasto del período (es activo: el rollo entra a inventario).
      - COSTO_PRODUCCION: pago al confeccionista → salida de caja, NO
        gasto del período (se activa al precio_costo de cada prenda).
      - GASTO_OPERATIVO: arriendo, sueldos, servicios, etc → SÍ es gasto.
      - OTRO: comodín cuando no encaja.
    """

    ENTRADA = 'entrada'
    SALIDA = 'salida'
    TIPO_CHOICES = [
        (ENTRADA, 'Entrada'),
        (SALIDA, 'Salida'),
    ]

    INGRESO_VENTA = 'ingreso_venta'
    COSTO_INVENTARIO = 'costo_inventario'
    COSTO_PRODUCCION = 'costo_produccion'
    GASTO_OPERATIVO = 'gasto_operativo'
    OTRO = 'otro'
    CATEGORIA_CHOICES = [
        (INGRESO_VENTA,    'Ingreso por venta'),
        (COSTO_INVENTARIO, 'Compra de inventario / materia prima'),
        (COSTO_PRODUCCION, 'Costo de producción / confección'),
        (GASTO_OPERATIVO,  'Gasto operativo'),
        (OTRO,             'Otro'),
    ]

    tienda = models.ForeignKey(
        'bodega.Tienda', on_delete=models.PROTECT, related_name='movimientos_caja'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    categoria = models.CharField(
        max_length=30, choices=CATEGORIA_CHOICES, default=OTRO,
        help_text='Cómo afecta al estado de resultados',
    )
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
        indexes = [
            models.Index(fields=['categoria']),
            models.Index(fields=['fecha']),
        ]

    def __str__(self):
        return f'{self.tipo} ${self.monto} · {self.concepto}'
