from django.urls import path

from . import views

app_name = 'bodega'

urlpatterns = [
    path('', views.StockView.as_view(), name='stock'),
    path('reponer/', views.reponer_stock, name='reponer'),
]
