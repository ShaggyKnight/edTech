"""Generación y validación de códigos de barras EAN-13.

El proyecto usa códigos EAN-13 (13 dígitos, estándar retail mundial)
para todos los items vendibles. Para productos confeccionados internos
generamos códigos en el rango **200-299** del prefijo país, que GS1
reserva explícitamente para "uso interno" del negocio (no se confunde
con productos comerciales reales como los perfumes que vienen con
EAN propio).

Esquema del código interno:
    [200] [t] [pk zero-padded a 8] [check]
     │     │   │                    └─ dígito de control EAN-13
     │     │   └─ pk del Producto o ProductoVariante (0..99 999 999)
     │     └─ tipo: 1 = Producto, 2 = ProductoVariante
     └─ prefijo "uso interno" GS1

Ejemplos:
    Producto pk=5    → 200 1 00000005 C  → 2001000000050 + check
    Variante pk=123  → 200 2 00000123 C  → 2002000001230 + check
"""
from __future__ import annotations

PREFIJO_INTERNO = '200'
TIPO_PRODUCTO = '1'
TIPO_VARIANTE = '2'


def calcular_digito_ean13(doce_digitos: str) -> str:
    """Dado un string de 12 dígitos, devuelve el dígito de control EAN-13.

    Algoritmo estándar: suma alterna con pesos 1 y 3, mod 10, complemento.
    Para `4006381333931` los primeros 12 dígitos `400638133393` dan check
    igual a `1`.
    """
    if len(doce_digitos) != 12 or not doce_digitos.isdigit():
        raise ValueError('Se requieren exactamente 12 dígitos numéricos')
    suma = 0
    for i, ch in enumerate(doce_digitos):
        d = int(ch)
        # Posiciones impares (1ra, 3ra, ...) pesan 1; pares pesan 3.
        # i=0 → posición 1 (impar) → peso 1.
        suma += d if i % 2 == 0 else d * 3
    return str((10 - (suma % 10)) % 10)


def validar_ean13(codigo: str) -> bool:
    """True si `codigo` es un EAN-13 válido (13 dígitos + check correcto)."""
    if not codigo or len(codigo) != 13 or not codigo.isdigit():
        return False
    return calcular_digito_ean13(codigo[:12]) == codigo[12]


def generar_codigo_interno(tipo: str, pk: int) -> str:
    """Devuelve el EAN-13 interno para un Producto o ProductoVariante.

    Args:
        tipo: 'p' para Producto, 'v' para ProductoVariante.
        pk: clave primaria del item (1..99_999_999).

    Returns:
        13 dígitos como string. Ejemplos:
            generar_codigo_interno('p', 5)   → '2001000000058'
            generar_codigo_interno('v', 123) → '2002000001236'

    Raises:
        ValueError: si `tipo` no es 'p'/'v' o `pk` está fuera de rango.
    """
    if tipo == 'p':
        tipo_digit = TIPO_PRODUCTO
    elif tipo == 'v':
        tipo_digit = TIPO_VARIANTE
    else:
        raise ValueError("tipo debe ser 'p' (Producto) o 'v' (ProductoVariante)")

    if not isinstance(pk, int) or pk < 1 or pk > 99_999_999:
        raise ValueError('pk debe estar entre 1 y 99 999 999')

    cuerpo = f'{PREFIJO_INTERNO}{tipo_digit}{pk:08d}'  # 12 dígitos
    check = calcular_digito_ean13(cuerpo)
    return cuerpo + check


def parsear_codigo_interno(codigo: str) -> tuple[str, int] | None:
    """Si `codigo` es un EAN-13 interno generado por este modulo, devuelve
    (tipo, pk). Si no, devuelve None.

    Útil para que el POS escanee un código y sepa si buscar en Producto
    o en ProductoVariante (más rápido que dos queries).
    """
    if not validar_ean13(codigo):
        return None
    if not codigo.startswith(PREFIJO_INTERNO):
        return None
    tipo_digit = codigo[3]
    if tipo_digit == TIPO_PRODUCTO:
        tipo = 'p'
    elif tipo_digit == TIPO_VARIANTE:
        tipo = 'v'
    else:
        return None
    try:
        pk = int(codigo[4:12])
    except ValueError:
        return None
    if pk < 1:
        return None
    return (tipo, pk)


def render_svg_ean13(codigo: str, *, module_width=0.35,
                     module_height=12.0, font_size=8) -> str:
    """Renderiza un EAN-13 como SVG (string) para embeber en HTML/print.

    Args:
        codigo: 13 dígitos (debe ser EAN-13 válido o se levanta).
        module_width: ancho de cada modulo en mm (0.33 es minimo legible).
        module_height: alto de las barras en mm.
        font_size: tamaño del texto del codigo bajo las barras.

    Returns:
        SVG completo como string, listo para embeber con |safe en template.
    """
    if not validar_ean13(codigo):
        raise ValueError(f'No es un EAN-13 valido: {codigo!r}')

    # Lazy import: python-barcode solo se usa cuando se imprime, no en
    # cada request del catalogo.
    import io
    import barcode
    from barcode.writer import SVGWriter

    # python-barcode acepta el EAN-13 completo de 13 digitos en su clase
    # 'ean13' usando add_checksum=False (ya tenemos check).
    bcode = barcode.get('ean13', codigo[:12], writer=SVGWriter())
    buf = io.BytesIO()
    bcode.write(buf, options={
        'module_width': module_width,
        'module_height': module_height,
        'font_size': font_size,
        'text_distance': 2.0,
        'quiet_zone': 2.0,
        'write_text': True,
    })
    svg_bytes = buf.getvalue()
    # python-barcode incluye <?xml?> y <!DOCTYPE> antes del <svg> que
    # estorban al embeber inline. Cortamos desde el primer '<svg'.
    svg = svg_bytes.decode('utf-8')
    idx = svg.find('<svg')
    if idx > 0:
        svg = svg[idx:]
    return svg
