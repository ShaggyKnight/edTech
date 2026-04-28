from django.urls import path

from . import views

app_name = 'reportes'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('caja/', views.caja, name='caja'),
    path('produccion/', views.produccion, name='produccion'),
]
