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
                      template_html: str, template_txt: str | None = None,
                      unsub_url: str = '') -> bool:
    """Renderiza HTML (+ txt opcional) y envia un email multipart.

    Devuelve True si el envio se programo OK. Errores se loggean y devuelven
    False — el caller decide si esto rompe algo o no (normalmente no).

    `unsub_url`: si viene, se agrega el header `List-Unsubscribe` — Gmail
    y Outlook lo ponderan fuerte para NO mandar a spam los emails de tipo
    suscripcion (stock disponible, carrito, resena, recordatorio).
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
        headers = {}
        if unsub_url and unsub_url != '#':
            headers['List-Unsubscribe'] = f'<{unsub_url}>'
            # Gmail exige este segundo header para el "unsubscribe" de un
            # click en su UI (RFC 8058). Nuestro endpoint de cancelar
            # acepta GET, asi que declararlo es correcto.
            headers['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
        msg = EmailMultiAlternatives(
            subject=subject, body=text,
            from_email=_remitente(), to=[to],
            headers=headers or None,
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


def _destinatarios_notif_pedidos() -> list[str]:
    """Lista de emails que reciben aviso de cada venta online.

    Combina:
      1. OWNER_NOTIFICATION_EMAIL del .env (Blanca, backup siempre).
      2. Todos los users con rol DESPACHADOR activo + flag
         recibe_notif_ecommerce=True.

    Deduplica (mismo email no se manda dos veces) y filtra vacios.
    """
    from django.contrib.auth import get_user_model
    from accounts.roles import DESPACHADOR

    destinos = set()
    owner = getattr(settings, 'OWNER_NOTIFICATION_EMAIL', '') or ''
    if owner:
        destinos.add(owner.strip().lower())

    User = get_user_model()
    despachadores = (
        User.objects
        .filter(
            is_active=True,
            groups__name=DESPACHADOR,
            perfil__recibe_notif_ecommerce=True,
        )
        .exclude(email='')
        .values_list('email', flat=True)
    )
    for email in despachadores:
        destinos.add(email.strip().lower())

    return [d for d in destinos if d]


def notificar_dueno_nueva_orden(recibo: ReciboVenta) -> bool:
    """Aviso interno cuando entra una venta online pagada.

    Va a Blanca (OWNER_NOTIFICATION_EMAIL) + todos los despachadores
    activos con notificaciones prendidas. Si no hay destinatarios,
    es no-op silencioso.
    """
    destinatarios = _destinatarios_notif_pedidos()
    if not destinatarios:
        return False

    contexto = {
        'recibo': recibo,
        'admin_url': _absolute_url(
            reverse('despacho:detalle', args=[recibo.pk])
        ),
    }
    total_fmt = f'{int(recibo.total):,}'.replace(',', '.')
    subject = f'Nueva venta online #{recibo.pk} · ${total_fmt}'

    # Mandamos UN email con todos los destinatarios en `to`. Si en el
    # futuro queremos personalizar el mail por persona, separamos.
    try:
        contexto_completo = {
            **contexto,
            'PUBLIC_WHATSAPP': getattr(settings, 'PUBLIC_WHATSAPP', ''),
            'SITE_URL': getattr(settings, 'SITE_URL', 'https://ideasboutique.cl'),
        }
        html = render_to_string('emails/aviso_dueno_orden.html', contexto_completo)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=f'Nueva venta online #{recibo.pk}. Total ${total_fmt}.',
            from_email=_remitente(),
            to=destinatarios,
        )
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001
        log.exception('Fallo notificar venta online #%s a %s',
                      recibo.pk, destinatarios)
        return False


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
        contexto={
            # Template usa `user.first_name`. `usuario` se mantiene como
            # alias por si en el futuro algun otro caller lo usa.
            'user': usuario,
            'usuario': usuario,
            'tienda_url': _absolute_url('/tienda/'),
        },
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
        contexto={
            # Template usa `user.email`.
            'user': usuario,
            'usuario': usuario,
            'reset_url': reset_url,
        },
        template_html='emails/recuperar_password.html',
    )


def enviar_stock_disponible(variante, suscriptor_email: str,
                            *, unsub_url: str = '',
                            force: bool = False) -> bool:
    """Aviso a clientes que pidieron notificacion de reposicion.

    `variante` es una ProductoVariante (con .producto y .valores). El
    template muestra el producto + la talla. `unsub_url` es el link de
    cancelacion (lo arma el caller con el token del aviso — ver
    AvisoStockReposicion en ecommerce.models).
    """
    if not force and not getattr(settings, 'FEATURE_EMAIL_STOCK_DISPONIBLE', False):
        return False
    producto = variante.producto
    return _enviar_multipart(
        subject=f'Volvio! {producto.nombre}',
        to=suscriptor_email,
        contexto={
            'variante': variante,
            'producto': producto,  # alias por compatibilidad
            'producto_url': _absolute_url(
                reverse('ecommerce:producto', args=[producto.pk])
            ),
            'unsub_url': unsub_url or '#',
        },
        template_html='emails/stock_disponible.html',
        unsub_url=unsub_url,
    )


def enviar_carrito_abandonado(carrito_data: dict, *, force: bool = False) -> bool:
    """Campana de recuperacion +24h. Se invoca desde un cron diario.

    El `carrito_data` dict debe traer:
      - email           destinatario
      - nombre          saludo (opcional)
      - fecha           datetime del abandono
      - items           [{cantidad, nombre, subtotal}, ...]
      - total           Decimal
      - hay_uniforme    bool (cambia el copy de soporte)
      - calc_url        link a la calculadora de tallas
      - retomar_url     link con token para recuperar el carrito
    """
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
    """Email +14d post-compra pidiendo resena. Se invoca desde cron diario.

    El template asume UN producto representativo por email. Tomamos el
    primer detalle del recibo (suele ser el principal). Para resenas
    multi-producto en el futuro, mandar 1 email por linea.
    """
    if not force and not getattr(settings, 'FEATURE_EMAIL_PEDIR_RESENA', False):
        return False
    if not recibo.cliente_email:
        return False
    detalles = list(recibo.detalles.all()[:1])
    if not detalles:
        return False
    detalle = detalles[0]
    # Construimos un objeto chico con .nombre para que el template renderee.
    # `descripcion` esta en cada DetalleRecibo y captura el texto del item.
    producto_ref = type('ProductoRef', (), {
        'nombre': getattr(detalle, 'descripcion', '') or str(detalle),
    })
    return _enviar_multipart(
        subject='Que te parecio tu compra?',
        to=recibo.cliente_email,
        contexto={
            'recibo': recibo,
            'producto': producto_ref,
            'cliente_nombre': getattr(recibo, 'cliente_nombre', '') or '',
            'resena_url': _absolute_url(
                reverse('ecommerce:detalle_pedido', args=[recibo.pk])
            ) if _tiene_url('ecommerce:detalle_pedido') else '#',
        },
        template_html='emails/pedir_resena.html',
    )


def enviar_recordatorio_familia(cliente, hijos: list, *,
                                descuento_segundo_hijo: bool = False,
                                familia_url: str = '',
                                force: bool = False) -> bool:
    """Email anual de febrero a familias del colegio (uniformes).

    `hijos` es una lista de objetos con .nombre, .colegio, .talla_buzo,
    .talla_polera, .talla_chaleco. Hoy NO existe el modelo Hijo en el
    schema — el caller (futuro cron) lo deriva de las compras pasadas
    del cliente (analiza recibos del ultimo anio + tallas compradas +
    agrupar por colegio del producto).
    """
    if not force and not getattr(settings, 'FEATURE_EMAIL_RECORDATORIO_FAMILIA', False):
        return False
    if not cliente.email:
        return False
    nombre = getattr(cliente, 'nombre', '') or getattr(cliente, 'first_name', '') or ''
    return _enviar_multipart(
        subject='Llego febrero · sigue quedando el uniforme?',
        to=cliente.email,
        contexto={
            'cliente': cliente,            # mantener por si templates futuros lo usan
            'cliente_nombre': nombre,
            'hijos': hijos,
            'descuento_segundo_hijo': descuento_segundo_hijo,
            'familia_url': familia_url or _absolute_url('/cuenta/familia/'),
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
