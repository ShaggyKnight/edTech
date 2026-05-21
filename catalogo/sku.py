"""Generacion automatica de codigos SKU para variantes.

El SKU es un string corto, en mayusculas, sin espacios. Patron general:

    <MARCA>-<NOMBRE>-<VALORES_DE_ATRIBUTOS>

Para perfumes queda:
    LATTAFA-YARA-100ML-EDP

Idempotente y deterministico: el mismo input genera siempre el mismo
SKU. Si el SKU resultante ya existe en la BD (de otra variante distinta),
se le agrega un sufijo `-2`, `-3`, etc. para mantener la unicidad.
"""

from __future__ import annotations

import re

from django.utils.text import slugify


# Stopwords a remover del nombre antes de generar el SKU. Reducen la
# longitud sin sacrificar legibilidad.
STOPWORDS = {
    'de', 'del', 'la', 'el', 'los', 'las', 'for', 'pour', 'of', 'and',
    'y', 'a', 'en', 'with', 'the', 'al',
}


def _limpiar(texto: str, max_len: int = 30) -> str:
    """Slugifica + uppercase + remueve stopwords + recorta."""
    if not texto:
        return ''
    palabras = [
        p for p in re.split(r'[\s\-_/]+', texto.lower())
        if p and p not in STOPWORDS
    ]
    s = '-'.join(palabras)
    s = slugify(s).upper()  # slugify normaliza acentos y caracteres raros
    return s[:max_len].rstrip('-')


def _formato_valor(valor: str) -> str:
    """Normaliza un valor de atributo para el SKU.

    `'100 ml'`  ->  `'100ML'`
    `'EDP'`     ->  `'EDP'`
    `'Verde Oscuro'` -> `'VERDE-OSCURO'`
    """
    s = re.sub(r'\s+', '', valor.strip()).upper()  # primero saca espacios
    s = slugify(s.lower()).upper() or s
    return s[:15]


def generar_sku(*, marca: str = '', nombre: str = '',
                valores: list[str] | None = None) -> str:
    """Construye un SKU desde los componentes. NO consulta la BD.

    Para garantizar unicidad usar `generar_sku_unico` (abajo).
    """
    partes = []
    if marca:
        partes.append(_limpiar(marca, max_len=15))
    if nombre:
        partes.append(_limpiar(nombre, max_len=25))
    for v in (valores or []):
        if v:
            partes.append(_formato_valor(v))
    sku = '-'.join(p for p in partes if p)
    return sku[:60]  # cap al maximo del modelo


def generar_sku_unico(*, marca: str = '', nombre: str = '',
                      valores: list[str] | None = None,
                      excluir_pk: int | None = None) -> str:
    """Como `generar_sku` pero garantiza unicidad consultando la BD.

    Si el SKU base ya esta tomado por OTRA variante, agrega sufijo
    incremental: `-2`, `-3`, etc.
    """
    from catalogo.models import ProductoVariante

    base = generar_sku(marca=marca, nombre=nombre, valores=valores)
    if not base:
        # Fallback: si no hay datos, devolvemos un SKU placeholder con timestamp.
        from time import time
        return f'SKU-{int(time())}'

    candidato = base
    sufijo = 2
    qs = ProductoVariante.objects.exclude(pk=excluir_pk) if excluir_pk else ProductoVariante.objects.all()
    while qs.filter(sku=candidato).exists():
        candidato = f'{base[:60 - len(str(sufijo)) - 1]}-{sufijo}'
        sufijo += 1
        if sufijo > 9999:  # circuit breaker
            raise RuntimeError(f'No se pudo encontrar SKU unico para base {base}')
    return candidato


def sugerir_desde_variante(variante) -> str:
    """Helper de conveniencia: arma SKU desde una `ProductoVariante` con
    sus valores ya asignados. Util para el botón "Generar" del admin.
    """
    valores = [v.valor for v in variante.valores.all().order_by(
        'atributo__nombre', 'orden', 'valor'
    )]
    return generar_sku_unico(
        marca=variante.producto.marca or '',
        nombre=variante.producto.nombre,
        valores=valores,
        excluir_pk=variante.pk,
    )
