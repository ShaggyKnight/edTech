"""Definición central de roles y sus permisos.

Los roles se modelan como `auth.Group`. Este módulo es la fuente única de verdad
sobre qué permisos tiene cada rol — la data migration los aplica al poblar la db.
"""

ADMIN = 'admin'
CAJERO = 'cajero'
BODEGUERO = 'bodeguero'
DESPACHADOR = 'despachador'
OPERADOR = 'operador'

ALL_ROLES = (ADMIN, CAJERO, BODEGUERO, DESPACHADOR, OPERADOR)


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
    # Despachador: SOLO la pantalla de despacho (/despacho/). Esa pantalla
    # esta gateada por ROL (user_passes_test), no por permisos de modelo,
    # asi que el despachador no necesita permisos de catalogo/bodega/pos
    # para trabajar. Deliberadamente NO se le dan view_stocktienda ni
    # view_reciboventa porque esos permisos harian aparecer las secciones
    # "Stock" y "Ventas" en el sidebar — y la dueña lo quiere puro despacho.
    # Ver los productos del pedido para empacar no requiere permiso (los
    # templates los muestran via ORM). Se deja change_reciboventa como
    # registro honesto de que marca pedidos como despachados.
    DESPACHADOR: {
        'pos': {
            'reciboventa': ['change'],   # marcar despachado (igual es role-gated)
        },
    },
    # Operador: la operación COMPLETA de la tienda en un solo rol
    # simplificado (pensado para la dueña): vender en el POS, despachar
    # pedidos online, manejar stock, productos y ofertas. Deliberadamente
    # SIN: materiales/telas, etiquetas, reportes financieros, admin
    # Django ni gestión de usuarios — menos pantallas, menos ruido.
    OPERADOR: {
        'catalogo': {
            'producto': ['add', 'change', 'view'],
            'productovariante': ['add', 'change', 'view'],
            'familia': ['view'],
            'colegio': ['view'],
            'atributo': ['view'],
            'valoratributo': ['add', 'change', 'view'],
            'oferta': ['add', 'change', 'view'],
        },
        'bodega': {
            'tienda': ['view'],
            'stocktienda': ['add', 'change', 'view'],
            'movimientostock': ['add', 'view'],
        },
        'pos': {
            'reciboventa': ['add', 'change', 'view'],
            'reciboventadetalle': ['add', 'change', 'view'],
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
