from decimal import Decimal
from functools import cached_property

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

    @cached_property
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

    @cached_property
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

    # ── Precios con oferta para canal online ──────────────────────────
    # Usadas por el catálogo público y la PDP para mostrar el precio
    # con descuento aplicado antes de llegar al carrito. La lógica vive
    # en catalogo.precios (compartida con cart presencial/online).
    #
    # cached_property: los catalogos llaman estas 3 properties por cada
    # card (tiene_oferta_online + precio_oferta_online +
    # descuento_porcentaje_online). Sin cache, eran 3 queries por
    # producto. Con cache, 1 sola consulta por producto + reusos.

    @cached_property
    def _mejor_oferta_online(self):
        """Mejor oferta vigente para canal online sobre este producto
        (no toca variantes). Devuelve (descuento_unit, oferta) o
        (Decimal('0'), None) si no hay.
        """
        from catalogo.precios import mejor_descuento_unitario
        return mejor_descuento_unitario(self, Oferta.CANAL_ONLINE)

    @property
    def precio_oferta_online(self):
        """Precio con oferta aplicada. Si no hay oferta vigente,
        devuelve el `precio_minimo` (para productos con variantes
        baratas/caras, refleja el "desde")."""
        desc, oferta = self._mejor_oferta_online
        base = self.precio_minimo
        if not oferta or desc <= 0:
            return base
        return base - desc

    @property
    def tiene_oferta_online(self):
        _, oferta = self._mejor_oferta_online
        return oferta is not None

    @property
    def descuento_porcentaje_online(self):
        """Porcentaje (int 0..100) del descuento aplicado. 0 si no hay
        oferta. Útil para el badge "−15%" en card y PDP."""
        desc, oferta = self._mejor_oferta_online
        if not oferta or desc <= 0:
            return 0
        base = self.precio_minimo
        if base <= 0:
            return 0
        return int(round((desc / base) * 100))

    # ── Resenas (Bloque 9) ────────────────────────────────────────────

    @cached_property
    def resenas_publicas(self):
        """Resenas aprobadas, mas recientes primero."""
        return list(self.resenas.filter(estado='aprobada'))

    @cached_property
    def resena_promedio(self):
        """Promedio de estrellas (float 1.0..5.0), o None si no hay."""
        resenas = self.resenas_publicas
        if not resenas:
            return None
        return sum(r.estrellas for r in resenas) / len(resenas)

    @property
    def resena_promedio_redondo(self):
        """Promedio redondeado al entero — para mostrar N estrellas pintadas."""
        avg = self.resena_promedio
        return int(round(avg)) if avg is not None else 0

    @property
    def resena_count(self):
        return len(self.resenas_publicas)


class Resena(models.Model):
    """Reseña de un producto por un cliente (con o sin cuenta).

    Bloque 9: para mostrar reseñas reales en el PDP (en vez del
    placeholder "Nuevo · sin reseñas aún"). Moderacion manual via
    `estado` — se publica solo lo que la duena aprueba. No exponemos
    el email del cliente; solo `nombre_publico` (puede ser nick).

    `recibo` opcional: si la duena lo enlaza al ReciboVenta del
    cliente, mostramos badge "Compra verificada".
    """
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_APROBADA = 'aprobada'
    ESTADO_RECHAZADA = 'rechazada'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente de revisión'),
        (ESTADO_APROBADA, 'Aprobada (visible)'),
        (ESTADO_RECHAZADA, 'Rechazada'),
    ]

    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name='resenas',
    )
    estrellas = models.PositiveSmallIntegerField(
        choices=[(i, f'{i} estrella{"s" if i != 1 else ""}') for i in range(1, 6)],
    )
    titulo = models.CharField(max_length=120, blank=True)
    texto = models.TextField()
    nombre_publico = models.CharField(
        max_length=80,
        help_text='Nombre o nick que se publica con la resena.',
    )
    cliente_email = models.EmailField(
        help_text='Email del autor — NO se publica. Solo para contactar '
                  'si la dueña necesita validar.',
    )
    estado = models.CharField(
        max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE,
        db_index=True,
    )
    # FK opcional al recibo de compra — habilita el badge "verificada".
    recibo = models.ForeignKey(
        'pos.ReciboVenta', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='resenas',
    )
    creado = models.DateTimeField(auto_now_add=True)
    moderada = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado']
        constraints = [
            CheckConstraint(
                check=Q(estrellas__gte=1) & Q(estrellas__lte=5),
                name='resena_estrellas_1_5',
            ),
        ]

    def __str__(self):
        return f'{self.nombre_publico} · {self.estrellas}★ · {self.producto.nombre}'


class ProductoImagen(models.Model):
    """Imagen adicional para la galeria del PDP.

    `Producto.imagen` (el campo de la portada) se conserva como antes —
    es la que sale en cards de catalogo, busqueda, OG image y emails.
    Estas imagenes solo aparecen en el detalle de producto.

    `orden` determina como se muestran (asc): la primera es la mas
    grande, las siguientes son thumbnails. Si el cliente sube 4
    imagenes con orden 1/2/3/4 se renderizan en ese orden.
    """
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name='imagenes',
    )
    imagen = models.ImageField(upload_to='productos/galeria/')
    orden = models.PositiveSmallIntegerField(
        default=0,
        help_text='Orden de visualizacion en la galeria (asc).',
    )
    alt = models.CharField(
        max_length=200, blank=True,
        help_text='Texto alternativo para accesibilidad. Si vacio, '
                  'se usa el nombre del producto.',
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['orden', 'creado']
        verbose_name = 'Imagen de galeria'
        verbose_name_plural = 'Imagenes de galeria'

    def __str__(self):
        return f'{self.producto.nombre} · img #{self.pk}'


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

    # ── Precios con oferta para canal online ──────────────────────────

    @cached_property
    def _mejor_oferta_online(self):
        from catalogo.precios import mejor_descuento_unitario
        return mejor_descuento_unitario(self, 'online')

    @property
    def precio_oferta_online(self):
        desc, oferta = self._mejor_oferta_online
        if not oferta or desc <= 0:
            return self.precio
        return self.precio - desc

    @property
    def tiene_oferta_online(self):
        _, oferta = self._mejor_oferta_online
        return oferta is not None

    @property
    def descuento_porcentaje_online(self):
        desc, oferta = self._mejor_oferta_online
        if not oferta or desc <= 0:
            return 0
        if self.precio <= 0:
            return 0
        return int(round((desc / self.precio) * 100))


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
