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
    """Panel de indicadores del negocio."""
    try:
        dias = max(1, min(365, int(request.GET.get('dias', 30))))
    except (TypeError, ValueError):
        dias = 30

    desde, hasta = ventana_por_defecto(dias)
    tienda_id = request.GET.get('tienda') or None
    tienda = None
    if tienda_id:
        tienda = Tienda.objects.filter(pk=tienda_id).first()

    resumen = resumen_negocio(tienda=tienda, desde=desde, hasta=hasta)
    serie = ventas_por_periodo(tienda=tienda, desde=desde, hasta=hasta)

    context = {
        'resumen': resumen,
        'serie': serie,
        'dias': dias,
        'tiendas': Tienda.objects.filter(activa=True).order_by('nombre_organizacion'),
        'tienda_filtro': tienda,
    }
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
    Incluye chart de evolución últimos 12 meses.
    """
    from datetime import datetime, timedelta
    from django.utils import timezone

    desde, hasta, modo, anio, mes, label = _parse_periodo(request)

    tienda_id = request.GET.get('tienda') or None
    tienda = Tienda.objects.filter(pk=tienda_id).first() if tienda_id else None

    eerr_dato = estado_resultados(desde=desde, hasta=hasta, tienda=tienda)

    # Serie últimos 12 meses (incluye el período seleccionado).
    fin = timezone.localtime()
    inicio = fin.replace(day=1) - timedelta(days=1)
    inicio = inicio.replace(day=1)
    # Retroceder 11 meses más.
    for _ in range(11):
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    inicio = timezone.make_aware(datetime(inicio.year, inicio.month, 1))
    serie = serie_mensual(desde=inicio, hasta=fin, tienda=tienda)

    return render(request, 'reportes/eerr.html', {
        'eerr': eerr_dato,
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
    })


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
