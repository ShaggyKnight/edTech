"""Pasarelas de pago online para el e-commerce.

Cada gateway es un adapter HTTP a un proveedor (KLAP, Khipu, etc.) que
expone una interfaz uniforme:

    init = gateway.iniciar_pago(recibo, return_url)
    result = gateway.confirmar_pago(token)

El comercio puede tener varios gateways activos a la vez (`KLAP` para
tarjeta + `Khipu` para transferencia, por ejemplo). El cliente elige
cual usar en el checkout.

Setting:
    ECOMMERCE_GATEWAYS_ACTIVOS=klap,khipu      # CSV de gateways habilitados
    ECOMMERCE_GATEWAY_DEFAULT=klap             # cual marcar pre-seleccionado

API minima de cada gateway (ver `base.py` para el contrato completo):

    class MiGateway(OnlinePaymentGateway):
        provider = 'mi-gateway'
        nombre_publico = 'Mi gateway'

        def iniciar_pago(self, recibo, return_url) -> OnlinePaymentInit:
            ...

        def confirmar_pago(self, token) -> PaymentResult:
            ...

        def webhook(self, request) -> WebhookResult:
            ...
"""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from ecommerce.gateways.base import (
    OnlinePaymentGateway,
    OnlinePaymentInit,
    WebhookResult,
)

# Registry: nombre publico -> dotted path al gateway. Si en el futuro hay
# un gateway externo (paquete pip), se puede agregar via dotted path en
# ECOMMERCE_GATEWAYS_ACTIVOS sin tocar este archivo.
_REGISTRY = {
    'mock':  'ecommerce.gateways.mock.MockOnlineGateway',
    'klap':  'ecommerce.gateways.klap.KlapGateway',
    'khipu': 'ecommerce.gateways.khipu.KhipuGateway',
    # Transferencia directa con confirmacion manual — respaldo sin
    # pasarela. Requiere TRANSFERENCIA_* en el .env para activarse.
    'transferencia': 'ecommerce.gateways.transferencia.TransferenciaGateway',
}


def _activos_csv() -> list[str]:
    raw = getattr(settings, 'ECOMMERCE_GATEWAYS_ACTIVOS', 'mock')
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [p.strip() for p in str(raw).split(',') if p.strip()]


def get_gateway(nombre: str) -> OnlinePaymentGateway:
    """Devuelve la instancia del gateway por nombre publico.

    Lanza KeyError si el nombre no existe en el registry.
    """
    if nombre not in _REGISTRY:
        raise KeyError(f'Gateway desconocido: {nombre!r} (validos: {list(_REGISTRY)})')
    cls = import_string(_REGISTRY[nombre])
    return cls()


def get_gateways_activos() -> list[OnlinePaymentGateway]:
    """Lista de gateways disponibles para el checkout (en orden config).

    Filtra silenciosamente los que fallen al instanciar (ej. faltan
    credenciales en .env) — se loggea el problema pero no se rompe el
    resto del checkout. El gateway default va primero si esta activo.
    """
    import logging
    log = logging.getLogger(__name__)

    nombres = _activos_csv()
    default = getattr(settings, 'ECOMMERCE_GATEWAY_DEFAULT', '')
    if default and default in nombres:
        # Mover el default al principio.
        nombres = [default] + [n for n in nombres if n != default]

    activos: list[OnlinePaymentGateway] = []
    for nombre in nombres:
        try:
            activos.append(get_gateway(nombre))
        except Exception as exc:  # noqa: BLE001
            log.warning('Gateway %r no se puede activar: %s', nombre, exc)
    return activos


def get_gateway_default() -> OnlinePaymentGateway:
    """Devuelve el primer gateway activo (que sera el default segun el
    orden de ECOMMERCE_GATEWAY_DEFAULT). Compat con codigo viejo que
    solo soporta un gateway."""
    activos = get_gateways_activos()
    if not activos:
        # Fallback al mock — para que las pantallas no exploten si .env
        # esta vacio. En prod normalmente esto NO pasa.
        return get_gateway('mock')
    return activos[0]


# Alias para retrocompat con codigo que importaba `get_online_gateway` del
# antiguo `ecommerce.payments`. Devuelve el primer gateway activo (default).
# Codigo nuevo deberia usar get_gateway_default() o get_gateway(nombre).
get_online_gateway = get_gateway_default


# Re-export para que `from ecommerce.gateways import OnlinePaymentInit`
# siga funcionando como cuando vivia en payments.py.
__all__ = [
    'OnlinePaymentGateway',
    'OnlinePaymentInit',
    'WebhookResult',
    'get_gateway',
    'get_gateways_activos',
    'get_gateway_default',
    'get_online_gateway',  # alias retrocompat
]
