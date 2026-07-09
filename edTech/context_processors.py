"""Context processors publicos del sistema.

Cualquier dato que necesiten multiples templates publicos sin tener que
pasarlo explicitamente por cada `render()` va aca.
"""

from django.conf import settings
from django.utils.functional import SimpleLazyObject


def public_settings(request):
    """Expone settings seleccionados del backend a los templates publicos.

    Mantenido minimo a proposito - no exponer secretos. Solo flags y
    valores publicos cuyo conocimiento por el cliente no es problema.
    """
    return {
        'ANALYTICS_DOMAIN': getattr(settings, 'ANALYTICS_DOMAIN', ''),
        # Microsoft Clarity: heatmaps + session replays. Solo se inyecta
        # si esta seteado (en dev queda vacio -> sin tracking).
        'CLARITY_PROJECT_ID': getattr(settings, 'CLARITY_PROJECT_ID', ''),
        # Google tag (Ads/GA4). Solo se inyecta si esta seteado.
        'GOOGLE_TAG_ID': getattr(settings, 'GOOGLE_TAG_ID', ''),
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
        # BUG-009: número de WhatsApp para wa.me/... en el landing y /info/.
        'PUBLIC_WHATSAPP': getattr(settings, 'PUBLIC_WHATSAPP', ''),
        # Envios a domicilio. OFF = solo retiro en tienda: el checkout no
        # pide direccion y los templates esconden toda mencion a envios.
        'FEATURE_ENVIOS': getattr(settings, 'FEATURE_ENVIOS', False),
    }


def backoffice_badges(request):
    """Contadores para los badges del sidebar del backoffice.

    Lazy a proposito: las queries SOLO corren si el template pide la
    variable (base.html del backoffice) — las paginas publicas usan
    base_public.html y nunca las evaluan.
    """
    def _despacho_nuevos():
        if not request.user.is_authenticated:
            return 0
        from pos.models import ReciboVenta
        return ReciboVenta.objects.filter(
            canal=ReciboVenta.CANAL_ONLINE,
            estado=ReciboVenta.ESTADO_PAGADO,
            despachado_en__isnull=True,
        ).count()

    def _stock_agotados():
        if not request.user.is_authenticated:
            return 0
        from bodega.models import StockTienda
        return StockTienda.objects.filter(cantidad=0).count()

    return {
        'badge_despacho_nuevos': SimpleLazyObject(_despacho_nuevos),
        'badge_stock_agotados': SimpleLazyObject(_stock_agotados),
    }
