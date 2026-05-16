"""Sinónimos / modismos de búsqueda del POS para colegios de Los Vilos.

Los Vilos tiene 4 colegios principales, cada uno con un apodo local. La
gente del pueblo (incluida la clientela del POS) usa estos nicknames
mucho más que el nombre oficial. Si el cajero busca "liceo" en el POS,
debería encontrar los productos del Liceo Nicolás Federico Lohse aunque
los productos no tengan la palabra "liceo" en el nombre — están
asignados al colegio cuyo `nombre_buscable` contiene "lohse".

Cada clave es el alias normalizado (lower + sin acentos, como devuelve
`edTech.search.normalize_text`). Cada valor es la lista de substrings
que el `nombre_buscable` del Colegio (o del Producto) debe contener
para matchear. Se hace OR con el alias original — si el cajero busca
"liceo" y un Producto se llama literalmente "Buzo Liceo", ese también
matchea.

Para AGREGAR un alias nuevo:
    ALIASES_COLEGIO['miapodo'] = ['palabra_canonica_del_colegio']

Si la lista de aliases crece mucho, mover a un modelo de Django (campo
M2M `Colegio.aliases`) y manejar desde admin.
"""
from __future__ import annotations

from edTech.search import normalize_text


# Modismos -> términos canónicos.
# Las claves YA están normalizadas. Los valores también.
ALIASES_COLEGIO: dict[str, list[str]] = {
    # Liceo Nicolás Federico Lohse
    'liceo':      ['lohse'],
    'lice':       ['lohse'],         # tipo apurado, "lice"
    'nicolas':    ['lohse'],
    # San Francisco Javier (SFJ) — "fraga" es el apodo del barrio
    'fraga':      ['javier', 'sfj'],
    'sfj':        ['javier'],
    'francisco':  ['javier'],
    # Divina Providencia — "parro/parroquial" por ser el colegio
    # parroquial del pueblo
    'parro':      ['providencia'],
    'parroquial': ['providencia'],
    'divina':     ['providencia'],
    # Diego de Almagro — la "pública" (escuela pública)
    'publica':    ['almagro', 'diego'],
    'escuela':    ['almagro'],
    'diego':      ['almagro'],
}


def expandir_token(token: str) -> list[str]:
    """Si `token` es un alias conocido, devuelve [token] + términos
    canónicos. Si no, devuelve [token] tal cual.

    El token ya debe venir normalizado (lower + sin acentos). El caller
    es responsable de normalizar antes.

    Ejemplo:
        >>> expandir_token('liceo')
        ['liceo', 'lohse']
        >>> expandir_token('polera')
        ['polera']
    """
    expansiones = ALIASES_COLEGIO.get(token)
    if not expansiones:
        return [token]
    # Mantenemos el token original Y los términos canónicos. Si un
    # producto se llama literalmente "Buzo Liceo" el original matchea;
    # si solo está asignado al colegio "Lohse" via FK, matchean los
    # expandidos.
    return [token] + list(expansiones)


def normalizar_y_expandir(query: str) -> list[list[str]]:
    """Pipeline completa: normaliza, tokeniza y expande cada token.

    Devuelve una lista por token, donde cada sublista contiene las
    variantes a OR-buscar. El caller arma el `Q(...)` cruzado.

    Ejemplo:
        >>> normalizar_y_expandir('liceo Polera')
        [['liceo', 'lohse'], ['polera']]
    """
    q_norm = normalize_text(query)
    tokens = [t for t in q_norm.split() if t]
    return [expandir_token(t) for t in tokens]


# Tokens que SOLO deben matchear EXACTO contra `ValorAtributo.valor`
# (no contra nombre/sku/descripcion). Usarlos con `__contains` daría
# falsos positivos masivos:
#   "s"   matchea "gris", "san", "buscable"
#   "m"   matchea "moda", "almagro", "termo"
#   "l"   matchea "lohse", "almagro", "polera"
#   "edt" matchea... bueno, casi nada — pero acortar a iexact es claro
#
# Cubre tallas-letra (uniformes/ropa) y concentraciones de perfume.
EXACT_MATCH_TOKENS = frozenset({
    # Tallas-letra
    'xs', 's', 'm', 'l', 'xl', 'xxl', 'xxxl',
    # Concentraciones de perfume
    'edt', 'edp', 'elixir', 'cologne', 'parfum',
})

# Alias retrocompat — los tests viejos referenciaban TALLAS_LETRA.
TALLAS_LETRA = EXACT_MATCH_TOKENS


def es_talla_letra(token: str) -> bool:
    """True si `token` está en `EXACT_MATCH_TOKENS` (cubre tallas-letra
    y concentraciones de perfume). Mantengo el nombre por
    retrocompatibilidad con tests antiguos.
    """
    return token.lower() in EXACT_MATCH_TOKENS


def es_token_numerico_corto(token: str) -> bool:
    """True si el token son sólo dígitos de 1-4 caracteres.

    Cubre:
    - Tallas numéricas de uniformes: 4, 6, 8, 10, 12, 14, 16, 18
    - Volúmenes de perfume sin unidad: 5, 25, 30, 50, 75, ..., 250

    El caller debe combinarlo con un match `valor__iexact` + `valor__istartswith=f'{token} '`
    para diferenciar `"30"` de `"30 ml"` y de `"130 ml"`.
    """
    return token.isdigit() and 1 <= len(token) <= 4


def es_token_corto(token: str) -> bool:
    """True si el token va al PATH de match exacto contra valor.

    Engloba ambas categorías:
      - Letras / códigos cortos (S, M, XL, EDT, EDP, ...)
      - Numéricos puros de 1-4 dígitos (tallas y volúmenes)
    """
    return es_talla_letra(token) or es_token_numerico_corto(token)


def q_valor_exacto(term: str):
    """Construye un Django Q para match exacto contra ValorAtributo.valor
    desde un ProductoVariante.

    Reglas:
    - Letra/código (S, EDT, ...): `valor__iexact=term`. Único path.
    - Numérico puro (12, 30, 100): `iexact` matchea valor exacto ("12")
      Y `istartswith=f"{term} "` matchea valor con unidad ("30 ml") sin
      confundirse con "130 ml" o "300 ml".

    Devuelve un `Q` que el caller compone con `|=` o `&=`.
    """
    from django.db.models import Q
    base = Q(valores__valor__iexact=term)
    if term.isdigit():
        base |= Q(valores__valor__istartswith=f'{term} ')
    return base
