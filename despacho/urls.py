from django.urls import path

from . import views

app_name = 'despacho'

urlpatterns = [
    path('', views.cola, name='cola'),
    path('pedido/<int:pk>/', views.detalle, name='detalle'),
    path('pedido/<int:pk>/marcar-despachado/', views.marcar_despachado,
         name='marcar_despachado'),
    path('pedido/<int:pk>/desmarcar/', views.desmarcar_despachado,
         name='desmarcar_despachado'),
    # Transferencia directa: confirmar el abono / anular si nunca llegó.
    path('pedido/<int:pk>/confirmar-transferencia/',
         views.confirmar_transferencia, name='confirmar_transferencia'),
    path('pedido/<int:pk>/anular-transferencia/',
         views.anular_transferencia, name='anular_transferencia'),
]
