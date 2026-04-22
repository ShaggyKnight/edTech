"""Definición central de roles y sus permisos.

Los roles se modelan como `auth.Group`. Este módulo es la fuente única de verdad
sobre qué permisos tiene cada rol — la data migration los aplica al poblar la db.
"""

ADMIN = 'admin'
CAJERO = 'cajero'
BODEGUERO = 'bodeguero'

ALL_ROLES = (ADMIN, CAJERO, BODEGUERO)


ROLE_PERMISSIONS = {
    CAJERO: {
        'bodega': {
            'producto': ['view'],
            'familia': ['view'],
        },
        'tienda': {
            'tienda': ['view'],
            'stocktienda': ['view'],
            'reciboventa': ['add', 'change', 'view'],
            'reciboventadetalle': ['add', 'change', 'view'],
            'historiaventas': ['add', 'view'],
        },
    },
    BODEGUERO: {
        'bodega': {
            'producto': ['add', 'change', 'view'],
            'familia': ['add', 'change', 'view'],
            'grupo': ['add', 'change', 'view'],
            'atributo': ['add', 'change', 'view'],
            'productoatributo': ['add', 'change', 'delete', 'view'],
            'productoatributovalor': ['add', 'change', 'delete', 'view'],
            'material': ['add', 'change', 'view'],
            'bodega': ['view'],
            'inventario': ['add', 'change', 'view'],
            'inventariolinea': ['add', 'change', 'delete', 'view'],
            'proveedor': ['add', 'change', 'view'],
        },
        'tienda': {
            'stocktienda': ['add', 'change', 'view'],
        },
    },
    # admin recibe todos los permisos dinámicamente en la migración
}


def user_in_role(user, role):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=role).exists()
