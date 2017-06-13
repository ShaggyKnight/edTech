from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils import timezone

# Modelos para el control de bodega

class Familia(models.Model):
	""" Familias de productos, cada producto pertenece a una familia"""
	nombre = models.CharField(max_length=30)

	def __str__(self):
		return self.nombre

class Producto(models.Model):
	""" Define los productos del sistema, los productos son articulos terminados """
	descripcion = models.CharField(max_length=200)
	precio = models.FloatField(default=0)
	familia =models.ForeignKey(Familia)
	
	#ultima_modificacion = models.DateTimeField(auto_now=True)
	def __str__(self):
		return self.descripcion


class ProductoLinea(models.Model):
	TALLA_TAMAÑO =(
		('S', 'Small'),
		('M', 'Medium'),
		('L', 'Large')
	)
	talla = models.CharField(max_length=1, choices=TALLA_TAMAÑO)
	talla_numero = models.CharField(max_length=2)
	largo = models.PositiveIntegerField(default=0)
	producto = models.OneToOneField(Producto)

	
class Material(models.Model):
	""" los materiales pueden ser productos por si mismos o material para otro"""
	nombre = models.CharField(max_length=30)
	descripcion = models.CharField(max_length=200)
	precio = models.FloatField(default=0)
	mat_producto = models.ManyToManyField(Producto)


##### Manejo de materiales #####

class Bodega(models.Model):
	nombre = models.CharField(max_length=30)
	def __str__(self):
		return self.nombre

class Inventario(models.Model):
	bodega = models.ForeignKey(Bodega)
	fecha_inventario = models.DateTimeField('fecha inventario')

	def inventario_reciente(self):
		return	self.fecha_inventario >= timezone.now() - datetime.timedelta(days=1)

class Inventariolinea(models.Model):
	inventario = models.ForeignKey(Inventario, on_delete=models.CASCADE)
	producto = models.ForeignKey(Producto)
	cantidad_contada = models.IntegerField(default=0)
	observacion = models.CharField(max_length=200)
