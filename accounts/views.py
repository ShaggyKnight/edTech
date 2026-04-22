from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from .roles import ADMIN, BODEGUERO, CAJERO, user_in_role


@login_required
def dashboard(request):
    """Redirige al usuario a la pantalla principal según su rol."""
    user = request.user

    if user.is_superuser or user_in_role(user, ADMIN):
        return redirect(reverse('admin:index'))
    if user_in_role(user, CAJERO):
        return redirect(reverse('pos:home'))
    if user_in_role(user, BODEGUERO):
        return redirect(reverse('bodega:stock'))

    return render(request, 'accounts/sin_rol.html', status=403)
