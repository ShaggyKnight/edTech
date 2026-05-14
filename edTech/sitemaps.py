"""Sitemaps XML para SEO — Sprint 3 · 3.2.

Expone:
- Landing (`/`)
- Catalogo (`/tienda/`)
- Cada categoria (`/tienda/?cat=uniformes`, etc.)
- Cada producto activo con stock (`/tienda/p/<pk>/`)

Google y Bing indexan estas URLs automaticamente al ver el
`Sitemap:` directive en `robots.txt`. Es la base del SEO local de
Ideas Boutique: que "uniforme san francisco javier los vilos" llegue
al PDP correcto sin necesidad de pagar SEM.

Nota sobre `protocol`: en produccion el `request.scheme` siempre debe
ser `https` (Django respeta `SECURE_PROXY_SSL_HEADER` que ya esta
configurado). En dev sale `http`, lo cual esta bien para testing
local.
"""

from django.contrib.sitemaps import Sitemap
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse


class LandingSitemap(Sitemap):
    """La landing es la pagina mas importante: cambia raro pero pesa mucho."""
    priority = 1.0
    changefreq = 'monthly'

    def items(self):
        return ['index']

    def location(self, item):
        return reverse(item)


class CategoriasSitemap(Sitemap):
    """Las 4 categorias publicas del catalogo."""
    priority = 0.9
    changefreq = 'weekly'

    def items(self):
        # Importacion diferida para evitar AppRegistryNotReady en arranque.
        from ecommerce.views import CAT_SLUGS
        return list(CAT_SLUGS.keys())

    def location(self, slug):
        return f"{reverse('ecommerce:catalogo')}?cat={slug}"


class ProductosSitemap(Sitemap):
    """Productos activos con stock visible — cada uno es una pieza de SEO."""
    priority = 0.7
    changefreq = 'weekly'

    def items(self):
        # Importacion diferida: el modulo se carga antes que las apps.
        from bodega.models import StockTienda
        from catalogo.models import Producto
        from ecommerce.services import TiendaOnlineNoConfigurada, get_tienda_online
        try:
            tienda = get_tienda_online()
        except TiendaOnlineNoConfigurada:
            return Producto.objects.none()

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
                hay_v=Exists(stock_variante),
                hay_p=Exists(stock_directo),
            )
            .filter(Q(hay_v=True) | Q(hay_p=True))
            .order_by('-modificado')
        )

    def lastmod(self, producto):
        return producto.modificado

    def location(self, producto):
        return reverse('ecommerce:producto', args=[producto.pk])


SITEMAPS = {
    'landing': LandingSitemap,
    'categorias': CategoriasSitemap,
    'productos': ProductosSitemap,
}
