"""Definición central de roles y sus permisos.

Los roles se modelan como `auth.Group`. Este módulo es la fuente única de verdad
sobre qué permisos tiene cada rol — la data migration los aplica al poblar la db.
"""

ADMIN = 'admin'
CAJERO = 'cajero'
BODEGUERO = 'bodeguero'
DESPACHADOR = 'despachador'

ALL_ROLES = (ADMIN, CAJERO, BODEGUERO, DESPACHADOR)


ROLE_PERMISSIONS = {
    CAJERO: {
        'catalogo': {
            'producto': ['view'],
            'productovariante': ['view'],
            'familia': ['view'],
            'oferta': ['view'],
        },
        'bodega': {
            'tienda': ['view'],
            'stocktienda': ['view'],
        },
        'pos': {
            'reciboventa': ['add', 'change', 'view'],
            'reciboventadetalle': ['add', 'change', 'view'],
        },
    },
    BODEGUERO: {
        'catalogo': {
            'producto': ['add', 'change', 'view'],
            'productovariante': ['add', 'change', 'view'],
            'familia': ['add', 'change', 'view'],
            'colegio': ['view'],  # ver pero no editar; el dueño los gestiona
            'atributo': ['add', 'change', 'view'],
            'valoratributo': ['add', 'change', 'delete', 'view'],
            'oferta': ['add', 'change', 'view'],
        },
        'bodega': {
            'tienda': ['view'],
            'bodega': ['add', 'change', 'view'],
            'stocktienda': ['add', 'change', 'view'],
            'proveedor': ['add', 'change', 'view'],
            'material': ['add', 'change', 'view'],
            'inventario': ['add', 'change', 'view'],
            'inventariolinea': ['add', 'change', 'delete', 'view'],
            'movimientostock': ['add', 'view'],
        },
    },
    # Despachador prepara y despacha pedidos online. Ve solo lo necesario
    # para identificar productos a empacar (sin precios costo, sin proveedores)
    # y para marcar el pedido como despachado.
    DESPACHADOR: {
        'catalogo': {
            'producto': ['view'],
            'productovariante': ['view'],
        },
        'bodega': {
            'tienda': ['view'],
            'stocktienda': ['view'],
        },
        'pos': {
            'reciboventa': ['view', 'change'],   # change = marcar despachado
            'reciboventadetalle': ['view'],
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
