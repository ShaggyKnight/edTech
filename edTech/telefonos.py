"""Utilidades de telefonos chilenos — compartidas por todo el sistema.

Una sola definicion de "normalizar un celular chileno" para que el
checkout, los links wa.me del despacho y las notificaciones automaticas
de WhatsApp nunca diverjan en el formato.
"""
import re


def normalizar_fono_cl(telefono: str) -> str:
    """Deja el telefono en digitos con codigo pais: '56912345678'.

    Acepta lo que el cliente haya tipeado: '+56 9 5544 3322',
    '9 5544 3322', '955443322', '56955443322', '55443322' (celular
    viejo sin el 9). Devuelve '' si no hay nada rescatable.

    Este es el formato que esperan wa.me y la API de WhatsApp (Meta).
    """
    digitos = re.sub(r'\D', '', telefono or '')
    if not digitos:
        return ''
    if digitos.startswith('56'):
        return digitos
    # Celular chileno tipeado sin codigo pais (9XXXXXXXX).
    if len(digitos) == 9 and digitos.startswith('9'):
        return '56' + digitos
    # 8 digitos: celular viejo sin el 9 inicial.
    if len(digitos) == 8:
        return '569' + digitos
    return digitos
