from django.db import models
import bodega

# Create your models here.

class StockTienda(models.Model):
	fecha_hora_creacion	= models.DateTimeField(auto_now_add = True)
	producto 			= models.ForeignKey(bodega.models.Producto, null = True)
	cantidad_contada 	= models.PositiveIntegerField(default=0)
	def __str__(self):
		return str(self.producto.nombre +" "+ str(self.fecha_hora_creacion))

class Tienda(models.Model):
	nombre_organizacion	= models.CharField(max_length=200, unique=True)
	direccion			= models.CharField(max_length=200, null = True, blank=True)
	stock 				= models.ForeignKey(StockTienda)
	telefono_contacto	= models.PositiveIntegerField()
	correo_contacto 	= models.EmailField()
	rut_organizacion	= models.CharField(max_length=20)
	def __str__(self):
		return str(self.nombre_organizacion +" "+ self.direccion)


class ReciboVenta(models.Model):
	fecha_hora_venta	= models.DateTimeField(auto_now_add = True)
	usuario_vendedor	= models.IntegerField(null=True, blank=True)
	tienda 				= models.ForeignKey(Tienda)

class ReciboVentaDetalle(models.Model):
	id_reciboVenta		= models.ForeignKey(ReciboVenta)
	id_producto			= models.ForeignKey(bodega.models.Producto)
	cantidad_vendida	= models.PositiveIntegerField()
	precio_calculado	= models.PositiveIntegerField()


class HistoriaVentas(models.Model):
	fecha_venta			= models.DateTimeField(auto_now_add = True)	
	id_reciboVenta		= models.ForeignKey(ReciboVenta)
	monto_venta			= models.PositiveIntegerField()	