"""Cálculo de precios con oferta vigente.

Helpers públicos para mostrar precios con descuento en el catálogo,
PDP, cart y POS. La lógica de "cuál es la mejor oferta vigente para
este item en este canal" vive acá — antes estaba enterrada en
`pos.cart._descuento_unitario`. Ahora `pos.cart` y `ecommerce.cart`
la importan desde acá, y los templates pueden usar `precio_oferta_*`
properties que la calculan también.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from catalogo.models import Oferta, Producto, ProductoVariante


def precio_unitario(item) -> Decimal:
    """Precio base de un item sin descuento — variante o producto."""
    if isinstance(item, ProductoVariante):
        return item.precio
    return item.precio_base


def _ofertas_para_item(item):
    """Queryset de ofertas que apuntan a este item (no filtra fecha/canal/activa)."""
    if isinstance(item, ProductoVariante):
        # Ofertas puntuales de la variante O del producto padre (que aplican
        # a todas las variantes).
        return Oferta.objects.filter(variante=item) | Oferta.objects.filter(
            producto=item.producto, variante__isnull=True,
        )
    return Oferta.objects.filter(producto=item, variante__isnull=True)


def mejor_descuento_unitario(item, canal: str, ahora=None):
    """Devuelve (descuento_unit, oferta_aplicada).

    `oferta_aplicada` es la `Oferta` cuyo descuento ganó (o None si no
    hay ofertas vigentes). `descuento_unit` es un `Decimal >= 0` capeado
    al precio del item.
    """
    ahora = ahora or timezone.now()
    precio_unit = precio_unitario(item)

    qs = _ofertas_para_item(item).filter(
        activa=True,
        fecha_inicio__lte=ahora,
        fecha_fin__gte=ahora,
    )

    mejor_desc = Decimal('0')
    mejor_oferta = None
    for oferta in qs:
        if not oferta.aplica_a_canal(canal):
            continue
        if oferta.tipo == Oferta.TIPO_PORCENTAJE:
            candidato = (precio_unit * oferta.valor) / Decimal('100')
        else:
            candidato = oferta.valor
        if candidato > mejor_desc:
            mejor_desc = candidato
            mejor_oferta = oferta

    return (min(mejor_desc, precio_unit), mejor_oferta)


def descuento_unitario(item, precio_unit: Decimal, canal: str, ahora=None) -> Decimal:
    """Wrapper retrocompatible para pos.cart / ecommerce.cart.

    Solo devuelve el monto del descuento (sin la oferta). Mantiene la
    firma vieja para no romper imports existentes.
    """
    ahora = ahora or timezone.now()
    qs = _ofertas_para_item(item).filter(
        activa=True,
        fecha_inicio__lte=ahora,
        fecha_fin__gte=ahora,
    )

    mejor = Decimal('0')
    for oferta in qs:
        if not oferta.aplica_a_canal(canal):
            continue
        if oferta.tipo == Oferta.TIPO_PORCENTAJE:
            candidato = (precio_unit * oferta.valor) / Decimal('100')
        else:
            candidato = oferta.valor
        if candidato > mejor:
            mejor = candidato
    return min(mejor, precio_unit)
