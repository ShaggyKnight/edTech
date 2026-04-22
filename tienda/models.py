from django.conf import settings
from django.db import models

from bodega.models import Producto


class Tienda(models.Model):
    nombre_organizacion = models.CharField(max_length=200, unique=True)
    direccion = models.CharField(max_length=200, null=True, blank=True)
    telefono_contacto = models.CharField(max_length=20)
    correo_contacto = models.EmailField()
    rut_organizacion = models.CharField(max_length=20)

    def __str__(self):
        return self.nombre_organizacion


class StockTienda(models.Model):
    tienda = models.ForeignKey(
        Tienda, on_delete=models.CASCADE, related_name='stock', null=True
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name='stock_tienda'
    )
    cantidad = models.PositiveIntegerField(default=0)
    fecha_hora_creacion = models.DateTimeField(auto_now_add=True)
    fecha_hora_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('tienda', 'producto')]

    def __str__(self):
        return f'{self.producto} - {self.cantidad}'


class ReciboVenta(models.Model):
    fecha_hora_venta = models.DateTimeField(auto_now_add=True)
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ventas',
    )
    tienda = models.ForeignKey(Tienda, on_delete=models.PROTECT, related_name='recibos')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f'Recibo #{self.pk} - {self.fecha_hora_venta:%d-%m-%Y %H:%M}'


class ReciboVentaDetalle(models.Model):
    recibo_venta = models.ForeignKey(
        ReciboVenta, on_delete=models.CASCADE, related_name='detalles'
    )
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad_vendida = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def subtotal(self):
        return self.cantidad_vendida * self.precio_unitario


class HistoriaVentas(models.Model):
    fecha_venta = models.DateTimeField(auto_now_add=True)
    recibo_venta = models.ForeignKey(ReciboVenta, on_delete=models.CASCADE)
    monto_venta = models.DecimalField(max_digits=12, decimal_places=2)
