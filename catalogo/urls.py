"""URLs del app catalogo. Solo tiene endpoints internos del admin (la
parte publica vive en `ecommerce`)."""

from django.urls import path

from . import views

app_name = 'catalogo'

urlpatterns = [
    # AJAX para el boton "Generar SKU" del admin de ProductoVariante.
    path('admin/sku/sugerir/', views.admin_sugerir_sku, name='admin_sugerir_sku'),
]
