from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils import timezone


class Familia(models.Model):
    """Categoría de productos (ej: Buzos, Poleras, Perfumes)."""
    nombre = models.CharField(max_length=60, unique=True)
    descripcion = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Atributo(models.Model):
    """Eje de variante de un producto (ej: Talla, Color, Tamaño)."""
    nombre = models.CharField(max_length=30, unique=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class ValorAtributo(models.Model):
    """Valor concreto de un atributo (ej: S, M, L, 10, 30ml, Azul)."""
    atributo = models.ForeignKey(Atributo, on_delete=models.CASCADE, related_name='valores')
    valor = models.CharField(max_length=60)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [('atributo', 'valor')]
        ordering = ['atributo__nombre', 'orden', 'valor']

    def __str__(self):
        return f'{self.atributo.nombre}: {self.valor}'


class Producto(models.Model):
    """Producto base del catálogo. Puede tener variantes o venderse tal cual."""
    familia = models.ForeignKey(Familia, on_delete=models.PROTECT, related_name='productos')
    nombre = models.CharField(max_length=200, unique=True)
    descripcion = models.TextField(blank=True)
    precio_base = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    precio_costo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Costo unitario para valorización de activos',
    )
    tiene_variantes = models.BooleanField(
        default=False,
        help_text='Si es True, el producto se vende a través de sus ProductoVariante',
    )
    activo = models.BooleanField(default=True)
    imagen = models.ImageField(upload_to='productos/', null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class ProductoVariante(models.Model):
    """SKU vendible. Cada combinación de valores de atributo es una variante."""
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='variantes')
    sku = models.CharField(max_length=60, unique=True)
    precio_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Si se define, reemplaza el precio_base del producto',
    )
    activa = models.BooleanField(default=True)
    valores = models.ManyToManyField(ValorAtributo, related_name='variantes', blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['producto__nombre', 'sku']

    def __str__(self):
        return f'{self.producto.nombre} [{self.sku}]'

    @property
    def precio(self):
        return self.precio_override if self.precio_override is not None else self.producto.precio_base


class Oferta(models.Model):
    """Descuento aplicable a un producto o variante, por canal y ventana de fechas."""

    CANAL_PRESENCIAL = 'presencial'
    CANAL_ONLINE = 'online'
    CANAL_AMBOS = 'ambos'
    CANAL_CHOICES = [
        (CANAL_PRESENCIAL, 'Presencial'),
        (CANAL_ONLINE, 'Online'),
        (CANAL_AMBOS, 'Ambos'),
    ]

    TIPO_PORCENTAJE = 'porcentaje'
    TIPO_MONTO = 'monto'
    TIPO_CHOICES = [
        (TIPO_PORCENTAJE, 'Porcentaje'),
        (TIPO_MONTO, 'Monto fijo'),
    ]

    nombre = models.CharField(max_length=100)
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, null=True, blank=True, related_name='ofertas'
    )
    variante = models.ForeignKey(
        ProductoVariante, on_delete=models.CASCADE, null=True, blank=True, related_name='ofertas'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    canal = models.CharField(max_length=20, choices=CANAL_CHOICES, default=CANAL_AMBOS)
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    activa = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_inicio']
        constraints = [
            CheckConstraint(
                check=Q(producto__isnull=False) | Q(variante__isnull=False),
                name='oferta_tiene_target',
            ),
            CheckConstraint(
                check=Q(fecha_fin__gte=models.F('fecha_inicio')),
                name='oferta_fechas_coherentes',
            ),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        if not self.producto and not self.variante:
            raise ValidationError('Debe aplicar a un producto o una variante.')

    def vigente(self, momento=None):
        momento = momento or timezone.now()
        return self.activa and self.fecha_inicio <= momento <= self.fecha_fin

    def aplica_a_canal(self, canal):
        return self.canal == canal or self.canal == self.CANAL_AMBOS
