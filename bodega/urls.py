from django.urls import path

from . import views

app_name = 'bodega'

urlpatterns = [
    path('', views.StockView.as_view(), name='stock'),
    path('reponer/', views.reponer_stock, name='reponer'),

    # Catálogo (CRUD desde el backoffice — Fase Ñ).
    path('productos/', views.lista_productos, name='lista_productos'),
    path('productos/nuevo/', views.producto_nuevo, name='producto_nuevo'),
    path('productos/<int:pk>/editar/', views.producto_editar, name='producto_editar'),
    path('productos/<int:pk>/variantes/', views.variantes_lista, name='variantes'),
    path('productos/<int:pk>/variantes/nueva/', views.variante_nueva, name='variante_nueva'),
    path('productos/<int:pk>/variantes/<int:var_pk>/editar/',
         views.variante_editar, name='variante_editar'),
    path('productos/<int:pk>/variantes/<int:var_pk>/borrar/',
         views.variante_borrar, name='variante_borrar'),
]
