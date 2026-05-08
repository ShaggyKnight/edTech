from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


def index(request):
    return render(request, 'index.html')


@require_GET
@cache_control(max_age=86400, public=True)
def robots_txt(request):
    """robots.txt: permite indexar la tienda publica y la landing, bloquea
    todo lo que es operativo o privado.

    Servido por Django (no como static file) para que se respete aun si
    cambia el path de los staticfiles, y para que cualquiera que clone
    el repo lo tenga sin pasos extra.
    """
    lineas = [
        'User-agent: *',
        # Bloquea backoffice, POS, reportes y admin Django.
        'Disallow: /admin/',
        'Disallow: /bodega/',
        'Disallow: /pos/',
        'Disallow: /reportes/',
        # Cuenta de staff.
        'Disallow: /cuenta/',
        # Areas transaccionales / privadas del cliente — no aportan en SEO
        # y pueden generar contenido duplicado o confidencial indexado.
        'Disallow: /tienda/carrito/',
        'Disallow: /tienda/checkout/',
        'Disallow: /tienda/pedido/',
        'Disallow: /tienda/mock-pago/',
        'Disallow: /tienda/cuenta/',
        # Endpoints AJAX/JSON.
        'Disallow: /tienda/buscar.json',
        '',
        # Sugerencia de host canonico — el dueno actualiza el dominio cuando
        # publique. Mientras tanto queda como hint informativo.
        '# Sitemap: https://www.ideasboutique.cl/sitemap.xml',
        '',
    ]
    return HttpResponse('\n'.join(lineas), content_type='text/plain; charset=utf-8')
