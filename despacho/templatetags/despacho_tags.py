"""Tags del despacho — links de WhatsApp con mensaje prellenado.

No usamos la API de WhatsApp Business (requiere verificacion de Meta y
plantillas aprobadas): abrimos un chat `wa.me` con el texto listo para
que Blanca solo apriete Enviar. Cero costo, cero setup, y el mensaje es
editable antes de mandarlo — que es como ella trabaja hoy.
"""
from urllib.parse import quote

from django import template

from edTech.telefonos import normalizar_fono_cl

register = template.Library()

# Alias historico: los tests y este modulo usaban el nombre privado
# antes de que la normalizacion se moviera al util compartido.
_normalizar_fono_cl = normalizar_fono_cl


@register.simple_tag
def wa_aviso_pedido(pedido) -> str:
    """URL wa.me al cliente del pedido con el aviso segun su estado.

    - Despachado + con direccion  → "va en camino"
    - Despachado + sin direccion  → "listo para retiro"
    - En cola                     → "lo estamos preparando"

    Devuelve '' si el pedido no tiene telefono (el template esconde el
    boton).
    """
    fono = _normalizar_fono_cl(getattr(pedido, 'cliente_telefono', ''))
    if not fono:
        return ''

    nombre = (pedido.cliente_nombre or '').split(' ')[0] or 'Hola'
    if pedido.despachado_en:
        if (pedido.cliente_direccion or '').strip():
            cuerpo = (
                f'¡Hola {nombre}! Soy de Ideas Boutique 🙌 '
                f'Tu pedido #{pedido.pk} ya salió y va en camino. '
                f'Cualquier cosa me avisas. ¡Gracias por tu compra!'
            )
        else:
            cuerpo = (
                f'¡Hola {nombre}! Soy de Ideas Boutique 🙌 '
                f'Tu pedido #{pedido.pk} ya está listo para retiro en '
                f'Caupolicán 437-B, Los Vilos (lunes a sábado, 9 a 19hs). '
                f'¡Te esperamos!'
            )
    else:
        cuerpo = (
            f'¡Hola {nombre}! Soy de Ideas Boutique 🙌 '
            f'Recibimos tu pedido #{pedido.pk} y ya lo estamos preparando. '
            f'Te aviso apenas salga.'
        )
    return f'https://wa.me/{fono}?text={quote(cuerpo)}'
