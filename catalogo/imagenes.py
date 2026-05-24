"""Optimizacion de imagenes subidas por el admin.

Las fotos de producto las suben directo desde celular o camara — sin
post-proceso suelen pesar 1.5 a 3 MB y medir 3000x4000 px. Eso hace
que:
  - La vista rapida (modal en tablet) se vea pixelada los primeros 2-3
    segundos mientras se descarga el PNG interlazado.
  - El catalogo en mobile/3G tarde 5-10s en pintar las cards.
  - El presupuesto de transferencia de la tienda explote sin razon
    (300 KB de UI + 5 MB por producto visible = mala primera vista).

Esta utilidad reduce las imagenes a dimensiones razonables para web:
  - Lado mas largo: max 1400 px (PDP llena el viewport mobile; mas
    no se nota en ninguna pantalla del sitio).
  - JPEG quality 85 (no se distingue del 100 a ojo).
  - PNG con transparencia se mantiene como PNG; sin transparencia se
    convierte a JPEG (mucho mas chico).

Se llama desde:
  - `Producto.save()` y `ProductoImagen.save()` — auto al subir
  - `manage.py optimizar_imagenes` — backfill de las existentes
"""

from __future__ import annotations

import io
import os
from typing import Tuple

from django.core.files.base import ContentFile

# Umbral: solo procesamos si la imagen excede alguno de estos. Asi la
# re-ejecucion del comando sobre fotos ya procesadas no las re-encoda.
MAX_LADO_PX = 1400
MAX_BYTES = 500_000  # 500 KB

# Calidad JPEG. 85 es el "sweet spot" web — visualmente indistinguible
# de 100 a ojo humano, pero ~3x mas chico.
JPEG_QUALITY = 85


def _ya_optimizada(image_field) -> bool:
    """True si la imagen ya cumple los umbrales — no hace falta tocarla."""
    try:
        from PIL import Image
    except ImportError:
        return True  # sin Pillow no podemos hacer nada

    try:
        image_field.open('rb')
        size_bytes = image_field.size
        with Image.open(image_field.file) as im:
            w, h = im.size
    except Exception:
        return True
    finally:
        try:
            image_field.close()
        except Exception:
            pass

    if size_bytes <= MAX_BYTES and max(w, h) <= MAX_LADO_PX:
        return True
    return False


def _redimensionar(im, max_lado: int):
    """Reduce `im` para que su lado mayor no exceda `max_lado`. Idempotente."""
    w, h = im.size
    lado_mayor = max(w, h)
    if lado_mayor <= max_lado:
        return im
    ratio = max_lado / float(lado_mayor)
    nuevo = (int(round(w * ratio)), int(round(h * ratio)))
    # LANCZOS es el resampler de mejor calidad disponible en Pillow para
    # downscaling — preserva bordes nitidos en logos y texto.
    from PIL import Image as _Image
    return im.resize(nuevo, _Image.LANCZOS)


def _tiene_alfa(im) -> bool:
    """True si la imagen tiene canal alpha REAL (no solo modo 'RGBA' con
    todos los pixels opacos). Importante: si no tiene transparencia real,
    convertirla a JPEG ahorra mucho espacio sin perder nada."""
    if im.mode in ('RGBA', 'LA'):
        try:
            alpha = im.getchannel('A')
            # Si el min del canal alpha es 255, es 100% opaca -> no hay alpha real.
            return alpha.getextrema()[0] < 255
        except Exception:
            return True
    if im.mode == 'P' and 'transparency' in im.info:
        return True
    return False


def optimizar_imagen_field(image_field) -> Tuple[bool, str]:
    """Re-encoda y re-dimensiona el contenido de un FieldFile in-place.

    Retorna (cambiada, mensaje). Si no hay cambio, cambiada=False y
    el mensaje describe por que (umbral OK, formato no soportado, etc.).

    NO toca el FieldFile si la imagen ya cumple los umbrales — asi
    podemos llamar a esta funcion en cada save() sin penalty.
    """
    try:
        from PIL import Image
    except ImportError:
        return False, 'Pillow no instalado'

    if not image_field:
        return False, 'sin imagen'

    if _ya_optimizada(image_field):
        return False, 'ya cumple umbrales'

    try:
        # Algunos backends (S3, uploads en memoria) requieren seek(0)
        # explicito antes de leer. open('rb') no siempre lo asegura.
        try:
            image_field.open('rb')
        except Exception:
            pass
        try:
            image_field.file.seek(0)
        except Exception:
            pass
        with Image.open(image_field.file) as im:
            im.load()
            original_format = (im.format or 'JPEG').upper()
            tiene_alfa = _tiene_alfa(im)
            im = _redimensionar(im, MAX_LADO_PX)

            buffer = io.BytesIO()
            nombre_original = os.path.basename(image_field.name)
            base, _ext = os.path.splitext(nombre_original)

            if tiene_alfa:
                # Mantener PNG para no perder transparencia.
                if im.mode not in ('RGBA', 'LA', 'P'):
                    im = im.convert('RGBA')
                im.save(buffer, format='PNG', optimize=True)
                nuevo_nombre = f'{base}.png'
            else:
                # Sin transparencia: JPEG es mucho mas chico que PNG.
                if im.mode != 'RGB':
                    im = im.convert('RGB')
                im.save(
                    buffer, format='JPEG',
                    quality=JPEG_QUALITY, optimize=True, progressive=True,
                )
                nuevo_nombre = f'{base}.jpg'

            buffer.seek(0)
            datos = buffer.getvalue()
    except Exception as e:
        return False, f'error procesando: {e}'
    finally:
        try:
            image_field.close()
        except Exception:
            pass

    # `save(save=False)` no llama a model.save() — solo reemplaza el
    # archivo del FieldFile. Quien llamo es responsable de hacer
    # instance.save(update_fields=['imagen']) si quiere persistir.
    nombre_disco_anterior = image_field.name  # ej: 'productos/foo.png'
    image_field.save(nuevo_nombre, ContentFile(datos), save=False)
    # Django NO borra el archivo viejo automaticamente al reemplazar.
    # Si la extension cambio (png -> jpg) o el storage le puso un sufijo
    # para evitar conflicto, el original queda huerfano consumiendo
    # disco. Lo limpiamos explicitamente cuando el path cambio.
    if nombre_disco_anterior and nombre_disco_anterior != image_field.name:
        try:
            image_field.storage.delete(nombre_disco_anterior)
        except Exception:
            pass  # archivo ya no existe / sin permisos / etc — no es fatal
    return True, f'{nombre_original} -> {nuevo_nombre} ({len(datos)//1024} KB)'
