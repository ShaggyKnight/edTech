"""Middlewares globales del proyecto."""


class HtmxMiddleware:
    """Marca `request.htmx = True` cuando el request viene de HTMX.

    HTMX manda el header `HX-Request: true` con cada AJAX. Tener un
    booleano en `request` permite que las views y los templates
    decidan si devuelven HTML completo o un fragment para swap.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.htmx = request.headers.get('HX-Request') == 'true'
        return self.get_response(request)
