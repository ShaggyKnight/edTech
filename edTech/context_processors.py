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
    def _oferta_banner():
        # Campaña vigente (toda la tienda / familia) para el banner del
        # sitio publico. Lazy: la query solo corre si un template lo pide
        # (el header de la tienda y el landing).
        from catalogo.precios import oferta_banner_online
        return oferta_banner_online()

    clarity = getattr(settings, 'CLARITY_PROJECT_ID', '')
    google = getattr(settings, 'GOOGLE_TAG_ID', '')
    meta = getattr(settings, 'META_PIXEL_ID', '')

    return {
        'ANALYTICS_DOMAIN': getattr(settings, 'ANALYTICS_DOMAIN', ''),
        # Microsoft Clarity: heatmaps + session replays. Solo se carga si
        # esta seteado Y el visitante acepta la analitica.
        'CLARITY_PROJECT_ID': clarity,
        # Google tag (GA4 / Ads). Idem: analitica (y publicidad para Ads).
        'GOOGLE_TAG_ID': google,
        # Meta Pixel (FB/IG Ads). Solo con la publicidad aceptada.
        'META_PIXEL_ID': meta,
        # Categorias de cookies opcionales que existen segun lo configurado
        # (gestor de consentimiento, Ley 21.719). Sin ninguna, no hay aviso.
        'CONSENT_ANALITICA': bool(clarity or google),
        'CONSENT_PUBLICIDAD': bool(meta or google),
        # Responsable de los datos (politica de privacidad y terminos).
        'EMPRESA_RAZON_SOCIAL': getattr(settings, 'EMPRESA_RAZON_SOCIAL', ''),
        'EMPRESA_RUT': getattr(settings, 'EMPRESA_RUT', ''),
        'EMPRESA_DIRECCION': getattr(settings, 'EMPRESA_DIRECCION', ''),
        'PRIVACIDAD_EMAIL': getattr(settings, 'PRIVACIDAD_EMAIL', ''),
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
        # BUG-009: número de WhatsApp para wa.me/... en el landing y /info/.
        'PUBLIC_WHATSAPP': getattr(settings, 'PUBLIC_WHATSAPP', ''),
        # Google Maps: iframe incrustado + link a la ficha (horario/reseñas).
        'GOOGLE_MAPS_EMBED_URL': getattr(settings, 'GOOGLE_MAPS_EMBED_URL', ''),
        'GOOGLE_MAPS_PLACE_URL': getattr(settings, 'GOOGLE_MAPS_PLACE_URL', ''),
        # Envios a domicilio. OFF = solo retiro en tienda: el checkout no
        # pide direccion y los templates esconden toda mencion a envios.
        'FEATURE_ENVIOS': getattr(settings, 'FEATURE_ENVIOS', False),
        # Oferta de campaña vigente (o None) — banner automatico en la
        # barra de promo: aparece al crear la oferta y muere con ella.
        'OFERTA_BANNER': SimpleLazyObject(_oferta_banner),
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
        from django.db.models import Q
        from pos.models import ReciboVenta
        # Todo lo que espera accion en Despacho: pedidos pagados sin
        # despachar + transferencias directas por confirmar.
        return ReciboVenta.objects.filter(
            Q(estado=ReciboVenta.ESTADO_PAGADO, despachado_en__isnull=True)
            | Q(estado=ReciboVenta.ESTADO_PENDIENTE,
                payment_provider='transferencia'),
            canal=ReciboVenta.CANAL_ONLINE,
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
