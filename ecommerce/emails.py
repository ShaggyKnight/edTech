"""Notificación de boleta al cliente.

Por ahora un correo simple en texto; cuando tengamos DTE real se adjunta el
PDF del timbre electrónico (Fase E).

Sprint 3 · 3.5: agrega `notificar_dueno_nueva_orden` para que Blanca reciba
un aviso por email apenas entra una venta online (independiente de si el
cliente abre o no el panel admin). Si no hay `OWNER_NOTIFICATION_EMAIL`
configurado, es no-op silencioso — útil en dev.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

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


def notificar_dueno_nueva_orden(recibo: ReciboVenta) -> bool:
    """Avisa a la dueña por email cuando entra una venta online pagada.

    Sprint 3 · 3.5. No bloquea el flujo de compra: si no hay
    `OWNER_NOTIFICATION_EMAIL` configurado, es no-op. Si el envío
    falla, se loguea pero la venta sigue siendo válida.
    """
    destinatario = getattr(settings, 'OWNER_NOTIFICATION_EMAIL', '')
    if not destinatario:
        return False

    detalles = list(recibo.detalles.all())
    lineas_txt = '\n'.join(
        f'  • {d.cantidad}× {d.descripcion} — ${int(d.precio_unitario * d.cantidad):,}'.replace(',', '.')
        for d in detalles
    )
    cuerpo = (
        f'Hola Blanca,\n\n'
        f'Acaba de entrar una venta online en Ideas Boutique.\n\n'
        f'Pedido #{recibo.pk}\n'
        f'Cliente: {recibo.cliente_nombre}\n'
        f'Email:   {recibo.cliente_email}\n'
        f'Total:   ${int(recibo.total):,}\n\n'.replace(',', '.')
        + f'Items:\n{lineas_txt}\n\n'
        + f'Ver en el panel: '
          f'{getattr(settings, "SITE_URL", "").rstrip("/")}'
          f'{reverse("admin:pos_reciboventa_change", args=[recibo.pk])}\n\n'
        + 'Saludos,\nSistema Ideas Boutique'
    )
    asunto = f'✨ Nueva venta online #{recibo.pk} — ${int(recibo.total):,}'.replace(',', '.')
    remitente = getattr(settings, 'DEFAULT_FROM_EMAIL', 'ventas@ideas.local')

    try:
        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=remitente,
            recipient_list=[destinatario],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        log.exception('No se pudo notificar al dueño sobre recibo %s', recibo.pk)
        return False
    return True
