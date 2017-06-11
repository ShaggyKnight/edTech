from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils import timezone

# Los productos seran los que se venderan en las tiendas
# poseen familias de productos a modo de categorizarlos


class Familia(models.Model):
	""" Familias de productos, cada producto pertenece a una familia"""
	nombre = models.CharField(max_length=30)

	def __str__(self):
		return self.nombre

class Producto(models.Model):
	""" Define los productos del sistema, los productos son articulos terminados """
	nombre = models.CharField(max_length=30)
	descripcion = models.CharField(max_length=200)
	precio = models.FloatField(default=0)
	familia =models.ForeignKey(Familia)

	#ultima_modificacion = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.nombre

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
	largo = models.IntegerField()
	producto = models.ForeignKey(Producto, on_delete=models.CASCADE)

class Material(models.Model):
	""" los materiales pueden ser productos por si mismos o material para otro"""
	nombre = models.CharField(max_length=30)
	descripcion = models.CharField(max_length=200)
	precio = models.FloatField(default=0)
	mat_producto = models.ManyToManyField(Producto)




######## Control de proveedores ###################

class Proveedor(models.Model):
	""" Informacion reelevante de los proveedores"""
	nombre = models.CharField(max_length=30)
	email = models.EmailField()
	direccion = models.CharField(max_length=50)
	telefono = models.IntegerField()
	rut = models.CharField(max_length=15)

class Ordencompra(models.Model):
	fecha_orden = models.DateTimeField('fecha emisión')

	def emitida_recientemente(self):
		return self.fecha_orden >= timezone.now() - datetime.timedelta(days=1)

class Ordenlinea(models.Model):
	orden = models.ForeignKey(Ordencompra, on_delete=models.CASCADE)



##### Control de ventas #####

class Cliente(models.Model):
	""" Contiene los clientes de los cuales se desea mantener informacion"""
	nombre = models.CharField(max_length=30)
	email = models.EmailField()
	direccion = models.TextField()
	telefono = models.IntegerField()


###### Modulo de punto de venta #######

class Tienda(models.Model):
	""" Descripcion de las tiendas asociadas"""
	nombre = models.CharField(max_length=30)
	def __str__(self):
		return self.nombre


class Stock(models.Model):
	""" controla el stock de productos que tiene una tienda"""
	producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
	tienda = models.ForeignKey(Tienda)
	cantidad = models.IntegerField(default =0)

class Historial(models.Model):
	fecha_transaccion = models.DateTimeField('tiempo transaccion')


class Transaccion(models.Model):
	descripcion = models.CharField(max_length=100);

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
