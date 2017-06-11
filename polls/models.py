from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils import timezone

# Create your models here.

@python_2_unicode_compatible
class Pregunta(models.Model):
	texto_pregunta = models.CharField(max_length=200)
	fecha_pub = models.DateTimeField('fecha publicación')

	def __str__(self):
		return self.texto_pregunta

	def fue_publicada_recientemente(self):
		return self.fecha_pub >= timezone.now() - datetime.timedelta(days=1)

@python_2_unicode_compatible
class Opcion(models.Model):
	pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE)
	texto_opcion = models.CharField(max_length=200)
	votos = models.IntegerField(default=0)

	def __str__(self):
		return self.texto_opcion
