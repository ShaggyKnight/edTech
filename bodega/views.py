# coding=utf-8
# Ìmports django
from django.shortcuts 		import get_object_or_404, render
from django.http 			import HttpResponse, Http404, HttpResponseRedirect
from django.template 		import loader
from django.urls 			import reverse
from django.views 			import generic
from django.views.generic 	import TemplateView
from .models 				import *

class IndexView(generic.ListView):
	template_name 		= 'bodega/index.html'
	context_object_name = 'inventario'

	def get_queryset(self):
		""" Retorna las ulimas 5 publicaciones"""
		return Producto.objects.all()

class FamiliasView(generic.ListView):
	model = Familia
	template_name = 'bodega/familias.html'

class ProductoView(generic.ListView):
	template_name = 'bodega/productos.html'
	context_object_name = 'lista_productos'

	def get_queryset(self):
		'''retorna los productos'''
		return Producto.objects.all()

class DetallesView(generic.DetailView):
	model = Producto
	template_name = 'bodega/detalles.html'
