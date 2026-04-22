import datetime

from django.db import models
from django.utils import timezone


class Bodega(models.Model):
    """Bodegas de almacenamiento de productos."""
    nombre = models.CharField(max_length=30, unique=True)
    ubicacion = models.CharField(max_length=30, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre


class Familia(models.Model):
    """Familias de productos. Ej: Buzos, Poleras, Chalecos, Perfumes."""
    nombre = models.CharField(max_length=30, unique=True)
    descripcion = models.TextField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre


class Grupo(models.Model):
    nombre_grupo = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.nombre_grupo


class Producto(models.Model):
    """Artículos terminados que se venden."""
    TALLA_TAMANO = (
        ('S', 'Small'),
        ('M', 'Medium'),
        ('L', 'Large'),
    )
    familia = models.ForeignKey(Familia, on_delete=models.PROTECT, related_name='productos')
    nombre = models.CharField(max_length=200, unique=True)
    descripcion = models.CharField(max_length=300, null=True, blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    talla = models.CharField(max_length=1, choices=TALLA_TAMANO, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre


class Atributo(models.Model):
    nombre = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.nombre


class ProductoAtributo(models.Model):
    """Relación producto <-> atributo (ej: color, colegio, diseño)."""
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='atributos')
    atributo = models.ForeignKey(Atributo, on_delete=models.PROTECT)
    valor = models.CharField(max_length=30, null=True, blank=True)

    def __str__(self):
        return f'{self.producto} - {self.atributo}'


class ProductoAtributoValor(models.Model):
    producto_atributo = models.ForeignKey(
        ProductoAtributo, on_delete=models.CASCADE, related_name='valores'
    )
    valor = models.CharField(max_length=30, null=True, blank=True)


class Material(models.Model):
    """Materiales necesarios para elaborar un producto."""
    nombre = models.CharField(max_length=30)
    descripcion = models.CharField(max_length=200)
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_proveedor = models.PositiveIntegerField(default=0)
    mat_producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='materiales')
    largo = models.PositiveIntegerField(default=0, null=True, blank=True)
    comerciable = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.nombre} - {self.descripcion}'


class Inventario(models.Model):
    """Conteo de inventario en una bodega."""
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='inventarios')
    descripcion = models.TextField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.creado.strftime('%d-%m-%Y %H:%M')

    def inventario_reciente(self):
        return self.creado >= timezone.now() - datetime.timedelta(days=1)


class Inventariolinea(models.Model):
    inventario = models.ForeignKey(Inventario, on_delete=models.CASCADE, related_name='lineas')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad_contada = models.IntegerField(default=0)

    def __str__(self):
        return self.producto.nombre


class Proveedor(models.Model):
    nombre_proveedor = models.CharField(max_length=30, unique=True)
    direccion = models.CharField(max_length=30, null=True, blank=True)
    telefono = models.CharField(max_length=10)
    correo = models.EmailField()
    cuenta_bco = models.CharField(max_length=20)
    rut_proveedor = models.CharField(max_length=20, unique=True)
    nombre_contacto = models.CharField(max_length=20)

    def __str__(self):
        return self.nombre_proveedor
