"""Validadores específicos del dominio chileno (RUT, etc).

Mantienen la lógica autoritativa server-side. Los endpoints de
`validar_*_inline` los reusan para dar feedback inmediato vía HTMX,
pero la validación final del checkout siempre pasa por estos
helpers en el clean del form.
"""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError


_RUT_LIMPIO = re.compile(r'[.\s-]')


def normalizar_rut(rut: str) -> str:
    """Quita puntos, guiones y espacios; pasa la K a mayúscula.

    Ej: "12.345.678-k" → "12345678K".
    """
    if not rut:
        return ''
    sin_separadores = _RUT_LIMPIO.sub('', rut.strip())
    return sin_separadores.upper()


def calcular_dv(numero: int) -> str:
    """Dígito verificador chileno (módulo 11)."""
    suma = 0
    factor = 2
    for d in reversed(str(numero)):
        suma += int(d) * factor
        factor = factor + 1 if factor < 7 else 2
    resto = 11 - (suma % 11)
    if resto == 11:
        return '0'
    if resto == 10:
        return 'K'
    return str(resto)


def validar_rut_chileno(rut: str) -> str:
    """Valida y normaliza un RUT chileno.

    Devuelve el RUT en formato "12345678-K" (con guión).
    Levanta `ValidationError` si:
    - Está vacío o solo tiene caracteres no válidos.
    - El cuerpo no es numérico.
    - El DV no coincide con el módulo 11.
    """
    if not rut:
        raise ValidationError('Ingresá tu RUT.')

    limpio = normalizar_rut(rut)
    if len(limpio) < 2:
        raise ValidationError('RUT demasiado corto.')

    cuerpo, dv = limpio[:-1], limpio[-1]
    if not cuerpo.isdigit():
        raise ValidationError('El RUT solo puede tener números y un dígito verificador.')
    if dv not in '0123456789K':
        raise ValidationError('Dígito verificador inválido.')

    if calcular_dv(int(cuerpo)) != dv:
        raise ValidationError('RUT inválido. Revisá el número o el dígito verificador.')

    return f'{cuerpo}-{dv}'
