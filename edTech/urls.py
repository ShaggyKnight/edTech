"""edTech URL Configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from . import views

# Branding del Django admin (Fase M).
admin.site.site_header = 'Ideas Boutique — Administración'
admin.site.site_title  = 'Ideas Boutique'
admin.site.index_title = 'Panel de control'

urlpatterns = [
    path('', views.index, name='index'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('cuenta/', include('django.contrib.auth.urls')),
    path('cuenta/', include('accounts.urls')),
    path('bodega/', include('bodega.urls')),
    path('pos/', include('pos.urls')),
    path('tienda/', include('ecommerce.urls')),
    path('reportes/', include('reportes.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
