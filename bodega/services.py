"""Servicios de bodega: compra de materiales y recepción de lotes producidos.

Dos operaciones principales que abarcan stock + contabilidad:

1. `comprar_material`: entra rollos a la bodega, sale plata de la caja.
2. `recibir_lote`: salen rollos de la bodega, entra producto terminado a la
   tienda, sale plata de la caja (pago al confeccionista — incluye los
   accesorios que él compró).

Ambas son atómicas: si algo falla, ningún side-effect se persiste.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from django.db import transaction
from django.db.models import F

from bodega.models import (
    Bodega,
    Material,
    MovimientoMaterial,
    MovimientoStock,
    StockMaterial,
    StockTienda,
    Tienda,
)


class StockMaterialInsuficiente(Exception):
    def __init__(self, material: Material, disponible: int, solicitado: int):
        self.material = material
        self.disponible = disponible
        self.solicitado = solicitado
        super().__init__(
            f'Stock insuficiente de {material.nombre}: '
            f'disponible={disponible} rollos, solicitado={solicitado}'
        )


@dataclass
class LineaProduccion:
    """Una línea del lote: variante producida + cantidad recibida del taller."""
    variante_id: int
    cantidad: int


@transaction.atomic
def comprar_material(
    *,
    material: Material,
    bodega: Bodega,
    cantidad: int,
    costo_total: Decimal,
    tienda_caja: Tienda,
    referencia: str = '',
    usuario=None,
) -> MovimientoMaterial:
    """Registra la compra de N rollos a un proveedor.

    Side-effects (todo en una transacción):
      - Suma `cantidad` rollos a `StockMaterial(bodega, material)`.
      - Crea `MovimientoMaterial.ENTRADA` con costo_total real pagado.
      - Crea `MovimientoCaja.SALIDA` por costo_total con concepto autogenerado.

    `tienda_caja` indica de qué caja sale la plata (cuando hay múltiples
    tiendas; en el caso típico de una sola tienda se pasa esa).
    """
    if cantidad <= 0:
        raise ValueError('La cantidad de rollos debe ser mayor a 0')
    if costo_total < 0:
        raise ValueError('El costo total no puede ser negativo')

    # Lock de la fila de stock (puede no existir todavía).
    stock, _created = StockMaterial.objects.select_for_update().get_or_create(
        bodega=bodega, material=material, defaults={'cantidad': 0},
    )
    StockMaterial.objects.filter(pk=stock.pk).update(
        cantidad=F('cantidad') + cantidad
    )

    mov = MovimientoMaterial.objects.create(
        bodega=bodega,
        material=material,
        tipo=MovimientoMaterial.ENTRADA,
        cantidad=cantidad,
        costo_total=costo_total,
        referencia=referencia or f'Compra {cantidad} rollos {material.nombre}',
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )

    if costo_total > 0:
        # Asiento contable: salida de caja por la compra. NO es gasto del
        # período — es adquisición de inventario (activo).
        from contabilidad.services import registrar_salida
        from contabilidad.models import MovimientoCaja
        registrar_salida(
            tienda=tienda_caja,
            monto=costo_total,
            concepto=f'Compra material: {material.nombre} (×{cantidad} rollos)',
            usuario=usuario,
            categoria=MovimientoCaja.COSTO_INVENTARIO,
        )

    return mov


@transaction.atomic
def recibir_lote(
    *,
    material: Material,
    bodega: Bodega,
    rollos_consumidos: int,
    lineas: Iterable[LineaProduccion],
    tienda: Tienda,
    costo_confeccion: Decimal,
    referencia: str = '',
    usuario=None,
) -> MovimientoMaterial:
    """Registra la recepción de un lote del taller.

    Tres efectos en una sola transacción:
      1. Salida de `rollos_consumidos` de `StockMaterial(bodega, material)`.
      2. Entrada de cada `LineaProduccion` al `StockTienda` de la `tienda`
         (una fila de StockTienda por variante).
      3. Salida de caja por `costo_confeccion` (que ya incluye lo que el
         confeccionista pagó por accesorios — cuellos, puños, hilo, etc).

    Si no hay stock suficiente de rollos, levanta `StockMaterialInsuficiente`
    y la transacción se revierte completa — nada queda a medias.
    """
    lineas = list(lineas)
    if rollos_consumidos <= 0:
        raise ValueError('rollos_consumidos debe ser mayor a 0')
    if not lineas:
        raise ValueError('Debe haber al menos una línea producida')
    if costo_confeccion < 0:
        raise ValueError('costo_confeccion no puede ser negativo')

    # 1. Lock + descuento de stock de material.
    try:
        stock = StockMaterial.objects.select_for_update().get(
            bodega=bodega, material=material,
        )
    except StockMaterial.DoesNotExist:
        raise StockMaterialInsuficiente(material, 0, rollos_consumidos)
    if stock.cantidad < rollos_consumidos:
        raise StockMaterialInsuficiente(material, stock.cantidad, rollos_consumidos)
    StockMaterial.objects.filter(pk=stock.pk).update(
        cantidad=F('cantidad') - rollos_consumidos,
    )

    mov_material = MovimientoMaterial.objects.create(
        bodega=bodega,
        material=material,
        tipo=MovimientoMaterial.SALIDA,
        cantidad=rollos_consumidos,
        costo_total=Decimal('0'),  # la plata sale al pagar la confección
        referencia=referencia or f'Producción: {rollos_consumidos} rollos consumidos',
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )

    # 2. Suma a StockTienda y audita en MovimientoStock por cada línea.
    for ln in lineas:
        if ln.cantidad <= 0:
            raise ValueError(f'Cantidad de variante {ln.variante_id} debe ser > 0')
        fila, _ = StockTienda.objects.select_for_update().get_or_create(
            tienda=tienda, variante_id=ln.variante_id,
            defaults={'cantidad': 0},
        )
        StockTienda.objects.filter(pk=fila.pk).update(
            cantidad=F('cantidad') + ln.cantidad,
        )
        MovimientoStock.objects.create(
            tienda=tienda,
            variante_id=ln.variante_id,
            tipo=MovimientoStock.ENTRADA,
            cantidad=ln.cantidad,
            referencia=referencia or f'Recepción taller (mov material #{mov_material.pk})',
            usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
        )

    # 3. Asiento contable: pago al confeccionista (incluye accesorios).
    # NO es gasto del período — su costo se activa en precio_costo de
    # cada prenda terminada, y aparece en EERR cuando se vende.
    if costo_confeccion > 0:
        from contabilidad.services import registrar_salida
        from contabilidad.models import MovimientoCaja
        registrar_salida(
            tienda=tienda,
            monto=costo_confeccion,
            concepto=f'Confección lote: {sum(ln.cantidad for ln in lineas)} prendas',
            usuario=usuario,
            categoria=MovimientoCaja.COSTO_PRODUCCION,
        )

    return mov_material


# ----------------------------------------------------------------------------
# Capacidad y valor potencial
# ----------------------------------------------------------------------------

@dataclass
class CapacidadVariante:
    variante_id: int
    variante_label: str
    material_nombre: str
    rollos_disponibles: int
    unidades_por_rollo: int
    capacidad: int  # floor(rollos × unidades_por_rollo)
    precio_venta: Decimal
    valor_potencial: Decimal  # capacidad × precio_venta


def capacidad_por_variante(bodega: Bodega) -> list[CapacidadVariante]:
    """Para cada variante con `Rendimiento`, calcula cuántas unidades se
    pueden producir dado el stock actual de su material en `bodega`.

    Las variantes sin rendimiento configurado quedan fuera del listado.
    """
    from bodega.models import Rendimiento

    rendimientos = (
        Rendimiento.objects
        .select_related('material', 'variante__producto')
        .order_by('variante__producto__nombre', 'variante__sku')
    )
    stocks = {
        sm.material_id: sm.cantidad
        for sm in StockMaterial.objects.filter(bodega=bodega)
    }

    out: list[CapacidadVariante] = []
    for r in rendimientos:
        rollos = stocks.get(r.material_id, 0)
        capacidad = rollos * r.unidades_por_rollo
        precio = r.variante.precio_override or r.variante.producto.precio_base
        valor_potencial = Decimal(capacidad) * precio
        valores = ', '.join(str(v) for v in r.variante.valores.all())
        label = f'{r.variante.producto.nombre} [{r.variante.sku}]'
        if valores:
            label += f' ({valores})'
        out.append(CapacidadVariante(
            variante_id=r.variante_id,
            variante_label=label,
            material_nombre=r.material.nombre,
            rollos_disponibles=rollos,
            unidades_por_rollo=r.unidades_por_rollo,
            capacidad=capacidad,
            precio_venta=precio,
            valor_potencial=valor_potencial,
        ))
    return out


@dataclass
class ResumenProduccion:
    bodega: Bodega
    capacidades: list[CapacidadVariante]
    valor_materiales: Decimal       # costo (referencia) de los rollos en bodega
    valor_potencial_total: Decimal  # Σ capacidad × precio venta


def resumen_produccion(bodega: Bodega) -> ResumenProduccion:
    capacidades = capacidad_por_variante(bodega)
    valor_potencial_total = sum(
        (c.valor_potencial for c in capacidades), Decimal('0')
    )
    valor_materiales = Decimal('0')
    for sm in StockMaterial.objects.filter(bodega=bodega).select_related('material'):
        valor_materiales += Decimal(sm.cantidad) * sm.material.costo_unitario_referencia
    return ResumenProduccion(
        bodega=bodega,
        capacidades=capacidades,
        valor_materiales=valor_materiales,
        valor_potencial_total=valor_potencial_total,
    )
