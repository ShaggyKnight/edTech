"""Vistas del app catalogo.

Por ahora solo el endpoint AJAX que el admin Django y el backoffice de
bodega usan para el boton "Generar SKU" en el form de variante.
La parte publica del catalogo (catalogo, PDP, etc.) vive en `ecommerce`.
"""

import json

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from catalogo.models import Producto, ValorAtributo
from catalogo.sku import generar_sku_unico


def _puede_generar_sku(user) -> bool:
    """Mismo criterio que el backoffice de bodega: admin, bodeguero o
    superuser. Cajeros no — ellos no crean variantes."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=['admin', 'bodeguero']).exists()


@require_POST
@login_required
@user_passes_test(_puede_generar_sku, login_url='login')
def admin_sugerir_sku(request):
    """Construye un SKU desde producto + valores de atributo seleccionados.

    POST JSON:
        {"producto_id": 42, "valor_ids": [1, 2, 3], "excluir_pk": 99}
    Respuesta:
        {"sku": "LATTAFA-YARA-100ML-EDP"}
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalido'}, status=400)

    producto_id = data.get('producto_id')
    valor_ids = data.get('valor_ids') or []
    excluir_pk = data.get('excluir_pk')

    if not producto_id:
        return JsonResponse({'error': 'Falta producto_id'}, status=400)

    try:
        producto = Producto.objects.get(pk=producto_id)
    except Producto.DoesNotExist:
        return JsonResponse({'error': 'Producto no existe'}, status=404)

    valores = list(
        ValorAtributo.objects
        .filter(pk__in=valor_ids)
        .order_by('atributo__nombre', 'orden', 'valor')
        .values_list('valor', flat=True)
    )

    sku = generar_sku_unico(
        marca=producto.marca or '',
        nombre=producto.nombre,
        valores=valores,
        excluir_pk=int(excluir_pk) if excluir_pk else None,
    )
    return JsonResponse({'sku': sku})
