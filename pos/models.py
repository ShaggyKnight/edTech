from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Q


class ReciboVenta(models.Model):
    """Recibo de venta. Puede originarse en POS presencial o en e-commerce (canal)."""

    CANAL_PRESENCIAL = 'presencial'
    CANAL_ONLINE = 'online'
    CANAL_CHOICES = [
        (CANAL_PRESENCIAL, 'Presencial'),
        (CANAL_ONLINE, 'Online'),
    ]

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PAGADO = 'pagado'
    ESTADO_FALLIDO = 'fallido'
    ESTADO_CANCELADO = 'cancelado'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_PAGADO, 'Pagado'),
        (ESTADO_FALLIDO, 'Fallido'),
        (ESTADO_CANCELADO, 'Cancelado'),
    ]

    canal = models.CharField(max_length=20, choices=CANAL_CHOICES)
    tienda = models.ForeignKey('bodega.Tienda', on_delete=models.PROTECT, related_name='recibos')
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ventas_realizadas',
        help_text='Cajero que procesó la venta (solo presencial)',
    )
    cliente_nombre = models.CharField(max_length=200, blank=True)
    cliente_email = models.EmailField(blank=True, help_text='Para envío de boleta por correo')
    cliente_rut = models.CharField(max_length=20, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)

    payment_provider = models.CharField(
        max_length=30,
        blank=True,
        help_text='tuu | webpay | mercadopago | mock',
    )
    payment_idempotency_key = models.CharField(
        max_length=36, unique=True, null=True, blank=True
    )
    payment_reference = models.CharField(max_length=120, blank=True)

    dte_tipo = models.IntegerField(
        null=True,
        blank=True,
        help_text='SII: 39=boleta electrónica, 33=factura afecta, etc',
    )
    dte_folio = models.CharField(max_length=50, blank=True)
    dte_timbre_xml = models.TextField(blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creado']
        indexes = [
            models.Index(fields=['canal', 'estado']),
            models.Index(fields=['creado']),
        ]

    def __str__(self):
        return f'Recibo #{self.pk} [{self.canal}] - {self.creado:%d-%m-%Y %H:%M}'


class ReciboVentaDetalle(models.Model):
    recibo = models.ForeignKey(
        ReciboVenta, on_delete=models.CASCADE, related_name='detalles'
    )
    variante = models.ForeignKey(
        'catalogo.ProductoVariante',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    producto = models.ForeignKey(
        'catalogo.Producto',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    descripcion = models.CharField(
        max_length=300,
        help_text='Snapshot del nombre del producto al momento de la venta',
    )
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))

    class Meta:
        constraints = [
            CheckConstraint(
                check=(
                    (Q(variante__isnull=False) & Q(producto__isnull=True))
                    | (Q(variante__isnull=True) & Q(producto__isnull=False))
                ),
                name='detalle_variante_xor_producto',
            ),
        ]

    def clean(self):
        if bool(self.variante) == bool(self.producto):
            raise ValidationError('El detalle debe apuntar a una variante o a un producto, no ambos.')

    def subtotal(self):
        return (self.precio_unitario * self.cantidad) - self.descuento
