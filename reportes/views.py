"""Vistas de reportes (solo admin).

- `dashboard`: resumen de negocio (ventas por canal, serie diaria, top
  productos, saldo de caja, valor de inventario). Ventana configurable vía
  ?dias=N (default 30).
- `caja`: lista de MovimientoCaja con filtro por tienda, y formulario para
  registrar salidas manuales (arriendo, sueldos, compras).
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.roles import ADMIN, user_in_role
from bodega.models import Bodega, Tienda
from bodega.services import resumen_produccion
from contabilidad.models import MovimientoCaja
from contabilidad.services import (
    balance_general,
    estado_resultados,
    registrar_salida,
    resumen_caja,
    serie_mensual,
)

from .forms import CajaSalidaForm
from .services import resumen_negocio, ventas_por_periodo, ventana_por_defecto


def _es_admin(user):
    return user.is_authenticated and (user.is_superuser or user_in_role(user, ADMIN))


admin_required = user_passes_test(_es_admin, login_url='login')


@login_required
@admin_required
def dashboard(request):
    """Panel de indicadores del negocio.

    Soporta dos modos de respuesta:
      - GET normal: pagina completa (`reportes/dashboard.html`).
      - GET con header `HX-Request: true` (desde HTMX): solo el partial
        del contenido dinamico (`reportes/_dashboard_content.html`).
        Esto deja que los filtros refresquen sin recargar.
    """
    try:
        dias = max(1, min(365, int(request.GET.get('dias', 30))))
    except (TypeError, ValueError):
        dias = 30

    desde, hasta = ventana_por_defecto(dias)
    tienda_id = request.GET.get('tienda') or None
    tienda = None
    if tienda_id:
        tienda = Tienda.objects.filter(pk=tienda_id).first()

    # Mejora dashboard #3: filtro por canal. Solo aceptamos los valores
    # validos de ReciboVenta.CANAL_*; cualquier otra cosa se ignora.
    from pos.models import ReciboVenta
    canal_filtro = request.GET.get('canal') or None
    if canal_filtro not in (ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.CANAL_ONLINE):
        canal_filtro = None

    # `incluir_anterior=True` para mejora #1: calcula la variacion vs el
    # periodo previo (% bajo cada KPI). Costo extra: 1 query mas a recibos.
    resumen = resumen_negocio(
        tienda=tienda, desde=desde, hasta=hasta,
        canal=canal_filtro, incluir_anterior=True,
    )
    serie = ventas_por_periodo(
        tienda=tienda, desde=desde, hasta=hasta, canal=canal_filtro,
    )

    context = {
        'resumen': resumen,
        'serie': serie,
        'dias': dias,
        'canal_filtro': canal_filtro,
        'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
        'tienda_filtro': tienda,
        # Para los `?desde=...&hasta=...` de los links drill-down (mejora #2).
        'desde_iso': desde.date().isoformat(),
        'hasta_iso': hasta.date().isoformat(),
    }

    # HtmxMiddleware (ver edTech.middleware) setea `request.htmx` cuando
    # el header HX-Request viene en la request. Las requests "hx-boost"
    # NO se consideran partial — solo las que tienen target explicito
    # (que es nuestro caso con hx-target=#dashboard-content).
    if getattr(request, 'htmx', False):
        return render(request, 'reportes/_dashboard_content.html', context)
    return render(request, 'reportes/dashboard.html', context)


@login_required
@admin_required
def caja(request):
    """Movimientos de caja + registro de egresos manuales."""
    tienda_id = request.GET.get('tienda') or None
    tienda = Tienda.objects.filter(pk=tienda_id).first() if tienda_id else None

    if request.method == 'POST':
        form = CajaSalidaForm(request.POST)
        if form.is_valid():
            try:
                registrar_salida(
                    tienda=form.cleaned_data['tienda'],
                    monto=form.cleaned_data['monto'],
                    concepto=form.cleaned_data['concepto'],
                    usuario=request.user,
                )
                messages.success(request, 'Salida registrada.')
                return redirect(reverse('reportes:caja'))
            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        form = CajaSalidaForm()

    movimientos_qs = MovimientoCaja.objects.select_related(
        'tienda', 'recibo_venta', 'usuario'
    )
    if tienda is not None:
        movimientos_qs = movimientos_qs.filter(tienda=tienda)

    resumen = resumen_caja(tienda=tienda)

    return render(request, 'reportes/caja.html', {
        'form': form,
        'movimientos': movimientos_qs[:200],
        'resumen': resumen,
        'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
        'tienda_filtro': tienda,
    })


@login_required
@admin_required
def produccion(request):
    """Capacidad de producción y valor potencial por bodega.

    Muestra, para cada variante con `Rendimiento` configurado, cuántas
    unidades se pueden producir hoy y cuánto valdrían a precio de venta.
    """
    bodega_id = request.GET.get('bodega')
    bodegas = Bodega.objects.select_related('tienda').order_by('nombre')

    bodega = None
    if bodega_id:
        bodega = bodegas.filter(pk=bodega_id).first()
    if bodega is None:
        bodega = bodegas.first()

    resumen = resumen_produccion(bodega) if bodega else None

    return render(request, 'reportes/produccion.html', {
        'bodegas': bodegas,
        'bodega': bodega,
        'resumen': resumen,
    })


# ============================================================================
# Reportes financieros — Estado de Resultados + Balance General (Fase O)
# ============================================================================

def _parse_periodo(request):
    """Resuelve el rango (desde, hasta) según el querystring.

    Modos soportados:
      ?periodo=mes&anio=2026&mes=4   — un mes calendario
      ?periodo=anio&anio=2026         — un año calendario
      ?periodo=rango&desde=YYYY-MM-DD&hasta=YYYY-MM-DD — rango libre
    Default: mes actual.
    """
    from datetime import datetime, timedelta
    from django.utils import timezone
    now = timezone.localtime()
    modo = (request.GET.get('periodo') or 'mes').strip()
    try:
        anio = int(request.GET.get('anio') or now.year)
    except (TypeError, ValueError):
        anio = now.year
    try:
        mes = int(request.GET.get('mes') or now.month)
    except (TypeError, ValueError):
        mes = now.month

    if modo == 'anio':
        desde = timezone.make_aware(datetime(anio, 1, 1))
        hasta = timezone.make_aware(datetime(anio, 12, 31, 23, 59, 59))
        label = f'Año {anio}'
    elif modo == 'rango':
        try:
            desde = timezone.make_aware(
                datetime.strptime(request.GET['desde'], '%Y-%m-%d')
            )
            hasta = timezone.make_aware(
                datetime.strptime(request.GET['hasta'], '%Y-%m-%d')
            ) + timedelta(days=1, microseconds=-1)
            label = f'{desde:%d-%m-%Y} a {hasta:%d-%m-%Y}'
        except (KeyError, ValueError):
            modo = 'mes'  # fallback
    if modo == 'mes':
        desde = timezone.make_aware(datetime(anio, mes, 1))
        if mes == 12:
            sig = timezone.make_aware(datetime(anio + 1, 1, 1))
        else:
            sig = timezone.make_aware(datetime(anio, mes + 1, 1))
        hasta = sig - timedelta(microseconds=1)
        from contabilidad.services import _MESES_ABREV
        label = f'{_MESES_ABREV[mes-1]} {anio}'

    return desde, hasta, modo, anio, mes, label


@login_required
@admin_required
def eerr(request):
    """Estado de Resultados: ingresos − costo de ventas − gastos = utilidad.

    Filtros: período (mes/anio/rango) + tienda. Default mes actual.
    Incluye chart de evolución últimos 12 meses + sección de potencial
    de confección con la materia prima en bodega.
    """
    from datetime import datetime, timedelta
    from django.utils import timezone
    from bodega.services import resumen_produccion_global
    from reportes.services import variacion_pct

    desde, hasta, modo, anio, mes, label = _parse_periodo(request)

    tienda_id = request.GET.get('tienda') or None
    tienda = Tienda.objects.filter(pk=tienda_id).first() if tienda_id else None

    eerr_dato = estado_resultados(desde=desde, hasta=hasta, tienda=tienda)

    # Mejora #1: comparativa vs periodo anterior. Calculamos el EERR del
    # periodo inmediatamente anterior (mismo ancho, terminando donde
    # empieza el actual) y derivamos las variaciones.
    ancho = hasta - desde
    desde_prev = desde - ancho
    hasta_prev = desde
    eerr_prev = estado_resultados(desde=desde_prev, hasta=hasta_prev, tienda=tienda)

    eerr_anterior = {
        'desde': desde_prev,
        'hasta': hasta_prev,
        'ingresos': eerr_prev.ingresos,
        'costo_ventas': eerr_prev.costo_ventas,
        'margen_bruto': eerr_prev.margen_bruto,
        'margen_pct': eerr_prev.margen_pct,
        'utilidad_neta': eerr_prev.utilidad_neta,
        'var_ingresos': variacion_pct(eerr_dato.ingresos, eerr_prev.ingresos),
        'var_cogs': variacion_pct(eerr_dato.costo_ventas, eerr_prev.costo_ventas),
        'var_margen_bruto': variacion_pct(eerr_dato.margen_bruto, eerr_prev.margen_bruto),
        # Para el margen % calculamos delta en PUNTOS porcentuales (no %).
        # 40% actual vs 37% anterior → +3 ppts (no "+8% YoY").
        'delta_margen_pct_ppts': (
            int((eerr_dato.margen_pct - eerr_prev.margen_pct) * 100)
            if eerr_prev.margen_pct or eerr_dato.margen_pct else None
        ),
        'var_utilidad_neta': variacion_pct(eerr_dato.utilidad_neta, eerr_prev.utilidad_neta),
    }

    # Serie últimos 12 meses (incluye el período seleccionado).
    fin = timezone.localtime()
    inicio = fin.replace(day=1) - timedelta(days=1)
    inicio = inicio.replace(day=1)
    # Retroceder 11 meses más.
    for _ in range(11):
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    inicio = timezone.make_aware(datetime(inicio.year, inicio.month, 1))
    serie = serie_mensual(desde=inicio, hasta=fin, tienda=tienda)

    # Potencial: lo que se podría sumar al margen si confeccionás y
    # vendés todo lo que la tela actual permite. Es snapshot — no depende
    # del período del EERR — pero se muestra al lado para tener
    # contexto: "el margen del mes fue X, además podrías generar Y más
    # con la materia prima que ya pagaste".
    potencial = resumen_produccion_global()

    # Mejora #3: atajos rapidos de periodo. Construimos query-strings
    # que el template usa en chips clickeables (HTMX). Cada atajo
    # corresponde a un periodo predefinido + el `active` flag indica
    # cual matchea el periodo actual.
    hoy = timezone.localtime()
    mes_anterior_anio = hoy.year if hoy.month > 1 else hoy.year - 1
    mes_anterior_mes = hoy.month - 1 if hoy.month > 1 else 12
    atajos = [
        {
            'label': 'Este mes',
            'qs': f'periodo=mes&mes={hoy.month}&anio={hoy.year}',
            'active': modo == 'mes' and anio == hoy.year and mes == hoy.month,
        },
        {
            'label': 'Mes anterior',
            'qs': f'periodo=mes&mes={mes_anterior_mes}&anio={mes_anterior_anio}',
            'active': modo == 'mes' and anio == mes_anterior_anio and mes == mes_anterior_mes,
        },
        {
            'label': 'Este año',
            'qs': f'periodo=anio&anio={hoy.year}',
            'active': modo == 'anio' and anio == hoy.year,
        },
        {
            'label': 'Año anterior',
            'qs': f'periodo=anio&anio={hoy.year - 1}',
            'active': modo == 'anio' and anio == hoy.year - 1,
        },
        {
            'label': 'Últimos 12 meses',
            'qs': 'periodo=rango&desde='
                  + (hoy - timedelta(days=365)).strftime('%Y-%m-%d')
                  + '&hasta=' + hoy.strftime('%Y-%m-%d'),
            # Active solo si el modo es rango exactamente con esos limites.
            # No matcheamos rangos custom diferentes.
            'active': False,
        },
    ]

    context = {
        'eerr': eerr_dato,
        'eerr_anterior': eerr_anterior,
        'potencial': potencial,
        'atajos': atajos,
        'serie': [{
            'label': p.label,
            'ingresos': float(p.ingresos),
            'cogs': float(p.costo_ventas),
            'utilidad': float(p.utilidad),
        } for p in serie],
        'periodo': {
            'modo': modo, 'anio': anio, 'mes': mes, 'label': label,
            'desde': desde.strftime('%Y-%m-%d'),
            'hasta': hasta.strftime('%Y-%m-%d'),
        },
        'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
        'tienda_filtro': tienda,
        'anios': list(range(2024, timezone.localtime().year + 2)),
    }
    # Mismo patron que `dashboard`: si la request es HTMX, devolvemos
    # solo el partial del contenido dinamico (~5 KB vs ~28 KB del shell).
    if getattr(request, 'htmx', False):
        return render(request, 'reportes/_eerr_content.html', context)
    return render(request, 'reportes/eerr.html', context)


@login_required
@admin_required
def balance(request):
    """Balance General: snapshot patrimonial (activos / pasivos / patrimonio)."""
    from datetime import datetime
    from django.utils import timezone

    fecha_str = (request.GET.get('fecha') or '').strip()
    try:
        fecha = timezone.make_aware(
            datetime.strptime(fecha_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        ) if fecha_str else timezone.localtime()
    except ValueError:
        fecha = timezone.localtime()

    tienda_id = request.GET.get('tienda') or None
    tienda = Tienda.objects.filter(pk=tienda_id).first() if tienda_id else None

    bal = balance_general(fecha=fecha, tienda=tienda)

    return render(request, 'reportes/balance.html', {
        'balance': bal,
        'fecha_str': fecha.strftime('%Y-%m-%d'),
        'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
        'tienda_filtro': tienda,
    })
