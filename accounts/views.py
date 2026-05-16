from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse

from .roles import ADMIN, BODEGUERO, CAJERO, user_in_role


@login_required
def dashboard(request):
    """Redirige al usuario a la pantalla principal según su rol.

    BUG-011: antes los usuarios sin rol staff veían un 403 "sin rol".
    Para los clientes de la tienda online el "dashboard" debe ser la
    lista de sus pedidos. La regla queda: si el usuario tiene rol staff
    (admin / cajero / bodeguero) entra al backoffice; cualquier otro
    usuario autenticado (cliente normal) cae en `/tienda/cuenta/pedidos/`.
    """
    user = request.user

    if user.is_superuser or user_in_role(user, ADMIN):
        return redirect(reverse('reportes:dashboard'))
    if user_in_role(user, CAJERO):
        return redirect(reverse('pos:home'))
    if user_in_role(user, BODEGUERO):
        return redirect(reverse('bodega:stock'))

    # Cliente normal (sin rol staff) → su área de pedidos en la tienda.
    return redirect(reverse('ecommerce:mis_pedidos'))
