"""Notificaciones automaticas por WhatsApp — Meta Cloud API (oficial).

FUNCIONALIDAD ACTIVABLE, apagada por default. Los flujos del sistema
(pago confirmado, pedido despachado) llaman estas funciones SIEMPRE;
con la flag apagada son no-op silenciosos. El dia que el negocio
complete el setup en Meta (ver docs/whatsapp_api.md) basta con:

    FEATURE_WHATSAPP_AUTO=True
    WHATSAPP_API_TOKEN=<token permanente del system user>
    WHATSAPP_PHONE_NUMBER_ID=<id numerico del numero emisor>

en el .env + restart — cero cambios de codigo.

Por que la API oficial y no un bot de WhatsApp Web (whatsapp-web.js y
similares): esos violan los terminos de WhatsApp y arriesgan el BAN
del numero — y el numero de la tienda es el canal principal con las
clientas. No se juega con eso.

Los mensajes iniciados por el negocio DEBEN usar plantillas
pre-aprobadas por Meta ("utility templates"). Las que este modulo usa
(registrarlas con estos nombres exactos — texto sugerido en
docs/whatsapp_api.md):

    pedido_confirmado    {{1}}=nombre  {{2}}=numero pedido
    pedido_listo_retiro  {{1}}=nombre  {{2}}=numero pedido
    pedido_despachado    {{1}}=nombre  {{2}}=numero pedido

Todo es best-effort: un fallo se loggea y devuelve False — jamas rompe
el flujo de venta.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

from edTech.telefonos import normalizar_fono_cl

log = logging.getLogger(__name__)

# Version del Graph API. Meta soporta cada version ~2 años.
API_VERSION = 'v20.0'


def _config():
    return (
        bool(getattr(settings, 'FEATURE_WHATSAPP_AUTO', False)),
        getattr(settings, 'WHATSAPP_API_TOKEN', ''),
        str(getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')),
    )


def enviar_plantilla(telefono: str, plantilla: str,
                     parametros: tuple = ()) -> bool:
    """Envia una plantilla aprobada al numero dado. Best-effort.

    Devuelve True solo si Meta acepto el mensaje. False en cualquier
    otro caso (flag apagada, sin credenciales, telefono invalido,
    error de red/API) — siempre con log del motivo.
    """
    activo, token, phone_id = _config()
    if not activo:
        log.debug('WhatsApp auto apagado (FEATURE_WHATSAPP_AUTO=False) '
                  '— no se envia %r.', plantilla)
        return False
    if not (token and phone_id):
        log.warning('FEATURE_WHATSAPP_AUTO activo pero faltan '
                    'WHATSAPP_API_TOKEN / WHATSAPP_PHONE_NUMBER_ID.')
        return False

    fono = normalizar_fono_cl(telefono)
    if not fono:
        log.info('WhatsApp %r no enviado: telefono invalido %r.',
                 plantilla, telefono)
        return False

    payload = {
        'messaging_product': 'whatsapp',
        'to': fono,
        'type': 'template',
        'template': {
            'name': plantilla,
            'language': {'code': 'es'},
        },
    }
    if parametros:
        payload['template']['components'] = [{
            'type': 'body',
            'parameters': [{'type': 'text', 'text': str(p)}
                           for p in parametros],
        }]

    url = f'https://graph.facebook.com/{API_VERSION}/{phone_id}/messages'
    try:
        resp = requests.post(
            url, json=payload,
            headers={'Authorization': f'Bearer {token}'},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning('WhatsApp %r a %s fallo (red): %s', plantilla, fono, exc)
        return False
    if resp.status_code >= 400:
        log.warning('WhatsApp %r a %s rechazado (%s): %s',
                    plantilla, fono, resp.status_code, resp.text[:300])
        return False
    log.info('WhatsApp %r enviado a %s.', plantilla, fono)
    return True


# ─── Avisos concretos del negocio ────────────────────────────────────

def _primer_nombre(recibo) -> str:
    return (recibo.cliente_nombre or '').split(' ')[0] or 'Hola'


def notificar_pedido_confirmado(recibo) -> bool:
    """Al quedar PAGADO un pedido online: "recibimos tu pedido"."""
    if not getattr(recibo, 'cliente_telefono', ''):
        return False
    return enviar_plantilla(
        recibo.cliente_telefono, 'pedido_confirmado',
        (_primer_nombre(recibo), f'#{recibo.pk}'),
    )


def notificar_pedido_listo(recibo) -> bool:
    """Al marcarlo DESPACHADO: "listo para retiro" o "va en camino"
    segun tenga direccion de envio o no."""
    if not getattr(recibo, 'cliente_telefono', ''):
        return False
    plantilla = ('pedido_despachado'
                 if (recibo.cliente_direccion or '').strip()
                 else 'pedido_listo_retiro')
    return enviar_plantilla(
        recibo.cliente_telefono, plantilla,
        (_primer_nombre(recibo), f'#{recibo.pk}'),
    )
