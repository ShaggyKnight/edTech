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
    """Materia prima (rollo de tela) que se compra a un proveedor y se consume
    al producir prendas terminadas.

    Unidad: rollo (entero). Una compra registra cantidad + costo total real
    pagado — el costo unitario varía con el peso del rollo, así que se guarda
    en cada compra (MovimientoMaterial) y aquí queda solo como referencia.
    """
    nombre = models.CharField(max_length=80, unique=True)
    nombre_buscable = models.CharField(max_length=80, db_index=True, blank=True)
    descripcion = models.CharField(max_length=200, blank=True)
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='materiales',
    )
    costo_unitario_referencia = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Costo aproximado por rollo, en CLP. El costo real de cada compra se guarda en MovimientoMaterial.',
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        from edTech.search import normalize_text
        self.nombre_buscable = normalize_text(self.nombre)
        super().save(*args, **kwargs)


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

    def __str__(self):
        item = self.variante or self.producto
        return f'{item} = {self.cantidad_contada}'


class Rendimiento(models.Model):
    """Cuántas unidades de una variante se obtienen de un rollo de material.

    Ejemplo: "Rollo de fleece azul SFJ" + "Buzo SFJ talla M" = 50 unidades.
              "Rollo de fleece azul SFJ" + "Buzo SFJ talla XL" = 35 unidades.

    Si una variante no tiene fila de Rendimiento, no se puede calcular su
    capacidad de producción y queda fuera del reporte (informa explícitamente).

    Una variante usa **un solo material** (la tela del producto). Los
    accesorios (cuellos, puños, hilo) los compra el confeccionista y se
    pagan dentro del costo de confección, no se modelan acá.
    """
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='rendimientos')
    variante = models.ForeignKey(
        'catalogo.ProductoVariante',
        on_delete=models.CASCADE,
        related_name='rendimientos',
    )
    unidades_por_rollo = models.PositiveIntegerField(
        help_text='Cuántas unidades de esta variante salen de un rollo (después de cortar). '
                  'Tallas grandes consumen más tela, así que el número baja.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('material', 'variante')]
        ordering = ['material__nombre', 'variante__sku']

    def __str__(self):
        return f'{self.variante} ← {self.unidades_por_rollo} u/rollo de {self.material}'


class StockMaterial(models.Model):
    """Stock de rollos de un material en una bodega específica.

    Análogo a `StockTienda` pero para materias primas. Se actualiza vía
    `bodega.services.comprar_material` (entrada) y
    `bodega.services.recibir_lote` (salida al confeccionarse productos).
    """
    bodega = models.ForeignKey(Bodega, on_delete=models.CASCADE, related_name='stock_materiales')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name='stock_bodegas')
    cantidad = models.PositiveIntegerField(default=0, help_text='Rollos disponibles')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('bodega', 'material')]
        ordering = ['bodega__nombre', 'material__nombre']

    def __str__(self):
        return f'{self.bodega} · {self.material} · {self.cantidad} rollos'


class MovimientoMaterial(models.Model):
    """Audit log de cambios de stock de materiales en una bodega.

    - ENTRADA: compra de rollos al proveedor. Lleva `costo_total` real pagado.
    - SALIDA: rollos enviados a confeccionar (consumidos para producir prendas).
    """

    ENTRADA = 'entrada'
    SALIDA = 'salida'
    TIPO_CHOICES = [
        (ENTRADA, 'Entrada'),
        (SALIDA, 'Salida'),
    ]

    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='movimientos_material')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name='movimientos')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField(help_text='Rollos')
    costo_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='CLP total pagado/movido. En entradas = compra; en salidas = 0 (la plata sale al pagar la confección, no acá).',
    )
    referencia = models.CharField(max_length=120, blank=True, help_text='Descripción libre (proveedor, factura, lote, etc)')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movimientos_material',
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado']

    def __str__(self):
        return f'{self.creado:%d-%m-%Y} · {self.tipo} · {self.cantidad} × {self.material}'


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

    def __str__(self):
        item = self.variante or self.producto
        signo = '+' if self.tipo == self.ENTRADA else '−'
        return f'{self.get_tipo_display()} {signo}{self.cantidad} {item} @ {self.tienda}'
