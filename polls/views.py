# coding=utf-8
# Ìmports django
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.template import loader
from django.urls import reverse
from django.views import generic
from django.views.generic import TemplateView

# import modelos
from .models import Pregunta, Opcion

# Vistas creadas

class IndexView(generic.ListView):
	template_name = 'polls/index.html'
	context_object_name = 'ultimas_respuestas'

	def get_queryset(self):
		""" Retorna las ulimas 5 publicaciones"""
		return Pregunta.objects.order_by('fecha_pub')[:5]

#	ultimas_respuestas = Pregunta.objects.order_by('fecha_pub')[:5]

#	output = ', '.join([p.texto_pregunta for p in ultimas_respuestas])
#	return HttpResponse(output)
#	template = loader.get_template('polls/index.html')

# 	Una formade hacerlo

#	context = {
#		'ultimas_respuestas': ultimas_respuestas,
#	}
#	return HttpResponse(template.render(context,request))

# 	Otra forma de hacerlo 
#	ya que es comun cargar un template, llenar el contenido y retornar un HttpResponse

#	context = {'ultimas_respuestas': ultimas_respuestas}
#	return render(request, 'polls/index.html', context)

class AboutView(TemplateView):
	template_name = "polls/about.html"

class DetallesView(generic.DetailView):
	model = Pregunta
	template_name = 'polls/detalle.html'
		

#def detalles(request, id_pregunta):
	# inicializa el modelo de pregunta con el parametro id
#	try:
#		pregunta = Pregunta.objects.get(pk=id_pregunta)

	# si no encuentra el elemento en la BD con esa id 
	# entonces tampoco podemos acceder a la vista
	# levantamos un error 404
#	except Pregunta.NoExiste:
#		raise Http404("La pregunta no existe!")
#	return HttpResponse("Estas buscando la pregunta %s." % id_pregunta)
#	return render(request, 'polls/detalle.html', {'pregunta': pregunta})

	# el codigo anterior se puede realizar de manera mas acotada agregando el atajo 
	# django.shortcuts import get_object_or_404

#	pregunta = get_object_or_404(Pregunta, pk=id_pregunta)
#	return render(request, 'polls/detalle.html', {'pregunta': pregunta})

class ResultadosView(generic.DetailView):
	model = Pregunta
	template_name = 'polls/resultados.html'

#def resultados(request, id_pregunta):
#	respuesta = "Estas buscando los resultados de la pregunta %s"
#	return HttpResponse(respuesta % id_pregunta)

def voto(request,id_pregunta):
	pregunta = get_object_or_404(Pregunta, pk=id_pregunta)

	try:
		opcion_seleccionada = pregunta.opcion_set.get(pk=request.POST['opcion'])
	except (KeyError, Opcion.DoesNotExist):
		# Muestra nuevamente la pregunta
		return render(request, 'polls/detalle.html', {'pregunta': pregunta, 'error_message':"No seleccionaste ninguna opción"})
	else:
		opcion_seleccionada.votos += 1
		opcion_seleccionada.save()
		# Siempre retornar un HttpResponseRedirect despues 
		# una operacion POST. Esto previene que los datos se dupliquen
		# despues de que se presiona el boton atras.
	return HttpResponseRedirect(reverse('polls:resultados', args=(pregunta.id,)))

def resultados(request, id_pregunta):
	pregunta = get_object_or_404(Pregunta, pk=id_pregunta)
	return render(request, 'polls/resultados.html', {'pregunta':pregunta})