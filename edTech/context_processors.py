"""Context processors publicos del sistema.

Cualquier dato que necesiten multiples templates publicos sin tener que
pasarlo explicitamente por cada `render()` va aca.
"""

from django.conf import settings


def public_settings(request):
    """Expone settings seleccionados del backend a los templates publicos.

    Mantenido minimo a proposito - no exponer secretos. Solo flags y
    valores publicos cuyo conocimiento por el cliente no es problema.
    """
    return {
        'ANALYTICS_DOMAIN': getattr(settings, 'ANALYTICS_DOMAIN', ''),
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
    }
