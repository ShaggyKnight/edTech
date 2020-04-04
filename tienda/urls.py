from django.conf.urls import url
from django.conf import settings
from django.conf.urls.static import static

from . import views

app_name = 'tienda'
urlpatterns = [
	#  /tienda/
	url(r'^$', views.IndexView.as_view(), name='index'),
    #url(r'^$', views.index, name='index')

]+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
