"""Context processors publicos del sistema.

Cualquier dato que necesiten multiples templates publicos sin tener que
pasarlo explicitamente por cada `render()` va aca.
"""

import datetime

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


def proxima_temporada_uniformes(request):
    """Devuelve la proxima fecha tope de ajustes gratis de uniforme.

    En Chile el ano escolar arranca a inicios de marzo. La promo de
    "ajustes sin costo hasta marzo" es estacional — antes la fecha
    estaba hard-coded ('marzo 2026') y quedo vencida en mayo 2026.

    Logica:
      - Si hoy es enero o febrero -> el corte es marzo del ANO ACTUAL.
      - Si hoy es marzo en adelante -> el corte es marzo del ANO SIGUIENTE
        (asi el banner nunca dice una fecha ya pasada).

    Variables disponibles en templates:
      - `ajustes_fecha_tope`: "marzo 2027" (lowercase, listo para
        usar en el medio de una frase).
      - `ajustes_fecha_tope_short`: "mar 2027" — para sub-strings.
      - `ajustes_ano`: 2027 (int, por si el template quiere otro
        formato).
    """
    hoy = datetime.date.today()
    if hoy.month <= 2:
        ano = hoy.year
    else:
        ano = hoy.year + 1
    return {
        'ajustes_fecha_tope': f'marzo {ano}',
        'ajustes_fecha_tope_short': f'mar {ano}',
        'ajustes_ano': ano,
    }
