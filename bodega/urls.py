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

    # Materiales (Fase Ñ.2).
    path('materiales/', views.lista_materiales, name='lista_materiales'),
    path('materiales/nuevo/', views.material_nuevo, name='material_nuevo'),
    path('materiales/<int:pk>/editar/', views.material_editar, name='material_editar'),
    path('materiales/<int:pk>/rendimientos/', views.rendimientos_lista, name='rendimientos'),
    path('materiales/<int:pk>/rendimientos/nuevo/',
         views.rendimiento_nuevo, name='rendimiento_nuevo'),
    path('materiales/<int:pk>/rendimientos/<int:rend_pk>/editar/',
         views.rendimiento_editar, name='rendimiento_editar'),
    path('materiales/<int:pk>/rendimientos/<int:rend_pk>/borrar/',
         views.rendimiento_borrar, name='rendimiento_borrar'),
]
