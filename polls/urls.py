from django.conf.urls import url


from . import views

app_name = 'polls'
urlpatterns = [
	# ej: /polls/
    url(r'^$', views.IndexView.as_view(), name='index'),
    # ej: /polls/5
    url(r'^(?P<pk>[0-9]+)/$', views.DetallesView.as_view(), name='detalles'),
    # ej: /polls/5/resultados
    url(r'^(?P<pk>[0-9]+)/resultados/$', views.ResultadosView.as_view(), name='resultados'),
    # ej: /polls/5/voto
    url(r'^(?P<id_pregunta>[0-9]+)/voto/$', views.voto, name='voto'),
    url(r'^about/$', views.AboutView.as_view()),
]


# Tener cuidad con los nombres de las vistas y los nombres de los templates... deben coincidir el nombre.