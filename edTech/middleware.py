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
    """Modos del sitio toggleables via archivos flag (sin restart).

    Cuatro modos, con prioridad MANTENIMIENTO > LANDING > TIENDA_DIRECTA > NORMAL:

    1. MANTENIMIENTO (`settings.MAINTENANCE_FLAG_FILE` existe):
       publico ve "Volvemos pronto" (HTTP 503) en TODOS los paths.
       Google interpreta 503 como "vuelve mas tarde", NO desindexa.

    2. LANDING (`settings.LANDING_ONLY_FLAG_FILE` existe):
       publico SOLO puede ver la home y `/info/`. Cualquier otro path
       (ej. `/tienda/`) redirige a `/`. Util para soft-launch: la
       landing engancha clientes pero la tienda todavia no esta lista.

    3. TIENDA_DIRECTA (`settings.TIENDA_DIRECTA_FLAG_FILE` existe):
       lo contrario de LANDING. El sitio esta 100% abierto, pero la home
       (`/`) redirige directo a la tienda — quien entra a ideasboutique.cl
       cae en el catalogo sin pasar por la landing. Se aplica a TODOS
       (incluido staff): no bloquea nada, solo redirige la raiz, asi que
       el dueno ve lo mismo que el cliente. Para editar/ver la landing en
       vivo, volver a `modo normal`.

    4. NORMAL: site abierto, la home muestra la landing.

    En los modos restrictivos (mantenimiento/landing), estos SIEMPRE pasan:
      - Staff/superusers (para que el dueno siga editando)
      - /admin/ y el ADMIN_URL custom (para loguearse)
      - /cuenta/login/, /cuenta/logout/
      - /static/, /media/, /healthz

    Toggle: `python manage.py modo normal|landing|tienda|mantenimiento`
    O directo: `touch /srv/ideas/MAINTENANCE` etc.
    """

    # Paths que siempre pasan, en cualquier modo. Sin esto la duena no
    # podria loguearse para apagar el modo activo.
    SAFE_PREFIXES = ('/admin/', '/cuenta/login/', '/cuenta/logout/',
                     '/static/', '/media/', '/healthz')

    # Paths publicos en modo LANDING. La home + about-us pages.
    LANDING_OK_PREFIXES = ('/info',)
    LANDING_OK_EXACT = ('/', '/sitemap.xml', '/robots.txt')

    def __init__(self, get_response):
        self.get_response = get_response
        # Cache de paths en atributos: `Path.exists()` es microsegundos
        # pero igual lo evitamos en cada request.
        m_flag = getattr(settings, 'MAINTENANCE_FLAG_FILE', None)
        l_flag = getattr(settings, 'LANDING_ONLY_FLAG_FILE', None)
        t_flag = getattr(settings, 'TIENDA_DIRECTA_FLAG_FILE', None)
        self.mant_path = Path(m_flag) if m_flag else None
        self.landing_path = Path(l_flag) if l_flag else None
        self.tienda_directa_path = Path(t_flag) if t_flag else None
        # Admin URL custom (ej. 'admin-xZqR82/') — agregamos al allowlist.
        admin_url = getattr(settings, 'ADMIN_URL', 'admin/')
        self.admin_prefix = '/' + admin_url.strip('/') + '/'

    def _en_mantenimiento(self):
        return self.mant_path is not None and self.mant_path.exists()

    def _solo_landing(self):
        return self.landing_path is not None and self.landing_path.exists()

    def _tienda_directa(self):
        return (self.tienda_directa_path is not None
                and self.tienda_directa_path.exists())

    def _safe_path(self, path):
        """Allowlist comun a todos los modos restringidos."""
        if path.startswith(self.SAFE_PREFIXES):
            return True
        if path.startswith(self.admin_prefix):
            return True
        return False

    def _landing_ok(self, path):
        """True si el path es publicamente visible en modo LANDING."""
        if self._safe_path(path):
            return True
        if path in self.LANDING_OK_EXACT:
            return True
        if path.startswith(self.LANDING_OK_PREFIXES):
            return True
        return False

    def __call__(self, request):
        # Staff pasa siempre, en cualquier modo — para editar en vivo.
        es_staff = request.user.is_authenticated and request.user.is_staff

        if self._en_mantenimiento():
            if es_staff or self._safe_path(request.path):
                return self.get_response(request)
            return render(request, 'maintenance.html', status=503)

        if self._solo_landing():
            if es_staff or self._landing_ok(request.path):
                return self.get_response(request)
            # Cualquier otra ruta -> la landing. 302 (temporal) porque
            # cuando salgamos del modo landing queremos que vuelvan a
            # poder acceder a esas URLs normalmente.
            from django.shortcuts import redirect
            return redirect('/')

        if self._tienda_directa() and request.path == '/':
            # Solo la raiz se redirige a la tienda; todo lo demas pasa
            # normal. 302 (temporal): al volver a modo normal, `/` debe
            # mostrar la landing de nuevo sin cache agresivo.
            from django.shortcuts import redirect
            from django.urls import reverse
            return redirect(reverse('ecommerce:catalogo'))

        return self.get_response(request)
