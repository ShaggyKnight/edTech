"""Template tags para chequear roles en los templates del backoffice.

Uso:
    {% load roles_tags %}
    {% if user|has_role:'despachador' %} ... {% endif %}
    {% if user|has_any_role:'admin,despachador' %} ... {% endif %}

Los permisos de Django (`perms.app.action_model`) sirven para gatear
acciones concretas, pero a veces queremos mostrar/ocultar por ROL
(ej. el link "Despacho" lo ve el despachador y el admin, no el cajero
aunque tenga change_reciboventa). Para eso van estos filtros.
"""
from django import template

from accounts.roles import user_in_role

register = template.Library()


@register.filter
def has_role(user, role: str) -> bool:
    """True si el user tiene el rol dado (o es superuser)."""
    return user_in_role(user, role)


@register.filter
def has_any_role(user, roles_csv: str) -> bool:
    """True si el user tiene AL MENOS uno de los roles (CSV).

    Ej: {% if user|has_any_role:'admin,despachador' %}
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    roles = [r.strip() for r in roles_csv.split(',') if r.strip()]
    return any(user_in_role(user, r) for r in roles)
