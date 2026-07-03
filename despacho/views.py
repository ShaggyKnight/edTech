"""Vistas del despacho de pedidos online.

Accesible para users con rol DESPACHADOR o ADMIN (Blanca ve todo igual).

Flujo de 2 estados: Nuevo (pagado, no despachado) -> Despachado.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.roles import ADMIN, DESPACHADOR, OPERADOR, user_in_role
from pos.models import ReciboVenta


def _puede_despachar(user):
    """ADMIN, DESPACHADOR y OPERADOR ven el panel. Superuser siempre."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return (
        user_in_role(user, ADMIN)
        or user_in_role(user, DESPACHADOR)
        or user_in_role(user, OPERADOR)
    )


@login_required
@user_passes_test(_puede_despachar, login_url='login')
def cola(request):
    """Lista de pedidos online por estado.

    Default: nuevos (pagados, no despachados todavia) primero.
    Filtro `?estado=despachados` muestra los ya cerrados (historico).
    """
    estado_filtro = request.GET.get('estado', 'nuevos')

    base_qs = (
        ReciboVenta.objects
        .filter(canal=ReciboVenta.CANAL_ONLINE,
                estado=ReciboVenta.ESTADO_PAGADO)
        .select_related('tienda', 'cliente_usuario')
        .prefetch_related('detalles__variante__producto',
                          'detalles__variante__valores')
    )

    if estado_filtro == 'despachados':
        pedidos = base_qs.filter(despachado_en__isnull=False).order_by('-despachado_en')[:100]
    else:
        pedidos = base_qs.filter(despachado_en__isnull=True).order_by('-creado')

    contadores = base_qs.aggregate(
        nuevos=Count('pk', filter=Q(despachado_en__isnull=True)),
        despachados=Count('pk', filter=Q(despachado_en__isnull=False)),
    )

    return render(request, 'despacho/cola.html', {
        'pedidos': pedidos,
        'estado_filtro': estado_filtro,
        'contadores': contadores,
    })


@login_required
@user_passes_test(_puede_despachar, login_url='login')
def detalle(request, pk):
    """Detalle de un pedido — vista para preparar/empacar."""
    pedido = get_object_or_404(
        ReciboVenta.objects
            .select_related('tienda', 'cliente_usuario', 'despachado_por')
            .prefetch_related('detalles__variante__producto',
                              'detalles__variante__valores__atributo'),
        pk=pk,
        canal=ReciboVenta.CANAL_ONLINE,
    )
    return render(request, 'despacho/detalle.html', {'pedido': pedido})


@login_required
@user_passes_test(_puede_despachar, login_url='login')
@require_POST
def marcar_despachado(request, pk):
    """Marca el pedido como despachado (timestamp + quien lo hizo)."""
    pedido = get_object_or_404(
        ReciboVenta, pk=pk,
        canal=ReciboVenta.CANAL_ONLINE,
    )
    if pedido.despachado_en is None:
        pedido.despachado_en = timezone.now()
        pedido.despachado_por = request.user
        pedido.save(update_fields=['despachado_en', 'despachado_por'])
        messages.success(
            request,
            f'Pedido #{pedido.pk} marcado como despachado.',
        )
    else:
        messages.info(
            request,
            f'Pedido #{pedido.pk} ya estaba despachado.',
        )
    return redirect('despacho:cola')


@login_required
@user_passes_test(_puede_despachar, login_url='login')
@require_POST
def desmarcar_despachado(request, pk):
    """Reabre un pedido (revierte el despachado). Para errores de
    operador — marcar y desmarcar quedan en el log de auditoria."""
    pedido = get_object_or_404(
        ReciboVenta, pk=pk,
        canal=ReciboVenta.CANAL_ONLINE,
    )
    if pedido.despachado_en is not None:
        pedido.despachado_en = None
        pedido.despachado_por = None
        pedido.save(update_fields=['despachado_en', 'despachado_por'])
        messages.success(
            request,
            f'Pedido #{pedido.pk} reabierto. Volvió a la cola de nuevos.',
        )
    return redirect('despacho:detalle', pk=pk)
