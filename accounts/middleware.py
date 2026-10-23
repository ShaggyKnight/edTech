"""Bloquea las pantallas de una funcion apagada (ver accounts/funciones.py)."""
from django.shortcuts import render

from .funciones import estado_funciones, funcion_de_ruta


class FuncionesMiddleware:
    """Si la vista pertenece a una funcion que un superusuario apago en
    Administracion > Funciones, responde una pagina "funcion apagada"
    (404) en vez de la pantalla. Quien no inicio sesion sigue el flujo
    normal de la vista (redireccion al login)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = getattr(request, 'resolver_match', None)
        if not match or not match.namespace:
            return None
        funcion = funcion_de_ruta(f'{match.namespace}:{match.url_name}')
        if funcion is None or not request.user.is_authenticated:
            return None
        if estado_funciones().get(funcion.clave, True):
            return None
        return render(request, 'accounts/funcion_apagada.html', {'funcion': funcion}, status=404)
