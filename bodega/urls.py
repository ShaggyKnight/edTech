from django.urls import path

from . import views

app_name = 'bodega'

urlpatterns = [
    path('', views.StockView.as_view(), name='stock'),
    path('reponer/', views.reponer_stock, name='reponer'),
    path('stock/<int:pk>/set/', views.set_stock, name='set_stock'),

    # Catálogo (CRUD desde el backoffice — Fase Ñ).
    path('productos/', views.lista_productos, name='lista_productos'),
    path('productos/nuevo/', views.producto_nuevo, name='producto_nuevo'),
    path('productos/<int:pk>/editar/', views.producto_editar, name='producto_editar'),
    path('productos/<int:pk>/set-precio/', views.set_precio, name='set_precio'),
    path('productos/<int:pk>/toggle-activo/', views.producto_toggle_activo, name='producto_toggle_activo'),
    path('productos/bulk/', views.productos_bulk_action, name='productos_bulk_action'),
    path('productos/<int:pk>/variantes/', views.variantes_lista, name='variantes'),
    path('productos/<int:pk>/variantes/nueva/', views.variante_nueva, name='variante_nueva'),
    path('productos/<int:pk>/variantes/<int:var_pk>/editar/',
         views.variante_editar, name='variante_editar'),
    path('productos/<int:pk>/variantes/<int:var_pk>/borrar/',
         views.variante_borrar, name='variante_borrar'),

    # Materiales (Fase Ñ.2).
    path('materiales/', views.lista_materiales, name='lista_materiales'),
    path('materiales/bulk/', views.materiales_bulk_action, name='materiales_bulk_action'),
    path('materiales/nuevo/', views.material_nuevo, name='material_nuevo'),
    path('materiales/<int:pk>/editar/', views.material_editar, name='material_editar'),
    path('materiales/<int:pk>/rendimientos/', views.rendimientos_lista, name='rendimientos'),
    path('materiales/<int:pk>/rendimientos/nuevo/',
         views.rendimiento_nuevo, name='rendimiento_nuevo'),
    path('materiales/<int:pk>/rendimientos/<int:rend_pk>/editar/',
         views.rendimiento_editar, name='rendimiento_editar'),
    path('materiales/<int:pk>/rendimientos/<int:rend_pk>/borrar/',
         views.rendimiento_borrar, name='rendimiento_borrar'),

    # Etiquetas imprimibles con codigo de barras.
    path('etiquetas/', views.etiquetas_seleccionar, name='etiquetas_seleccionar'),
    path('etiquetas/imprimir/', views.etiquetas_imprimir, name='etiquetas_imprimir'),

    # Ofertas (Fase O.1).
    path('ofertas/', views.lista_ofertas, name='lista_ofertas'),
    path('ofertas/bulk/', views.ofertas_bulk_action, name='ofertas_bulk_action'),
    path('ofertas/nueva/', views.oferta_nueva, name='oferta_nueva'),
    path('ofertas/<int:pk>/editar/', views.oferta_editar, name='oferta_editar'),
    path('ofertas/<int:pk>/borrar/', views.oferta_borrar, name='oferta_borrar'),
    path('ofertas/<int:pk>/toggle/', views.oferta_toggle, name='oferta_toggle'),
]
