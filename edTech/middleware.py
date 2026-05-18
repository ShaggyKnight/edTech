"""Middlewares globales del proyecto."""

from pathlib import Path

from django.conf import settings
from django.shortcuts import render


class HtmxMiddleware:
    """Marca `request.htmx = True` cuando el request viene de HTMX.

    HTMX manda el header `HX-Request: true` con cada AJAX. Tener un
    booleano en `request` permite que las views y los templates
    decidan si devuelven HTML completo o un fragment para swap.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.htmx = request.headers.get('HX-Request') == 'true'
        return self.get_response(request)


class MaintenanceMiddleware:
    """Modo mantenimiento toggleable via archivo flag (sin restart).

    Encendido cuando existe `settings.MAINTENANCE_FLAG_FILE` (default
    `/srv/ideas/MAINTENANCE` en prod). Comandos rapidos:

        sudo -u ideas touch /srv/ideas/MAINTENANCE   # encender
        sudo -u ideas rm    /srv/ideas/MAINTENANCE   # apagar

    Tambien `python manage.py mantenimiento on|off`.

    Cuando esta encendido:
      - Superusers y staff pasan normal (para que la duena pueda seguir
        editando la tienda mientras el publico ve la pagina de mantencion).
      - El admin (`/admin/` o el `ADMIN_URL` random) queda accesible.
      - El login (`/cuenta/login/`) tambien, porque sin login no podes
        pasar como superuser.
      - Healthcheck (`/healthz`) pasa libre para que monitoring no
        crea que el site se cayo.
      - El resto recibe el template `maintenance.html` con HTTP 503
        (Google interpreta 503 como "vuelve mas tarde" y NO desindexa).
    """

    # Paths que siempre pasan, incluso en modo mantenimiento. Sin esto
    # la duena no puede loguearse para apagar el modo.
    SAFE_PREFIXES = ('/admin/', '/cuenta/login/', '/cuenta/logout/',
                     '/static/', '/media/', '/healthz')

    def __init__(self, get_response):
        self.get_response = get_response
        # Cache del path en un atributo: chequear `Path.exists()` es
        # microsegundos pero igual lo guardamos.
        flag = getattr(settings, 'MAINTENANCE_FLAG_FILE', None)
        self.flag_path = Path(flag) if flag else None
        # Admin URL custom (ej. 'admin-xZqR82/') — agregamos al allowlist.
        admin_url = getattr(settings, 'ADMIN_URL', 'admin/')
        self.admin_prefix = '/' + admin_url.strip('/') + '/'

    def _en_mantenimiento(self):
        return self.flag_path is not None and self.flag_path.exists()

    def _path_protegido(self, path):
        """True si `path` siempre debe pasar, aun en mantencion."""
        if path.startswith(self.SAFE_PREFIXES):
            return True
        if path.startswith(self.admin_prefix):
            return True
        return False

    def __call__(self, request):
        if not self._en_mantenimiento():
            return self.get_response(request)

        # Staff puede ver el site completo (para editar contenido en vivo).
        if request.user.is_authenticated and request.user.is_staff:
            return self.get_response(request)

        # Paths que necesitamos accesibles para que la duena pueda
        # loguearse y apagar el modo.
        if self._path_protegido(request.path):
            return self.get_response(request)

        return render(request, 'maintenance.html', status=503)
