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
from django.urls import reverse


class LandingSitemap(Sitemap):
    """La landing es la pagina mas importante: cambia raro pero pesa mucho."""
    priority = 1.0
    changefreq = 'monthly'

    def items(self):
        return ['index', 'ecommerce:catalogo', 'info']

    def location(self, item):
        return reverse(item)


class LegalesSitemap(Sitemap):
    """Politica de privacidad y terminos: cambian poco, pero tienen que
    estar encontrables."""
    priority = 0.2
    changefreq = 'yearly'

    def items(self):
        return ['privacidad', 'terminos']

    def location(self, item):
        return reverse(item)


class CategoriasSitemap(Sitemap):
    """Categorias publicas del catalogo con algo a la venta online."""
    priority = 0.9
    changefreq = 'weekly'

    def items(self):
        # Importacion diferida para evitar AppRegistryNotReady en arranque.
        # Una categoria sin stock es una pagina vacia: no se publica.
        from ecommerce.categorias import slugs_con_stock
        return slugs_con_stock()

    def location(self, slug):
        return f"{reverse('ecommerce:catalogo')}?cat={slug}"


class ProductosSitemap(Sitemap):
    """Productos activos con stock visible — cada uno es una pieza de SEO."""
    priority = 0.7
    changefreq = 'weekly'

    def items(self):
        # Importacion diferida: el modulo se carga antes que las apps.
        from catalogo.models import Producto
        from ecommerce.categorias import productos_con_stock_online
        from ecommerce.services import TiendaOnlineNoConfigurada, get_tienda_online
        try:
            tienda = get_tienda_online()
        except TiendaOnlineNoConfigurada:
            return Producto.objects.none()
        return productos_con_stock_online(tienda).order_by('-modificado')

    def lastmod(self, producto):
        return producto.modificado

    def location(self, producto):
        return reverse('ecommerce:producto', args=[producto.pk])


SITEMAPS = {
    'landing': LandingSitemap,
    'categorias': CategoriasSitemap,
    'productos': ProductosSitemap,
    'legales': LegalesSitemap,
}
