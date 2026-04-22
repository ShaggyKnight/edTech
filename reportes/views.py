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
from bodega.models import Tienda
from contabilidad.models import MovimientoCaja
from contabilidad.services import registrar_salida, resumen_caja

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
