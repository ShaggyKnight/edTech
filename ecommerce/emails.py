"""Notificación de boleta al cliente.

Por ahora un correo simple en texto; cuando tengamos DTE real se adjunta el
PDF del timbre electrónico (Fase E).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from pos.models import ReciboVenta

log = logging.getLogger(__name__)


def enviar_boleta(recibo: ReciboVenta) -> bool:
    """Envía la boleta del recibo al email del cliente. Devuelve si se envió."""
    if not recibo.cliente_email:
        return False

    contexto = {'recibo': recibo, 'detalles': list(recibo.detalles.all())}
    cuerpo_txt = render_to_string('ecommerce/email/boleta.txt', contexto)
    asunto = f'Boleta de tu compra #{recibo.pk}'
    remitente = getattr(settings, 'DEFAULT_FROM_EMAIL', 'ventas@ideas.local')

    try:
        send_mail(
            subject=asunto,
            message=cuerpo_txt,
            from_email=remitente,
            recipient_list=[recibo.cliente_email],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001 — logueamos y seguimos para no romper el flujo de compra
        log.exception('No se pudo enviar boleta por email para recibo %s', recibo.pk)
        return False
    return True
