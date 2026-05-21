"""Envio de emails transaccionales con templates branded.

Cada email tiene version HTML (extiende `emails/_base.html` con branding
Ideas Boutique: Cormorant + Inter, fondo crema, dorado + vino sobre ink)
y texto plano como fallback. Multipart por defecto.

Funciones activas:
  - enviar_boleta(recibo)              cliente recibe boleta tras pago
  - notificar_dueno_nueva_orden(recibo) Blanca recibe aviso de venta online

Funciones detras de feature flags (apagadas por default):
  - enviar_bienvenida(usuario)         registro de cuenta nueva
  - enviar_reset_password(usuario, url) link de reset
  - enviar_stock_disponible(...)       "volvio la talla que esperabas"
  - enviar_carrito_abandonado(...)     +24h sin checkout
  - enviar_pedir_resena(recibo)        +14d post-compra
  - enviar_recordatorio_familia(...)   anual febrero (familias colegio)

Politica de errores: TODO error de envio se loggea pero NO rompe el flujo
de compra. La venta sigue siendo valida aunque el email no salga.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from pos.models import ReciboVenta

log = logging.getLogger(__name__)


def _remitente() -> str:
    return getattr(settings, 'DEFAULT_FROM_EMAIL', 'ventas@ideas.local')


def _absolute_url(path: str) -> str:
    base = getattr(settings, 'SITE_URL', '').rstrip('/')
    return f'{base}{path}'


def _enviar_multipart(subject: str, to: str, contexto: dict,
                      template_html: str, template_txt: str | None = None) -> bool:
    """Renderiza HTML (+ txt opcional) y envia un email multipart.

    Devuelve True si el envio se programo OK. Errores se loggean y devuelven
    False — el caller decide si esto rompe algo o no (normalmente no).
    """
    # Variables globales para todos los templates (footer del _base.html).
    contexto = {
        **contexto,
        'PUBLIC_WHATSAPP': getattr(settings, 'PUBLIC_WHATSAPP', ''),
        'SITE_URL': getattr(settings, 'SITE_URL', 'https://ideasboutique.cl'),
    }
    try:
        html = render_to_string(template_html, contexto)
        text = render_to_string(template_txt, contexto) if template_txt else ''
        if not text:
            # Si no hay txt, usamos un fallback minimo desde el subject.
            text = f'{subject}\n\nVer este email en HTML para los detalles.'
        msg = EmailMultiAlternatives(
            subject=subject, body=text,
            from_email=_remitente(), to=[to],
        )
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001
        log.exception('Fallo enviar email a %s (template %s)', to, template_html)
        return False


# ─────────────────────────────────────────────────────────────────────
# Activos (en el flujo de compra)
# ─────────────────────────────────────────────────────────────────────

def enviar_boleta(recibo: ReciboVenta) -> bool:
    """Envia la boleta al cliente despues del pago. Multipart HTML+txt."""
    if not recibo.cliente_email:
        return False
    contexto = {
        'recibo': recibo,
        'recibo_url': _absolute_url(
            reverse('ecommerce:detalle_pedido', args=[recibo.pk])
        ) if _tiene_url('ecommerce:detalle_pedido') else '',
    }
    return _enviar_multipart(
        subject=f'Boleta #{recibo.pk} · Ideas Boutique',
        to=recibo.cliente_email,
        contexto=contexto,
        template_html='emails/boleta_compra.html',
        template_txt='emails/boleta_compra.txt',
    )


def notificar_dueno_nueva_orden(recibo: ReciboVenta) -> bool:
    """Aviso interno a Blanca cuando entra una venta online pagada.

    Si no hay `OWNER_NOTIFICATION_EMAIL`, es no-op silencioso.
    """
    destinatario = getattr(settings, 'OWNER_NOTIFICATION_EMAIL', '')
    if not destinatario:
        return False
    contexto = {
        'recibo': recibo,
        'admin_url': _absolute_url(
            reverse('admin:pos_reciboventa_change', args=[recibo.pk])
        ),
    }
    total_fmt = f'{int(recibo.total):,}'.replace(',', '.')
    return _enviar_multipart(
        subject=f'Nueva venta online #{recibo.pk} · ${total_fmt}',
        to=destinatario,
        contexto=contexto,
        template_html='emails/aviso_dueno_orden.html',
    )


# ─────────────────────────────────────────────────────────────────────
# Detras de feature flags (postergados — codigo listo, no se invocan)
# ─────────────────────────────────────────────────────────────────────

def enviar_bienvenida(usuario, *, force: bool = False) -> bool:
    """Email de bienvenida al registrar cuenta.

    Activar con `FEATURE_EMAIL_BIENVENIDA=True` en .env. Mientras este
    apagado, no hace nada (ahorra confusion durante el polishing).
    """
    if not force and not getattr(settings, 'FEATURE_EMAIL_BIENVENIDA', False):
        return False
    if not usuario.email:
        return False
    return _enviar_multipart(
        subject=f'Bienvenida a Ideas Boutique, {usuario.first_name or usuario.username}',
        to=usuario.email,
        contexto={'usuario': usuario, 'site_url': _absolute_url('/tienda/')},
        template_html='emails/registro_bienvenida.html',
    )


def enviar_reset_password(usuario, reset_url: str, *, force: bool = False) -> bool:
    """Email con link para restablecer contrasena."""
    if not force and not getattr(settings, 'FEATURE_EMAIL_RESET_PASSWORD', False):
        return False
    if not usuario.email:
        return False
    return _enviar_multipart(
        subject='Recuperar contrasena · Ideas Boutique',
        to=usuario.email,
        contexto={'usuario': usuario, 'reset_url': reset_url},
        template_html='emails/recuperar_password.html',
    )


def enviar_stock_disponible(producto, suscriptor_email: str,
                            *, force: bool = False) -> bool:
    """Aviso a clientes que pidieron notificacion de reposicion."""
    if not force and not getattr(settings, 'FEATURE_EMAIL_STOCK_DISPONIBLE', False):
        return False
    return _enviar_multipart(
        subject=f'Volvio! {producto.nombre}',
        to=suscriptor_email,
        contexto={
            'producto': producto,
            'pdp_url': _absolute_url(
                reverse('ecommerce:producto', args=[producto.pk])
            ),
        },
        template_html='emails/stock_disponible.html',
    )


def enviar_carrito_abandonado(carrito_data: dict, *, force: bool = False) -> bool:
    """Campana de recuperacion +24h. Se invoca desde un cron diario."""
    if not force and not getattr(settings, 'FEATURE_EMAIL_CARRITO_ABANDONADO', False):
        return False
    email = carrito_data.get('email')
    if not email:
        return False
    return _enviar_multipart(
        subject='Te guardamos lo que dejaste en el carrito',
        to=email,
        contexto=carrito_data,
        template_html='emails/carrito_abandonado.html',
    )


def enviar_pedir_resena(recibo: ReciboVenta, *, force: bool = False) -> bool:
    """Email +14d post-compra pidiendo resena. Se invoca desde cron diario."""
    if not force and not getattr(settings, 'FEATURE_EMAIL_PEDIR_RESENA', False):
        return False
    if not recibo.cliente_email:
        return False
    return _enviar_multipart(
        subject=f'Que te parecio tu compra?',
        to=recibo.cliente_email,
        contexto={
            'recibo': recibo,
            'resena_url': _absolute_url(
                reverse('ecommerce:detalle_pedido', args=[recibo.pk])
            ) if _tiene_url('ecommerce:detalle_pedido') else '',
        },
        template_html='emails/pedir_resena.html',
    )


def enviar_recordatorio_familia(cliente, colegio, *, force: bool = False) -> bool:
    """Email anual de febrero a familias del colegio (uniformes)."""
    if not force and not getattr(settings, 'FEATURE_EMAIL_RECORDATORIO_FAMILIA', False):
        return False
    if not cliente.email:
        return False
    return _enviar_multipart(
        subject='Llego febrero · sigue quedando el uniforme?',
        to=cliente.email,
        contexto={
            'cliente': cliente, 'colegio': colegio,
            'tienda_url': _absolute_url('/tienda/?colegio={}'.format(colegio.pk)),
        },
        template_html='emails/recordatorio_familia.html',
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────

def _tiene_url(name: str) -> bool:
    """True si una URL nombrada existe (algunas son opcionales)."""
    try:
        reverse(name, args=[0])
        return True
    except Exception:
        return False
