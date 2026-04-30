"""Helpers de búsqueda accent-insensitive y case-insensitive.

SQLite no tiene `unaccent` nativo, y `__icontains` solo es case-insensitive
para ASCII. Esta utilidad normaliza strings (minúsculas + sin acentos) para
compararlos en Python o para almacenar en un campo "buscable" precomputado.

Convenciones:
- `normalize_text(s)` devuelve el string normalizado.
- Los modelos que tengan campo `nombre` y quieran búsqueda accent-insensitive
  pueden agregar `nombre_buscable` y mantenerlo sincronizado en `save()` —
  ver `catalogo.Producto`, `bodega.Material`, `catalogo.Colegio`.
- Las views/queries usan `nombre_buscable__contains=normalize_text(q)` en
  lugar de `nombre__icontains=q`.

Ejemplo:
    >>> normalize_text('Perfumé Avéllá')
    'perfume avella'
"""
from __future__ import annotations

import unicodedata
from typing import Optional


def normalize_text(s: Optional[str]) -> str:
    """Lowercase + sin acentos + strip. Usar tanto al guardar como al buscar."""
    if not s:
        return ''
    # Descompone caracteres acentuados en base + diacrítico.
    nfkd = unicodedata.normalize('NFKD', str(s))
    # Quita los diacríticos (categoría Mn = Mark, nonspacing).
    sin_acentos = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower().strip()
