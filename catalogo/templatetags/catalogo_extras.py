"""Template helpers para imágenes de producto.

`imagen_producto`: si el producto tiene imagen subida, devuelve su URL;
si no, devuelve un SVG estándar según la familia (Buzo, Polera, Falda,
Chaleco, Perfume, o un genérico). Esto evita que el catálogo se vea con
puro placeholder a rayas cuando todavía no se cargaron fotos reales.
"""
from django import template
from django.templatetags.static import static

register = template.Library()


# Mapping familia → archivo SVG. Match por palabras clave en el nombre
# de la familia, case-insensitive y accent-insensitive.
_MAPPING = [
    ('buzo',         'img/productos/buzo.svg'),
    ('polera',       'img/productos/polera.svg'),
    ('falda',        'img/productos/falda.svg'),
    ('chaleco',      'img/productos/chaleco.svg'),
    ('perfume',      'img/productos/perfume.svg'),
    ('fragan',       'img/productos/perfume.svg'),
    ('uniform',      'img/productos/polera.svg'),
]
_GENERICO = 'img/productos/generico.svg'


def _svg_para_familia(nombre_familia: str, nombre_producto: str = '') -> str:
    """Resuelve el archivo SVG por palabra clave en familia o nombre."""
    from edTech.search import normalize_text
    key = normalize_text(f'{nombre_familia} {nombre_producto}')
    for word, path in _MAPPING:
        if word in key:
            return path
    return _GENERICO


@register.simple_tag
def imagen_producto(producto):
    """URL de la imagen del producto. Si no tiene, devuelve el SVG default."""
    if producto and getattr(producto, 'imagen', None):
        try:
            return producto.imagen.url
        except (ValueError, AttributeError):
            pass
    nombre_fam = ''
    if producto and producto.familia_id:
        nombre_fam = producto.familia.nombre
    nombre_prod = producto.nombre if producto else ''
    return static(_svg_para_familia(nombre_fam, nombre_prod))
