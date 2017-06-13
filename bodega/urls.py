from django.conf.urls import url
from django.conf import settings
from django.conf.urls.static import static

from . import views

app_name = 'bodega'
urlpatterns = [
	# ej: /polls/
    url(r'^$', views.IndexView.as_view(), name='index'),
    url(r'^(?P<pk>[0-9]+)/$', views.DetallesView.as_view(), name='detalles')
    # ej: /polls/5
#    url(r'^(?P<pk>[0-9]+)/$', views.DetallesView.as_view(), name='detalles'),
    # ej: /polls/5/resultados
#    url(r'^(?P<pk>[0-9]+)/resultados/$', views.ResultadosView.as_view(), name='resultados'),
    # ej: /polls/5/voto
#    url(r'^(?P<id_pregunta>[0-9]+)/voto/$', views.voto, name='voto'),
#    url(r'^about/$', views.AboutView.as_view()),
]+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
