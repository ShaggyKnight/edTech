from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils import timezone


class Tienda(models.Model):
    """Sucursal física u organización comercial."""
    nombre_organizacion = models.CharField(max_length=200, unique=True)
    rut_organizacion = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    telefono_contacto = models.CharField(max_length=20, blank=True)
    correo_contacto = models.EmailField(blank=True)
    activa = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre_organizacion']

    def __str__(self):
        return self.nombre_organizacion


class Bodega(models.Model):
    """Almacén físico asociado a una tienda."""
    tienda = models.ForeignKey(
        Tienda, on_delete=models.PROTECT, null=True, blank=True, related_name='bodegas'
    )
    nombre = models.CharField(max_length=60, unique=True)
    ubicacion = models.CharField(max_length=100, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Proveedor(models.Model):
    nombre_proveedor = models.CharField(max_length=60, unique=True)
    rut_proveedor = models.CharField(max_length=20, unique=True)
    direccion = models.CharField(max_length=200, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    correo = models.EmailField(blank=True)
    cuenta_bco = models.CharField(max_length=30, blank=True)
    nombre_contacto = models.CharField(max_length=60, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre_proveedor']

    def __str__(self):
        return self.nombre_proveedor


class Material(models.Model):
    """Materia prima / insumo para elaborar un producto."""
    producto = models.ForeignKey(
        'catalogo.Producto', on_delete=models.CASCADE, related_name='materiales'
    )
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='materiales'
    )
    nombre = models.CharField(max_length=60)
    descripcion = models.CharField(max_length=200, blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_proveedor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    largo = models.PositiveIntegerField(default=0, null=True, blank=True)
    comerciable = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} - {self.descripcion}'


class StockTienda(models.Model):
    """Stock disponible por tienda. Apunta a variante (si el producto tiene variantes) o al producto directamente."""
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE, related_name='stock')
    variante = models.ForeignKey(
        'catalogo.ProductoVariante',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='stock_tienda',
    )
    producto = models.ForeignKey(
        'catalogo.Producto',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='stock_tienda_directo',
    )
    cantidad = models.PositiveIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            CheckConstraint(
                check=(
                    (Q(variante__isnull=False) & Q(producto__isnull=True))
                    | (Q(variante__isnull=True) & Q(producto__isnull=False))
                ),
                name='stocktienda_variante_xor_producto',
            ),
        ]

    def clean(self):
        if bool(self.variante) == bool(self.producto):
            raise ValidationError('StockTienda debe referenciar exactamente una variante o un producto.')

    def __str__(self):
        item = self.variante or self.producto
        return f'{self.tienda} · {item} · {self.cantidad}'


class Inventario(models.Model):
    """Conteo físico de stock en una bodega."""
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='inventarios')
    descripcion = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creado']

    def __str__(self):
        return self.creado.strftime('%d-%m-%Y %H:%M')

    def es_reciente(self):
        return self.creado >= timezone.now() - timedelta(days=1)


class InventarioLinea(models.Model):
    inventario = models.ForeignKey(Inventario, on_delete=models.CASCADE, related_name='lineas')
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
    cantidad_contada = models.IntegerField(default=0)

    class Meta:
        constraints = [
            CheckConstraint(
                check=(
                    (Q(variante__isnull=False) & Q(producto__isnull=True))
                    | (Q(variante__isnull=True) & Q(producto__isnull=False))
                ),
                name='inventariolinea_variante_xor_producto',
            ),
        ]


class MovimientoStock(models.Model):
    """Audit log de cambios de stock: entradas (compra/ajuste+), salidas (venta/merma), traslados."""

    ENTRADA = 'entrada'
    SALIDA = 'salida'
    TRASLADO = 'traslado'
    TIPO_CHOICES = [
        (ENTRADA, 'Entrada'),
        (SALIDA, 'Salida'),
        (TRASLADO, 'Traslado'),
    ]

    tienda = models.ForeignKey(Tienda, on_delete=models.PROTECT, related_name='movimientos_stock')
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
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField()
    referencia = models.CharField(max_length=120, blank=True, help_text='# de recibo, factura o nota')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movimientos_stock',
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado']
        constraints = [
            CheckConstraint(
                check=(
                    (Q(variante__isnull=False) & Q(producto__isnull=True))
                    | (Q(variante__isnull=True) & Q(producto__isnull=False))
                ),
                name='movimientostock_variante_xor_producto',
            ),
        ]
