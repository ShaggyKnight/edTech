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

from django.db.models import Q
from django.utils import timezone

from catalogo.models import Oferta, Producto, ProductoVariante


def precio_unitario(item) -> Decimal:
    """Precio base de un item sin descuento — variante o producto."""
    if isinstance(item, ProductoVariante):
        return item.precio
    return item.precio_base


# Ofertas SIN target puntual: aplican a una familia entera o (con familia
# también en NULL) a toda la tienda.
_SIN_TARGET_PUNTUAL = Q(producto__isnull=True, variante__isnull=True)


def _ofertas_para_item(item):
    """Queryset de ofertas que alcanzan a este item (no filtra fecha/canal/activa).

    Cuatro alcances, de más puntual a más amplio: la variante misma, su
    producto padre, la familia del producto y toda la tienda. Acá se juntan
    TODAS las candidatas; `mejor_descuento_unitario` elige la que más
    descuenta (no se acumulan).
    """
    if isinstance(item, ProductoVariante):
        producto = item.producto
        return Oferta.objects.filter(
            Q(variante=item)
            | Q(producto=producto, variante__isnull=True)
            | (_SIN_TARGET_PUNTUAL & Q(familia_id=producto.familia_id))
            | (_SIN_TARGET_PUNTUAL & Q(familia__isnull=True))
        )
    return Oferta.objects.filter(
        Q(producto=item, variante__isnull=True)
        | (_SIN_TARGET_PUNTUAL & Q(familia_id=item.familia_id))
        | (_SIN_TARGET_PUNTUAL & Q(familia__isnull=True))
    )


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
