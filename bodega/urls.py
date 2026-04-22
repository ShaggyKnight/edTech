from django.urls import path

from . import views

app_name = 'bodega'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('<int:pk>/', views.DetallesView.as_view(), name='detalles'),
]
