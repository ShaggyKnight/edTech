from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils import timezone


#	todos los modelos tienen campos comunes como:
#	creado, modificado

class Bodega(models.Model):
	'''
		Bodegas de almacenamiento de productos
	'''
	nombre 			= models.CharField(max_length=30, unique = True)
	ubicacion 		= models.CharField(max_length=30, blank = True)
	creado			= models.DateTimeField(auto_now_add = True)
	modificado		= models.DateTimeField(auto_now = True)
	def __str__(self):
		return self.nombre



class Familia(models.Model):
	""" 
		Familias de productos, cada producto pertenece a una familia
		ej: Buzos, Poleras, Chalecos
	"""
	nombre		= models.CharField(max_length=30, unique = True)
	descripcion 		= models.TextField(null = True, blank= True)
	creado				= models.DateTimeField(auto_now_add = True)
	modificado			= models.DateTimeField(auto_now = True)
	def __str__(self):
		return self.nombre


class Grupo(models.Model):
	nombre_grupo		= models.CharField(max_length=30, unique=True)
	def __str__(self):
		return self.nombre_grupo

class Producto(models.Model):
	""" 
		Define los productos del sistema, los productos son articulos terminados 
	"""
	TALLA_TAMANO 	=(	
					('S', 'Small'),
					('M', 'Medium'),
					('L', 'Large')
					)			
	familia 		= models.ForeignKey(Familia)
	nombre 			= models.CharField(max_length=200, unique=True)
	descripcion 	= models.CharField(max_length=300, null = True, blank= True)
	precio 			= models.FloatField(default=0)
	talla 			= models.CharField(max_length=1, choices=TALLA_TAMANO)
	creado			= models.DateTimeField(auto_now_add = True)
	modificado		= models.DateTimeField(auto_now = True)
	def __str__(self):
		return self.nombre

class Atributo(models.Model):
	""" 
		Define los productos del sistema, los productos son articulos terminados 
	"""
	nombre 			= models.CharField(max_length=30, unique= True )
	def __str__(self):
		return self.nombre

class ProductoAtributo(models.Model):
	"""
		contiene la relacion entre producto y atributo
	"""
	producto_id 	= models.ForeignKey(Producto)
	atributo_id 	= models.ForeignKey(Atributo)
	valor 			= models.CharField(max_length=30, null = True, blank=True)

class ProductoAtributoValor(models.Model):
	producto_atributo_id	= models.ForeignKey(ProductoAtributo)
	valor 					= models.CharField(max_length=30, null = True, blank=True)

class Material(models.Model):
	""" 
		Materiales necesarios para un elaborar un producto
	"""
	nombre 			= models.CharField(max_length=30)
	descripcion 	= models.CharField(max_length=200)
	precio 			= models.FloatField(default=0)
	precio_provedor = models.PositiveIntegerField(default=0)
	mat_producto 	= models.ForeignKey(Producto)
	largo			= models.PositiveIntegerField(default=0, null=True, blank= True)
	comerciable 	= models.BooleanField()
	creado			= models.DateTimeField(auto_now_add = True)
	modificado		= models.DateTimeField(auto_now = True)
	def __str__(self):
		return self.nombre + ' - '+  self.descripcion



class Inventario(models.Model):
	'''
		Inventario de productos y materiales
	'''
	
	bodega 				= models.ForeignKey(Bodega)
	descripcion 		= models.TextField(null=True, blank=True)
	creado				= models.DateTimeField(auto_now_add = True)
	modificado			= models.DateTimeField(auto_now = True)
	def __str__(self):
		return self.creado.strftime('%d-%m-%Y %H:%M')	
		
	def inventario_reciente(self):
		return	self.fecha_inventario >= timezone.now() - datetime.timedelta(days=1)



class Inventariolinea(models.Model):
	inventario 			= models.ForeignKey(Inventario)
	producto 			= models.ForeignKey(Producto)
	cantidad_contada 	= models.IntegerField(default=0)

	
	def __str__(self):
		return self.producto.nombre




class Proveedor(models.Model):
	nombre_proveedor 	= models.CharField(max_length=30, unique = True)
	direccion			= models.CharField(max_length=30, null=True, blank= True)
	telefono			= models.CharField(max_length=10)
	correo				= models.EmailField()
	cuenta_bco			= models.CharField(max_length=20)
	rut_proveedor		= models.CharField(max_length=20, unique = True)
	nombre_contacto		= models.CharField(max_length=20)
