"""Lint: detecta `{# ... #}` multi-linea en templates Django.

`{# %#}` solo es comentario en UNA SOLA LINEA. Si el `#}` esta en
otra linea distinta del `{#`, todo el texto entre medio FILTRA al
HTML renderizado y aparece visible al usuario. Hay que usar
`{% comment %} ... {% endcomment %}` para multi-linea.

Este check ha encontrado el mismo bug 3 veces en el mismo proyecto —
ya es habito agregarlo al pre-commit / CI.

Uso:
    python scripts/check_django_comments.py

Exit code:
    0 — OK, ningun comentario multi-linea problemático
    1 — Hay al menos uno; los lista en stdout
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Excluimos venvs y dirs externos que no son nuestros.
EXCLUDE_DIRS = {'.git', '.venv', 'venv', 'env', 'node_modules', 'staticfiles', '.claude'}

# `{# ... #}` que no se cierre en la misma linea.
RE_OPEN_NO_CLOSE = re.compile(r'\{#(?:(?!#\}).)*$')


def buscar_problemas() -> list[tuple[Path, int, str]]:
    """Devuelve lista de (archivo, linea, snippet) para cada multi-linea."""
    hallazgos: list[tuple[Path, int, str]] = []
    for html in ROOT.rglob('*.html'):
        # Saltar dirs excluidos.
        if any(part in EXCLUDE_DIRS for part in html.parts):
            continue
        try:
            lineas = html.read_text(encoding='utf-8').splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, linea in enumerate(lineas, start=1):
            if RE_OPEN_NO_CLOSE.search(linea):
                hallazgos.append((html.relative_to(ROOT), i, linea.strip()))
    return hallazgos


def main() -> int:
    problemas = buscar_problemas()
    if not problemas:
        print('OK — sin {# %#} multi-linea.')
        return 0
    print(f'ERROR — {len(problemas)} comentario(s) `{{# %#}}` multi-linea encontrados:')
    print('Django no los trata como comentario y el texto FILTRA al HTML.')
    print('Convertir a `{% comment %} ... {% endcomment %}`.\n')
    for archivo, nro, snippet in problemas:
        print(f'  {archivo}:{nro}: {snippet[:80]}...')
    return 1


if __name__ == '__main__':
    sys.exit(main())
