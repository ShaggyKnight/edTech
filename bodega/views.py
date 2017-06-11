# coding=utf-8
# Ìmports django
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.template import loader
from django.urls import reverse
from django.views import generic
from django.views.generic import TemplateView

from .models import *
from polls.models import Pregunta

class IndexView(generic.ListView):
	template_name = 'bodega/index.html'
	context_object_name = 'lista_bodega'

	def get_queryset(self):
		""" Retorna las ulimas 5 publicaciones"""
		return Pregunta.objects.order_by('fecha_pub')[:5]

class FamiliasView(generic.ListView):
	model = Familia
	template_name = 'bodega/index2.html'