import datetime

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

# Año de fundación de Ideas Boutique — punto único de verdad para que
# el hero del sitio nunca se desactualice (ver Sprint 1 · 1.1 del roadmap).
FUNDACION = 1987


def index(request):
    contexto = {
        'anios_negocio': datetime.date.today().year - FUNDACION,
        'fundacion': FUNDACION,
    }
    return render(request, 'index.html', contexto)


def info(request):
    """Página de ayuda con secciones: envíos, cambios, tallas, contacto.

    BUG-008: el footer apuntaba todos los links de Ayuda a anchors del
    landing (#visitanos) que no tenían el contenido prometido. Esta vista
    consolida los 4 temas en /info/ con anchors reales y copy chileno.
    """
    return render(request, 'info.html')


# Version de los textos legales. Al cambiar el fondo de la politica de
# privacidad o de los terminos, subir la version y la fecha (la ley pide
# informar la version vigente).
TEXTOS_LEGALES_VERSION = '1.0'
TEXTOS_LEGALES_FECHA = datetime.date(2026, 9, 30)

# Nombre de cada pasarela en los textos legales.
_NOMBRE_PASARELA = {
    'mercadopago': 'Mercado Pago',
    'khipu': 'Khipu',
    'klap': 'KLAP',
    'mock': 'simulador de pagos',
}


def _contexto_legal(request):
    """Datos compartidos por /privacidad/ y /terminos/.

    Los plazos salen de settings (los mismos que aplica el comando
    `purgar_datos_vencidos`) y los medios de pago, de las pasarelas
    activas: el texto publicado no puede quedar desalineado del sistema.
    """
    from django.conf import settings as dj_settings

    from ecommerce.cart import Cart
    from ecommerce.gateways import get_gateways_activos

    def meses(dias):
        return max(1, round(dias / 30))

    activos = [g.provider for g in get_gateways_activos()]
    # Plataformas que procesan el pago (la transferencia directa no es una).
    pasarelas = [_NOMBRE_PASARELA.get(p, p) for p in activos if p != 'transferencia']
    medios_pago = pasarelas + (
        ['transferencia bancaria directa'] if 'transferencia' in activos else [])

    return {
        'items_count': Cart(request.session).items_count,
        'pasarelas': pasarelas,
        'medios_pago': medios_pago,
        'version_legal': TEXTOS_LEGALES_VERSION,
        'fecha_legal': TEXTOS_LEGALES_FECHA,
        'retencion': {
            'pagados_meses': meses(dj_settings.RETENCION_PEDIDOS_PAGADOS_DIAS),
            'no_pagados_meses': meses(dj_settings.RETENCION_PEDIDOS_NO_PAGADOS_DIAS),
            'avisos_cerrados_meses': meses(dj_settings.RETENCION_AVISOS_CERRADOS_DIAS),
            'avisos_pendientes_meses': meses(dj_settings.RETENCION_AVISOS_PENDIENTES_DIAS),
            'accesos_dias': dj_settings.RETENCION_REGISTROS_ACCESO_DIAS,
        },
    }


def privacidad(request):
    """Politica de privacidad (Ley 21.719, art. 14 ter: informacion que el
    responsable debe tener disponible en forma permanente)."""
    return render(request, 'legal/privacidad.html', _contexto_legal(request))


def terminos(request):
    """Terminos y condiciones de la tienda online."""
    return render(request, 'legal/terminos.html', _contexto_legal(request))


@require_GET
@cache_control(max_age=86400, public=True)
def robots_txt(request):
    """robots.txt: permite indexar la tienda publica y la landing, bloquea
    todo lo que es operativo o privado.

    Servido por Django (no como static file) para que se respete aun si
    cambia el path de los staticfiles, y para que cualquiera que clone
    el repo lo tenga sin pasos extra.
    """
    from django.conf import settings as dj_settings
    lineas = [
        'User-agent: *',
        # Bloquea backoffice, POS, reportes y admin Django. La ruta del
        # admin viene de settings.ADMIN_URL para que el robots.txt siga
        # alineado cuando la cambiamos en prod.
        f'Disallow: /{dj_settings.ADMIN_URL}',
        'Disallow: /bodega/',
        'Disallow: /pos/',
        'Disallow: /reportes/',
        'Disallow: /despacho/',
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
        # Sitemap público (Sprint 3 · 3.2). El host se resuelve relativo al
        # request, por eso usamos build_absolute_uri en runtime.
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
        '',
    ]
    return HttpResponse('\n'.join(lineas), content_type='text/plain; charset=utf-8')
