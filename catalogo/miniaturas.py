"""Miniaturas WebP de las fotos de producto para las tarjetas del catalogo.

La tarjeta mide ~170 px en un celular y ~300 px en escritorio, pero se
descargaba la foto original (hasta ~430 KB en PNG). Por cada foto se
generan versiones WebP de 400 y 800 px de ancho en `media/productos/mini/`
y la tarjeta las ofrece con `srcset`; el navegador elige la que necesita.
Si una miniatura no existe (foto recien subida en un entorno sin Pillow,
por ejemplo), la tarjeta usa la original como siempre.

Se generan al guardar el producto (post_save, ver catalogo/models.py) y con
`manage.py generar_miniaturas`, que deploy.sh corre en cada despliegue.
"""

from __future__ import annotations

import io
import logging
import os

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

log = logging.getLogger(__name__)

ANCHOS = (400, 800)
CARPETA = 'productos/mini'
CALIDAD_WEBP = 80


def nombre_miniatura(nombre_original: str, ancho: int) -> str:
    """'productos/19-silk.png' -> 'productos/mini/19-silk-400.webp'."""
    base = os.path.splitext(os.path.basename(nombre_original))[0]
    return f'{CARPETA}/{base}-{ancho}.webp'


def generar(image_field, forzar: bool = False) -> list[str]:
    """Crea las miniaturas que falten de un ImageField. Devuelve las creadas."""
    if not image_field or not image_field.name:
        return []
    pendientes = [
        a for a in ANCHOS
        if forzar or not default_storage.exists(nombre_miniatura(image_field.name, a))
    ]
    if not pendientes:
        return []
    from PIL import Image

    creadas = []
    with default_storage.open(image_field.name, 'rb') as f:
        with Image.open(f) as original:
            original.load()
            im = original.convert('RGBA' if 'A' in original.getbands() else 'RGB')
    for ancho in pendientes:
        copia = im.copy()
        if copia.width > ancho:
            alto = round(copia.height * ancho / copia.width)
            copia = copia.resize((ancho, alto), Image.LANCZOS)
        buffer = io.BytesIO()
        copia.save(buffer, 'WEBP', quality=CALIDAD_WEBP, method=6)
        destino = nombre_miniatura(image_field.name, ancho)
        if default_storage.exists(destino):
            default_storage.delete(destino)
        default_storage.save(destino, ContentFile(buffer.getvalue()))
        creadas.append(destino)
    return creadas


def srcset(image_field) -> str:
    """'url-400 400w, url-800 800w' con las miniaturas que existan, o ''."""
    if not image_field or not image_field.name:
        return ''
    partes = []
    for ancho in ANCHOS:
        nombre = nombre_miniatura(image_field.name, ancho)
        if default_storage.exists(nombre):
            partes.append(f'{default_storage.url(nombre)} {ancho}w')
    return ', '.join(partes)


def url(image_field, ancho: int = 400) -> str:
    """URL de una miniatura si existe, si no la de la foto original."""
    if image_field and image_field.name:
        nombre = nombre_miniatura(image_field.name, ancho)
        if default_storage.exists(nombre):
            return default_storage.url(nombre)
        return image_field.url
    return ''
