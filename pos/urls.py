from django.urls import path

from . import views

app_name = 'pos'

urlpatterns = [
    path('', views.home, name='home'),
    path('agregar/', views.agregar, name='agregar'),
    path('actualizar/', views.actualizar, name='actualizar'),
    path('quitar/<path:key>/', views.quitar, name='quitar'),
    path('vaciar/', views.vaciar, name='vaciar'),
    path('checkout/', views.checkout, name='checkout'),
    path('recibo/<int:pk>/', views.ver_recibo, name='recibo'),
    path('ventas/', views.ventas, name='ventas'),
    path('tienda/seleccionar/', views.seleccionar_tienda, name='seleccionar_tienda'),
    path('agregar-stock/', views.agregar_stock, name='agregar_stock'),

    # PWA: manifest + service worker. La ruta del SW vive bajo /pos/ a
    # proposito — su scope queda restringido al POS.
    path('manifest.webmanifest', views.pwa_manifest, name='pwa_manifest'),
    path('sw.js', views.pwa_service_worker, name='pwa_sw'),
]
