from django.urls import path

from . import views, views_cuenta

app_name = 'ecommerce'

urlpatterns = [
    path('', views.catalogo, name='catalogo'),
    path('buscar.json', views.buscar_json, name='buscar_json'),
    path('p/<int:pk>/', views.detalle_producto, name='producto'),
    path('carrito/', views.ver_carrito, name='carrito'),
    path('agregar/', views.agregar, name='agregar'),
    path('actualizar/', views.actualizar, name='actualizar'),
    path('quitar/<path:key>/', views.quitar, name='quitar'),
    path('vaciar/', views.vaciar, name='vaciar'),
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/iniciar/', views.checkout_iniciar, name='checkout_iniciar'),
    path('checkout/retorno/', views.checkout_retorno, name='checkout_retorno'),
    path('pedido/<str:token>/', views.ver_pedido, name='pedido'),
    path('mock-pago/', views.mock_pago, name='mock_pago'),

    # Cuenta del cliente (flujo boutique, separado del login de staff).
    path('cuenta/login/', views_cuenta.BoutiqueLoginView.as_view(), name='login'),
    path('cuenta/logout/', views_cuenta.BoutiqueLogoutView.as_view(), name='logout'),
    path('cuenta/registro/', views_cuenta.registro, name='registro'),
    path('cuenta/pedidos/', views_cuenta.mis_pedidos, name='mis_pedidos'),
]
