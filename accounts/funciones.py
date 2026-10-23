"""Funciones del backoffice que se pueden apagar.

Cada funcion es un campo booleano de `ConfiguracionSistema` y la lista de
vistas ('namespace:nombre') que dependen de ella. Para sumar una nueva:
agregar el campo al modelo (con su migracion) y una entrada aqui.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Funcion:
    clave: str          # campo en ConfiguracionSistema
    nombre: str
    descripcion: str
    rutas: tuple        # vistas que se bloquean cuando esta apagada


FUNCIONES = (
    Funcion(
        'produccion', 'Producción',
        'Reporte de producción del taller: lotes de confección, su costo y '
        'lo que se puede confeccionar con la tela en bodega.',
        ('reportes:produccion',),
    ),
    Funcion(
        'etiquetas', 'Etiquetas',
        'Selección e impresión de etiquetas con código de barras.',
        ('bodega:etiquetas_seleccionar', 'bodega:etiquetas_imprimir'),
    ),
    Funcion(
        'materiales', 'Telas y materiales',
        'Telas del taller, sus rendimientos por prenda y los rollos en bodega.',
        ('bodega:lista_materiales', 'bodega:materiales_bulk_action',
         'bodega:material_nuevo', 'bodega:material_editar',
         'bodega:rendimientos', 'bodega:rendimiento_nuevo',
         'bodega:rendimiento_editar', 'bodega:rendimiento_borrar'),
    ),
)

_POR_RUTA = {ruta: f for f in FUNCIONES for ruta in f.rutas}


def estado_funciones() -> dict:
    """{clave: encendida} segun la configuracion guardada."""
    from .models import ConfiguracionSistema
    conf = ConfiguracionSistema.actual()
    return {f.clave: getattr(conf, f.clave) for f in FUNCIONES}


def funcion_de_ruta(ruta: str) -> Funcion | None:
    """La funcion a la que pertenece la vista 'namespace:nombre', o None."""
    return _POR_RUTA.get(ruta)
