"""Carrito de cajero en sesión.

Formato interno:
    session['pos_cart'] = {
        'v:<variante_id>': cantidad,
        'p:<producto_id>': cantidad,
    }

Las líneas distinguen variante vs producto-sin-variantes. Los precios y
stocks se leen de la DB al renderizar (no se cachean en sesión) para que
cambios del admin se reflejen inmediatamente.
"""

from decimal import Decimal

from django.utils import timezone

from catalogo.models import Oferta, Producto, ProductoVariante

SESSION_KEY = 'pos_cart'


def _key_variante(variante_id: int) -> str:
    return f'v:{variante_id}'


def _key_producto(producto_id: int) -> str:
    return f'p:{producto_id}'


class Cart:
    def __init__(self, session):
        self.session = session
        self._items = session.get(SESSION_KEY, {})

    def _save(self):
        self.session[SESSION_KEY] = self._items
        self.session.modified = True

    # --- mutaciones ---

    def add_variante(self, variante_id: int, cantidad: int = 1):
        key = _key_variante(variante_id)
        self._items[key] = self._items.get(key, 0) + cantidad
        self._save()

    def add_producto(self, producto_id: int, cantidad: int = 1):
        key = _key_producto(producto_id)
        self._items[key] = self._items.get(key, 0) + cantidad
        self._save()

    def set_cantidad(self, key: str, cantidad: int):
        if cantidad <= 0:
            self._items.pop(key, None)
        else:
            self._items[key] = cantidad
        self._save()

    def remove(self, key: str):
        self._items.pop(key, None)
        self._save()

    def clear(self):
        self._items = {}
        self.session.pop(SESSION_KEY, None)
        self.session.modified = True

    # --- lectura ---

    @property
    def items_count(self) -> int:
        return sum(self._items.values())

    def is_empty(self) -> bool:
        return not self._items

    def lineas(self, canal: str = 'presencial'):
        """Genera líneas enriquecidas: (key, item, cantidad, precio_unitario, descuento, subtotal).

        `item` es un ProductoVariante o un Producto.
        `descuento` es el total (no por unidad) aplicado por ofertas vigentes.
        """
        ahora = timezone.now()
        variante_ids = [int(k.split(':')[1]) for k in self._items if k.startswith('v:')]
        producto_ids = [int(k.split(':')[1]) for k in self._items if k.startswith('p:')]

        variantes = {
            v.pk: v
            for v in ProductoVariante.objects.select_related('producto').filter(pk__in=variante_ids)
        }
        productos = {p.pk: p for p in Producto.objects.filter(pk__in=producto_ids)}

        for key, cantidad in self._items.items():
            tipo, raw_id = key.split(':')
            item_id = int(raw_id)
            if tipo == 'v':
                item = variantes.get(item_id)
            else:
                item = productos.get(item_id)
            if item is None:
                continue

            precio_unit = _precio_unitario(item)
            descuento_unit = _descuento_unitario(item, precio_unit, canal, ahora)
            descuento_total = descuento_unit * cantidad
            subtotal = (precio_unit * cantidad) - descuento_total
            yield {
                'key': key,
                'tipo': tipo,
                'item': item,
                'cantidad': cantidad,
                'precio_unitario': precio_unit,
                'descuento_unitario': descuento_unit,
                'descuento_total': descuento_total,
                'subtotal': subtotal,
            }

    def totales(self, canal: str = 'presencial'):
        """Devuelve (subtotal_bruto, descuento_total, total_neto)."""
        subtotal_bruto = Decimal('0')
        descuento_total = Decimal('0')
        for linea in self.lineas(canal=canal):
            subtotal_bruto += linea['precio_unitario'] * linea['cantidad']
            descuento_total += linea['descuento_total']
        return subtotal_bruto, descuento_total, subtotal_bruto - descuento_total


def _precio_unitario(item):
    if isinstance(item, ProductoVariante):
        return item.precio
    return item.precio_base


def _descuento_unitario(item, precio_unit: Decimal, canal: str, ahora) -> Decimal:
    """Descuento por unidad según la mejor oferta vigente para item+canal."""
    if isinstance(item, ProductoVariante):
        ofertas_qs = Oferta.objects.filter(
            activa=True,
            fecha_inicio__lte=ahora,
            fecha_fin__gte=ahora,
        ).filter(
            # oferta puntual de la variante o del producto padre
            variante=item,
        ) | Oferta.objects.filter(
            activa=True,
            fecha_inicio__lte=ahora,
            fecha_fin__gte=ahora,
            producto=item.producto,
            variante__isnull=True,
        )
    else:
        ofertas_qs = Oferta.objects.filter(
            activa=True,
            fecha_inicio__lte=ahora,
            fecha_fin__gte=ahora,
            producto=item,
            variante__isnull=True,
        )

    mejor = Decimal('0')
    for oferta in ofertas_qs:
        if not oferta.aplica_a_canal(canal):
            continue
        if oferta.tipo == Oferta.TIPO_PORCENTAJE:
            candidato = (precio_unit * oferta.valor) / Decimal('100')
        else:
            candidato = oferta.valor
        if candidato > mejor:
            mejor = candidato
    # No descontar más que el propio precio
    return min(mejor, precio_unit)
