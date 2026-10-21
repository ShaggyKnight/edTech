"""Categorias publicas de la tienda y cuales estan a la venta.

Una categoria aparece en el menu, la landing, el pie y el sitemap solo
si tiene al menos un producto activo con stock en la tienda online.
Asi, cuando llega mercaderia de Moda o Ropa Intima, la categoria se
muestra sola; cuando se agota, desaparece sin tocar templates.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

from bodega.models import StockTienda
from catalogo.models import Familia, Producto


# Slug -> datos para el header, la descripcion y los tintes de acento.
# Permite que la landing enlace a `/tienda/?cat=uniformes` sin conocer la pk
# de la familia correspondiente. `nav` es el nombre corto del menu.
CAT_SLUGS = {
    'uniformes': {
        'title': 'Uniformes Escolares',
        'nav':   'Uniformes',
        'desc':  'Buzos, chalecos y remeras de tu colegio',
        'accent': '#7A1E2B',
        'match':  ['uniform'],
    },
    'perfumes': {
        'title': 'Perfumes',
        'nav':   'Perfumes',
        'desc':  'Fragancias originales y decants',
        'accent': '#C9A96E',
        # 'fragan' (no 'fragranc') matchea 'Fragancia(s)' en español.
        'match':  ['perfum', 'fragan'],
    },
    'moda': {
        'title': 'Moda',
        'nav':   'Moda',
        'desc':  'Ropa casual y formal',
        'accent': '#2B3140',
        'match':  ['moda', 'ropa'],
    },
    'intima': {
        'title': 'Ropa Íntima',
        'nav':   'Íntima',
        'desc':  'Lencería y ropa interior',
        'accent': '#A03853',
        'match':  ['intim', 'lenc'],
    },
}


def familias_por_slug(slug: str):
    """Queryset de familias que corresponden al slug de categoria."""
    info = CAT_SLUGS.get(slug)
    if not info:
        return Familia.objects.none()
    q = Familia.objects.none()
    for term in info['match']:
        q = q | Familia.objects.filter(nombre__icontains=term)
    return q


def productos_con_stock_online(tienda):
    """Productos activos con stock > 0 en la tienda online (por variante
    o directo). Mismo criterio que el catalogo y el sitemap."""
    stock_variante = StockTienda.objects.filter(
        tienda=tienda, variante__producto=OuterRef('pk'), cantidad__gt=0,
    )
    stock_directo = StockTienda.objects.filter(
        tienda=tienda, producto=OuterRef('pk'), cantidad__gt=0,
    )
    return (
        Producto.objects
        .filter(activo=True)
        .annotate(
            hay_stock_variante=Exists(stock_variante),
            hay_stock_directo=Exists(stock_directo),
        )
        .filter(Q(hay_stock_variante=True) | Q(hay_stock_directo=True))
    )


def slugs_con_stock(tienda=None) -> list[str]:
    """Slugs de las categorias con al menos un producto a la venta online,
    en el orden de CAT_SLUGS. Sin tienda online configurada: ninguna."""
    from ecommerce.services import TiendaOnlineNoConfigurada, get_tienda_online
    if tienda is None:
        try:
            tienda = get_tienda_online()
        except TiendaOnlineNoConfigurada:
            return []
    # Una sola query: los nombres de familia con stock. El match por
    # terminos se hace en Python (pocas familias, terminos ASCII).
    nombres = [
        (n or '').lower()
        for n in productos_con_stock_online(tienda)
        .values_list('familia__nombre', flat=True).distinct()
    ]
    return [
        slug for slug, info in CAT_SLUGS.items()
        if any(term in nombre for nombre in nombres for term in info['match'])
    ]


def categorias_visibles(tienda=None) -> list[dict]:
    """Categorias a mostrar en menus, landing y pie (ver slugs_con_stock)."""
    return [
        {'slug': slug, **{k: v for k, v in CAT_SLUGS[slug].items() if k != 'match'}}
        for slug in slugs_con_stock(tienda)
    ]
