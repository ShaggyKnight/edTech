from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils import timezone


class Familia(models.Model):
    """Categoría de productos (ej: Buzos, Poleras, Perfumes)."""
    nombre = models.CharField(max_length=60, unique=True)
    nombre_buscable = models.CharField(max_length=60, db_index=True, blank=True)
    descripcion = models.TextField(blank=True)
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


class Colegio(models.Model):
    """Institución educativa para la que confeccionamos uniformes.

    Los uniformes están bordados con la insignia, así que el colegio es
    estructural, no un texto suelto. Permite filtros precisos y catálogo
    público por colegio.
    """
    nombre = models.CharField(max_length=120, unique=True)
    nombre_buscable = models.CharField(max_length=120, db_index=True, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    telefono_contacto = models.CharField(max_length=30, blank=True)
    email_contacto = models.EmailField(blank=True)
    logo = models.ImageField(
        upload_to='colegios/', null=True, blank=True,
        help_text='Insignia del colegio para mostrar en el catálogo público',
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Colegio'
        verbose_name_plural = 'Colegios'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        from edTech.search import normalize_text
        self.nombre_buscable = normalize_text(self.nombre)
        super().save(*args, **kwargs)


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
    colegio = models.ForeignKey(
        Colegio,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='productos',
        help_text='Solo para uniformes escolares — colegio cuya insignia llevan bordada',
    )
    nombre = models.CharField(max_length=200, unique=True)
    nombre_buscable = models.CharField(max_length=200, db_index=True, blank=True)
    descripcion_buscable = models.TextField(blank=True, db_index=False)
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
    codigo_barras = models.CharField(
        max_length=32, unique=True, null=True, blank=True,
        help_text='EAN-13 / Code128. Si el producto tiene variantes el código '
                  'vive a nivel de variante; este campo solo se usa para '
                  'productos sin variantes (ej. perfumes).',
    )
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        from edTech.search import normalize_text
        self.nombre_buscable = normalize_text(self.nombre)
        self.descripcion_buscable = normalize_text(self.descripcion)
        super().save(*args, **kwargs)

    @property
    def precio_minimo(self):
        """Precio mínimo entre variantes activas (override) o precio_base.

        Útil para mostrar "Desde $X" en el catálogo cuando los precios
        varían por talla. Si no tiene variantes o todas usan precio_base,
        devuelve precio_base.
        """
        if not self.tiene_variantes:
            return self.precio_base
        precios = []
        for v in self.variantes.filter(activa=True):
            precios.append(v.precio_override or self.precio_base)
        return min(precios) if precios else self.precio_base

    @property
    def precios_varian_por_variante(self):
        """True si las variantes activas tienen precios distintos entre sí.

        Permite mostrar "Desde $X" solo cuando aporta info: si todas las
        tallas cuestan lo mismo, mostramos el precio único.
        """
        if not self.tiene_variantes:
            return False
        precios = set()
        for v in self.variantes.filter(activa=True):
            precios.add(v.precio_override or self.precio_base)
        return len(precios) > 1


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
    codigo_barras = models.CharField(
        max_length=32, unique=True, null=True, blank=True,
        help_text='EAN-13 / Code128. Para uniformes confeccionados se genera '
                  'automáticamente con prefijo 200 (rango GS1 reservado a uso '
                  'interno) — ver catalogo.barcode.generar_codigo_interno.',
    )
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
