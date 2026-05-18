"""Servicios de contabilidad.

Principios:
- Las ventas pagadas (`ReciboVenta` en estado `pagado`) se reflejan como
  `MovimientoCaja.ENTRADA` con FK al recibo. La operación es idempotente:
  dos llamadas seguidas producen un solo asiento.
- Los egresos manuales (arriendo, sueldos, compra a proveedor) se registran
  con `registrar_salida` desde el admin.
- La valorización de activos (`valor_inventario`) es `sum(stock ×
  precio_costo)` por tienda, al momento de la consulta; no se persiste.
- El saldo de caja se computa como suma de entradas − suma de salidas en
  la ventana indicada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from bodega.models import StockMaterial, StockTienda, Tienda
from contabilidad.models import MovimientoCaja
from pos.models import ReciboVenta


@dataclass
class ResumenCaja:
    entradas: Decimal
    salidas: Decimal

    @property
    def saldo(self) -> Decimal:
        return self.entradas - self.salidas


@transaction.atomic
def registrar_ingreso_venta(recibo: ReciboVenta, usuario=None) -> Optional[MovimientoCaja]:
    """Crea un MovimientoCaja.ENTRADA por un recibo pagado si no existe aún.

    Devuelve el MovimientoCaja creado o `None` si el recibo no está pagado
    o ya había un asiento previo.
    """
    if recibo.estado != ReciboVenta.ESTADO_PAGADO:
        return None

    # Lock sobre recibo para evitar doble-asiento en concurrencia.
    ReciboVenta.objects.select_for_update().filter(pk=recibo.pk).exists()
    if MovimientoCaja.objects.filter(
        recibo_venta=recibo, tipo=MovimientoCaja.ENTRADA
    ).exists():
        return None

    concepto = f'Venta #{recibo.pk} ({recibo.get_canal_display()})'
    return MovimientoCaja.objects.create(
        tienda=recibo.tienda,
        tipo=MovimientoCaja.ENTRADA,
        categoria=MovimientoCaja.INGRESO_VENTA,
        monto=recibo.total,
        concepto=concepto,
        recibo_venta=recibo,
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )


def registrar_salida(
    *,
    tienda: Tienda,
    monto: Decimal,
    concepto: str,
    usuario=None,
    categoria: str = MovimientoCaja.GASTO_OPERATIVO,
) -> MovimientoCaja:
    """Registra un egreso. Default: gasto operativo (arriendo, sueldos).

    Para compras de inventario y pagos de producción, los servicios de
    bodega pasan la categoría correcta (`COSTO_INVENTARIO` /
    `COSTO_PRODUCCION`) para no inflar el EERR con flujos que en realidad
    son adquisición de activos.
    """
    if monto <= 0:
        raise ValueError('El monto de la salida debe ser mayor a 0')
    if not concepto.strip():
        raise ValueError('El concepto es obligatorio')
    if categoria not in dict(MovimientoCaja.CATEGORIA_CHOICES):
        raise ValueError(f'Categoría inválida: {categoria!r}')
    return MovimientoCaja.objects.create(
        tienda=tienda,
        tipo=MovimientoCaja.SALIDA,
        categoria=categoria,
        monto=monto,
        concepto=concepto.strip(),
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )


def resumen_caja(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
) -> ResumenCaja:
    """Resumen de entradas y salidas en la ventana indicada."""
    qs = MovimientoCaja.objects.all()
    if tienda is not None:
        qs = qs.filter(tienda=tienda)
    if desde is not None:
        qs = qs.filter(fecha__gte=desde)
    if hasta is not None:
        qs = qs.filter(fecha__lt=hasta)

    agregados = qs.aggregate(
        entradas=Coalesce(
            Sum('monto', filter=Q(tipo=MovimientoCaja.ENTRADA)),
            Value(Decimal('0')),
        ),
        salidas=Coalesce(
            Sum('monto', filter=Q(tipo=MovimientoCaja.SALIDA)),
            Value(Decimal('0')),
        ),
    )
    return ResumenCaja(entradas=agregados['entradas'], salidas=agregados['salidas'])


def valor_inventario(tienda: Optional[Tienda] = None) -> Decimal:
    """Suma `stock.cantidad × precio_costo` para valorizar el activo.

    Incluye:
      - Productos terminados en `StockTienda` (variantes y productos directos).
      - Rollos de material en `StockMaterial` (a costo unitario de referencia).
        Cuando se filtra por `tienda`, se incluyen los materiales en bodegas
        que pertenecen a esa tienda (`Bodega.tienda`).

    Si una variante tiene `precio_override`, el costo sigue siendo el del
    producto padre (el override refiere al precio de venta, no al costo).
    """
    qs = StockTienda.objects.all()
    if tienda is not None:
        qs = qs.filter(tienda=tienda)

    total = Decimal('0')
    # Stock de variantes → costo desde producto padre.
    variantes_valor = (
        qs.filter(variante__isnull=False)
        .annotate(valor=F('cantidad') * F('variante__producto__precio_costo'))
        .aggregate(total=Coalesce(Sum('valor'), Value(Decimal('0'))))
    )['total']
    total += variantes_valor

    # Stock de productos directos.
    directos_valor = (
        qs.filter(producto__isnull=False)
        .annotate(valor=F('cantidad') * F('producto__precio_costo'))
        .aggregate(total=Coalesce(Sum('valor'), Value(Decimal('0'))))
    )['total']
    total += directos_valor

    # Materiales en bodega (rollos) a costo unitario de referencia.
    mats_qs = StockMaterial.objects.all()
    if tienda is not None:
        mats_qs = mats_qs.filter(bodega__tienda=tienda)
    materiales_valor = mats_qs.annotate(
        valor=F('cantidad') * F('material__costo_unitario_referencia'),
    ).aggregate(total=Coalesce(Sum('valor'), Value(Decimal('0'))))['total']
    total += materiales_valor

    return total


# ============================================================================
# Estado de Resultados (P&L) y Balance General — Fase O
# ============================================================================

@dataclass
class EstadoResultados:
    desde: object  # datetime
    hasta: object  # datetime
    ingresos: Decimal
    costo_ventas: Decimal
    margen_bruto: Decimal
    margen_pct: Decimal       # como decimal 0..1, multiplicar por 100 para %
    gastos_operativos: Decimal
    utilidad_neta: Decimal
    desglose_gastos: list     # [{categoria, label, monto}]
    # Mejora EERR: desglose por linea de negocio (Familia del catalogo).
    # Cada item: {familia, ingresos, cogs, margen, margen_pct, n_lineas}.
    # Ordenado por margen descendente.
    desglose_por_familia: list = field(default_factory=list)


def estado_resultados(
    *,
    desde,
    hasta,
    tienda: Optional[Tienda] = None,
) -> EstadoResultados:
    """Estado de Resultados de la ventana indicada.

    Definiciones:
      - Ingresos = total de ventas pagadas (`ReciboVenta` en estado pagado).
      - Costo de Ventas (COGS) = Σ cantidad × producto.precio_costo de
        cada detalle de las ventas pagadas. Usa el costo del producto al
        momento del cálculo (no se persiste el costo en cada detalle).
      - Margen Bruto = Ingresos − COGS.
      - Gastos Operativos = `MovimientoCaja.SALIDA` con categoria=
        `gasto_operativo` (no incluye compras de inventario ni pagos de
        confección — esos son flujos de caja, no gastos del período).
      - Utilidad Neta = Margen Bruto − Gastos Operativos.

    Las compras de tela / pagos a confeccionistas afectan caja y aumentan
    el valor del inventario, pero NO se cuentan acá: ya están "activadas"
    en el `precio_costo` de los productos terminados.
    """
    from pos.models import ReciboVenta, ReciboVentaDetalle

    # Ingresos.
    recibos_qs = ReciboVenta.objects.filter(
        estado=ReciboVenta.ESTADO_PAGADO,
        creado__gte=desde, creado__lte=hasta,
    )
    if tienda is not None:
        recibos_qs = recibos_qs.filter(tienda=tienda)
    ingresos = recibos_qs.aggregate(
        s=Coalesce(Sum('total'), Value(Decimal('0')), output_field=DecimalField())
    )['s']

    # COGS: una variante saca su precio_costo del producto padre.
    detalles_qs = ReciboVentaDetalle.objects.filter(recibo__in=recibos_qs)
    cogs_v = detalles_qs.filter(variante__isnull=False).annotate(
        c=F('cantidad') * F('variante__producto__precio_costo'),
    ).aggregate(s=Coalesce(Sum('c'), Value(Decimal('0')),
                            output_field=DecimalField()))['s']
    cogs_p = detalles_qs.filter(producto__isnull=False).annotate(
        c=F('cantidad') * F('producto__precio_costo'),
    ).aggregate(s=Coalesce(Sum('c'), Value(Decimal('0')),
                            output_field=DecimalField()))['s']
    costo_ventas = cogs_v + cogs_p

    margen_bruto = ingresos - costo_ventas
    margen_pct = (margen_bruto / ingresos) if ingresos > 0 else Decimal('0')

    # Gastos operativos.
    gastos_qs = MovimientoCaja.objects.filter(
        tipo=MovimientoCaja.SALIDA,
        categoria=MovimientoCaja.GASTO_OPERATIVO,
        fecha__gte=desde, fecha__lte=hasta,
    )
    if tienda is not None:
        gastos_qs = gastos_qs.filter(tienda=tienda)
    gastos_operativos = gastos_qs.aggregate(
        s=Coalesce(Sum('monto'), Value(Decimal('0')), output_field=DecimalField())
    )['s']

    utilidad_neta = margen_bruto - gastos_operativos

    # Desglose de gastos por concepto (top 10).
    desglose = list(
        gastos_qs.values('concepto')
        .annotate(monto=Sum('monto'))
        .order_by('-monto')[:10]
    )

    # Desglose por familia (linea de negocio). Cada familia con su
    # ingreso, su COGS y su margen. Util para decidir cual linea
    # priorizar — ej. perfumes vs uniformes vs moda.
    desglose_familia = _desglose_por_familia(detalles_qs)

    return EstadoResultados(
        desde=desde, hasta=hasta,
        ingresos=ingresos,
        costo_ventas=costo_ventas,
        margen_bruto=margen_bruto,
        margen_pct=margen_pct,
        gastos_operativos=gastos_operativos,
        utilidad_neta=utilidad_neta,
        desglose_gastos=desglose,
        desglose_por_familia=desglose_familia,
    )


def _desglose_por_familia(detalles_qs) -> list[dict]:
    """Agrega ingresos y COGS por Familia del catalogo.

    Cada `ReciboVentaDetalle` apunta o a un `ProductoVariante` (y de ahi
    al `Producto`) o a un `Producto` directo. La `Familia` cuelga del
    Producto. Hacemos las 2 agregaciones por separado y las mergeamos
    en Python (mas claro que un union/exists complejo en SQL).

    Devuelve lista ordenada por margen descendente:
        [{familia, ingresos, cogs, margen, margen_pct, n_lineas}, ...]
    """
    # Ingresos por familia desde variantes.
    ing_var = (
        detalles_qs.filter(variante__isnull=False)
        .values(fam=F('variante__producto__familia__nombre'))
        .annotate(
            ingresos=Coalesce(
                Sum(F('cantidad') * F('precio_unitario') - F('descuento')),
                Value(Decimal('0')), output_field=DecimalField(),
            ),
            cogs=Coalesce(
                Sum(F('cantidad') * F('variante__producto__precio_costo')),
                Value(Decimal('0')), output_field=DecimalField(),
            ),
            n_lineas=Sum('cantidad'),
        )
    )
    # Idem desde productos sin variantes.
    ing_prod = (
        detalles_qs.filter(producto__isnull=False)
        .values(fam=F('producto__familia__nombre'))
        .annotate(
            ingresos=Coalesce(
                Sum(F('cantidad') * F('precio_unitario') - F('descuento')),
                Value(Decimal('0')), output_field=DecimalField(),
            ),
            cogs=Coalesce(
                Sum(F('cantidad') * F('producto__precio_costo')),
                Value(Decimal('0')), output_field=DecimalField(),
            ),
            n_lineas=Sum('cantidad'),
        )
    )

    # Merge en Python (familia es el key).
    agg: dict[str, dict] = {}
    for row in list(ing_var) + list(ing_prod):
        fam_nombre = row['fam'] or '(sin familia)'
        bucket = agg.setdefault(fam_nombre, {
            'familia': fam_nombre,
            'ingresos': Decimal('0'),
            'cogs': Decimal('0'),
            'n_lineas': 0,
        })
        bucket['ingresos'] += row['ingresos']
        bucket['cogs'] += row['cogs']
        bucket['n_lineas'] += int(row['n_lineas'] or 0)

    # Calcular margen y margen_pct.
    out = []
    for bucket in agg.values():
        margen = bucket['ingresos'] - bucket['cogs']
        margen_pct = (margen / bucket['ingresos']) if bucket['ingresos'] > 0 else Decimal('0')
        out.append({
            **bucket,
            'margen': margen,
            'margen_pct': margen_pct,
        })
    out.sort(key=lambda d: d['margen'], reverse=True)
    return out


@dataclass
class BalanceGeneral:
    fecha: object  # datetime
    caja: Decimal
    inventario_terminado: Decimal
    inventario_materia_prima: Decimal
    total_activos: Decimal
    total_pasivos: Decimal     # 0 hoy — sin cuentas por pagar
    patrimonio: Decimal


def balance_general(
    *,
    fecha=None,
    tienda: Optional[Tienda] = None,
) -> BalanceGeneral:
    """Snapshot patrimonial al `fecha` (default: ahora).

    Activos:
      - Caja: saldo histórico (Σ entradas − Σ salidas hasta `fecha`).
      - Inventario terminado: Σ StockTienda × precio_costo (al momento).
      - Inventario materia prima: Σ StockMaterial × costo unitario ref.

    Pasivos: 0 (no modelamos cuentas por pagar todavía).
    Patrimonio = Activos − Pasivos.

    Nota: el inventario es snapshot del momento, no del `fecha` histórica
    — si `fecha` es pasado, el inventario igual se calcula con el stock
    actual. Para un balance histórico exacto habría que armar movimientos
    inversos; lo dejamos para una fase posterior si vale la pena.
    """
    from django.utils import timezone
    if fecha is None:
        fecha = timezone.now()

    # Caja: saldo histórico.
    caja_qs = MovimientoCaja.objects.filter(fecha__lte=fecha)
    if tienda is not None:
        caja_qs = caja_qs.filter(tienda=tienda)
    agg = caja_qs.aggregate(
        e=Coalesce(Sum('monto', filter=Q(tipo=MovimientoCaja.ENTRADA)),
                   Value(Decimal('0')), output_field=DecimalField()),
        s=Coalesce(Sum('monto', filter=Q(tipo=MovimientoCaja.SALIDA)),
                   Value(Decimal('0')), output_field=DecimalField()),
    )
    caja = agg['e'] - agg['s']

    # Inventario terminado.
    stt_qs = StockTienda.objects.all()
    if tienda is not None:
        stt_qs = stt_qs.filter(tienda=tienda)
    inv_v = stt_qs.filter(variante__isnull=False).annotate(
        v=F('cantidad') * F('variante__producto__precio_costo'),
    ).aggregate(s=Coalesce(Sum('v'), Value(Decimal('0'))))['s']
    inv_p = stt_qs.filter(producto__isnull=False).annotate(
        v=F('cantidad') * F('producto__precio_costo'),
    ).aggregate(s=Coalesce(Sum('v'), Value(Decimal('0'))))['s']
    inventario_terminado = inv_v + inv_p

    # Materia prima.
    mat_qs = StockMaterial.objects.all()
    if tienda is not None:
        mat_qs = mat_qs.filter(bodega__tienda=tienda)
    inventario_mp = mat_qs.annotate(
        v=F('cantidad') * F('material__costo_unitario_referencia'),
    ).aggregate(s=Coalesce(Sum('v'), Value(Decimal('0'))))['s']

    total_activos = caja + inventario_terminado + inventario_mp
    pasivos = Decimal('0')
    patrimonio = total_activos - pasivos

    return BalanceGeneral(
        fecha=fecha,
        caja=caja,
        inventario_terminado=inventario_terminado,
        inventario_materia_prima=inventario_mp,
        total_activos=total_activos,
        total_pasivos=pasivos,
        patrimonio=patrimonio,
    )


@dataclass
class PuntoMensual:
    anio: int
    mes: int
    label: str       # 'Ene 2026'
    ingresos: Decimal
    costo_ventas: Decimal
    margen_bruto: Decimal
    gastos: Decimal
    utilidad: Decimal


_MESES_ABREV = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def serie_mensual(
    *,
    desde,
    hasta,
    tienda: Optional[Tienda] = None,
) -> list[PuntoMensual]:
    """Lista de meses con su EERR para un chart de evolución."""
    from datetime import datetime
    from django.utils import timezone

    if timezone.is_naive(desde):
        desde = timezone.make_aware(desde)
    if timezone.is_naive(hasta):
        hasta = timezone.make_aware(hasta)

    # Genera lista de (anio, mes) entre desde y hasta inclusive.
    actual_y, actual_m = desde.year, desde.month
    fin_y, fin_m = hasta.year, hasta.month
    out: list[PuntoMensual] = []
    while (actual_y, actual_m) <= (fin_y, fin_m):
        # Inicio del mes.
        inicio = timezone.make_aware(datetime(actual_y, actual_m, 1))
        # Fin del mes (último segundo del último día).
        if actual_m == 12:
            siguiente = timezone.make_aware(datetime(actual_y + 1, 1, 1))
        else:
            siguiente = timezone.make_aware(datetime(actual_y, actual_m + 1, 1))

        eerr = estado_resultados(desde=inicio, hasta=siguiente, tienda=tienda)
        out.append(PuntoMensual(
            anio=actual_y, mes=actual_m,
            label=f'{_MESES_ABREV[actual_m - 1]} {actual_y}',
            ingresos=eerr.ingresos,
            costo_ventas=eerr.costo_ventas,
            margen_bruto=eerr.margen_bruto,
            gastos=eerr.gastos_operativos,
            utilidad=eerr.utilidad_neta,
        ))

        actual_m += 1
        if actual_m > 12:
            actual_m = 1
            actual_y += 1
    return out
