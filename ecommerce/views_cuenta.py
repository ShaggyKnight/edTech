"""Vistas de cuenta para clientes de la tienda online.

Corre sobre `/tienda/cuenta/` y usa el shell boutique (`base_public.html`).
Los usuarios staff (admin/cajero/bodeguero) siguen usando `/cuenta/login/`
con el shell Bootstrap 3 — son flujos separados aunque ambos escriben
contra `auth_user`.
"""
from __future__ import annotations

from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET

from pos.models import ReciboVenta

from .cart import Cart
from .forms import RegistroClienteForm


class BoutiqueLoginView(LoginView):
    """Login del cliente en el look boutique.

    Override explícito de `get_success_url` para ignorar `LOGIN_REDIRECT_URL`
    del settings (que apunta al dashboard de staff) y mandar al cliente a sus
    pedidos. En Django 3.2 `LoginView` no honra `next_page` — solo `?next=` o
    `LOGIN_REDIRECT_URL` — así que la sobrescritura debe ser explícita.
    """
    template_name = 'ecommerce/cuenta/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or str(reverse_lazy('ecommerce:mis_pedidos'))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['items_count'] = Cart(self.request.session).items_count
        return ctx


class BoutiqueLogoutView(LogoutView):
    next_page = reverse_lazy('ecommerce:catalogo')


def registro(request):
    """Registro de cliente en la tienda. Ingresa automáticamente tras registrar."""
    if request.user.is_authenticated:
        return redirect('ecommerce:mis_pedidos')

    if request.method == 'POST':
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('ecommerce:mis_pedidos')
    else:
        form = RegistroClienteForm()

    return render(request, 'ecommerce/cuenta/registro.html', {
        'form': form,
        'items_count': Cart(request.session).items_count,
    })


@login_required(login_url='ecommerce:login')
@require_GET
def mis_pedidos(request):
    """Lista los pedidos online del cliente autenticado.

    Dos fuentes:
      1. Recibos con `cliente_usuario = request.user` (creados post-registro).
      2. Recibos sin `cliente_usuario` pero con `cliente_email = request.user.email`
         (creados como invitado antes del registro).
    """
    recibos = (
        ReciboVenta.objects
        .filter(canal=ReciboVenta.CANAL_ONLINE)
        .filter(
            Q(cliente_usuario=request.user)
            | Q(cliente_usuario__isnull=True, cliente_email__iexact=request.user.email)
        )
        .order_by('-creado')
        .prefetch_related('detalles')
    )

    return render(request, 'ecommerce/cuenta/mis_pedidos.html', {
        'recibos': recibos,
        'items_count': Cart(request.session).items_count,
    })
