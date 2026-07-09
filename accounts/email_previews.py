"""Registro de previews de emails transaccionales con mock data.

Cada entry permite renderear el template del email en el browser sin
disparar el flujo real (compra, registro, etc). Util para iterar diseño,
verificar copy y testear contra clientes (Gmail, Outlook, Apple Mail).

Visible en /cuenta/emails/ (solo staff).

NOTA: Si encontras que el template usa una variable distinta a la que
emails.py le pasa (ej. template usa `user.first_name` pero la funcion
manda `usuario`), eso es un bug — el preview lo destapa porque pasa
ambos. Documentar y fixear en emails.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Callable

from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────
# Helpers para construir objetos fake que se parecen a modelos Django
# ─────────────────────────────────────────────────────────────────────

class _FakeQS:
    """Imita un queryset/related manager con .all() iterable."""
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


def _user_fake():
    return SimpleNamespace(
        pk=42,
        username='maria.gonzalez',
        first_name='María',
        last_name='González',
        email='maria.gonzalez@gmail.com',
        is_active=True,
    )


def _variante_fake(producto_nombre='Polera Piqué SFJ', valores=('Talla', 'M')):
    """Variante con .producto.nombre, .valores.all() y __str__."""
    producto = SimpleNamespace(pk=42, nombre=producto_nombre)
    valores_obj = [SimpleNamespace(valor=v) for v in valores]
    var = SimpleNamespace(
        pk=101,
        producto=producto,
        valores=_FakeQS(valores_obj),
    )
    # Para `variante|stringformat:"s"` en el preheader
    var.__str__ = lambda: f'{producto_nombre} ' + ' · '.join(valores)
    return var


def _detalle(cantidad, nombre, subtotal):
    """Item de detalle de un recibo."""
    return SimpleNamespace(
        cantidad=cantidad,
        descripcion=nombre,
        precio_unitario=Decimal(subtotal) / cantidad,
        subtotal=Decimal(subtotal),
    )


def _recibo_fake(con_descuento=False, con_dte=True):
    """Recibo de venta online con todos los attrs que usan los templates."""
    detalles = [
        _detalle(1, 'Polera Piqué SFJ · Talla M', 14900),
        _detalle(2, 'Chaleco SFJ · Talla 10', 41800),
        _detalle(1, 'Buzo SFJ Completo · Talla M', 35900),
    ]
    subtotal = sum(d.subtotal for d in detalles)
    descuento = Decimal('5000') if con_descuento else Decimal('0')
    total = subtotal - descuento
    return SimpleNamespace(
        pk=10247,
        cliente_nombre='María González',
        cliente_email='maria.gonzalez@gmail.com',
        cliente_telefono='+56 9 5544 3322',
        cliente_direccion='Av. Caupolicán 1234, Dpto 5B\nLos Vilos · Región de Coquimbo',
        creado=timezone.now() - timedelta(minutes=14),
        total=total,
        descuento=descuento,
        payment_provider='KLAP',
        dte_url_pdf='https://www.haulmer.com/dte/sample.pdf' if con_dte else '',
        detalles=_FakeQS(detalles),
    )


def _carrito_data_fake():
    """Dict como lo construye services para carrito abandonado."""
    return {
        'nombre': 'María',
        'email': 'maria.gonzalez@gmail.com',
        'fecha': timezone.now() - timedelta(hours=26),
        'items': [
            SimpleNamespace(cantidad=1, nombre='Polera Piqué SFJ · Talla M', subtotal=Decimal('14900')),
            SimpleNamespace(cantidad=2, nombre='Chaleco SFJ · Talla 10', subtotal=Decimal('41800')),
        ],
        'total': Decimal('56700'),
        'hay_uniforme': True,
        'calc_url': 'https://ideasboutique.cl/info/#calculadora-tallas',
        'retomar_url': 'https://ideasboutique.cl/tienda/carrito/?token=abc123',
    }


def _familia_fake():
    """Cliente con hijos en el colegio. Recordatorio anual de febrero."""
    return {
        'cliente_nombre': 'Carolina',
        'cliente': SimpleNamespace(
            email='carolina@gmail.com',
            nombre='Carolina',
            apellido='Soto',
        ),
        'colegio': SimpleNamespace(nombre='San Francisco Javier', pk=1),
        'hijos': [
            SimpleNamespace(
                nombre='Tomás',
                colegio='San Francisco Javier',
                talla_buzo='10',
                talla_polera='10',
                talla_chaleco='10',
            ),
            SimpleNamespace(
                nombre='Antonia',
                colegio='San Francisco Javier',
                talla_buzo='8',
                talla_polera='8',
                talla_chaleco=None,
            ),
        ],
        'descuento_segundo_hijo': True,
        'familia_url': 'https://ideasboutique.cl/cuenta/familia/',
        'tienda_url': 'https://ideasboutique.cl/tienda/?colegio=1',
    }


# ─────────────────────────────────────────────────────────────────────
# Registry de previews — agregar acá si se suma un email nuevo
# ─────────────────────────────────────────────────────────────────────

@dataclass
class PreviewEntry:
    slug: str
    nombre: str            # Label humano
    descripcion: str       # Cuando se dispara este email
    template: str          # Path en templates/
    subject_template: str  # Subject como aparece en el inbox
    para_quien: str        # Destinatario tipico (cliente / dueña / etc)
    contexto_fn: Callable[[], dict]
    feature_flag: str = ''  # Setting que lo habilita en prod (vacio = siempre on)


def _ctx_boleta():
    recibo = _recibo_fake()
    return {
        'recibo': recibo,
        'recibo_url': f'https://ideasboutique.cl/tienda/pedido/{recibo.pk}/',
    }


def _ctx_aviso_dueno():
    recibo = _recibo_fake()
    return {
        'recibo': recibo,
        'admin_url': f'https://ideasboutique.cl/admin/pos/reciboventa/{recibo.pk}/change/',
    }


def _ctx_aviso_transferencia():
    recibo = _recibo_fake(con_dte=False)
    return {
        'recibo': recibo,
        'cola_url': 'https://ideasboutique.cl/despacho/?estado=transferencias',
    }


def _ctx_instrucciones_transferencia():
    recibo = _recibo_fake(con_dte=False)
    return {
        'recibo': recibo,
        'cuenta': {
            'nombre': 'Blanca Contreras',
            'rut': '7.152.915-0',
            'banco': 'BancoEstado',
            'tipo_cuenta': 'CuentaRUT',
            'cuenta': '7152915',
            'email': 'ventas@ideasboutique.cl',
        },
        'pedido_url': f'https://ideasboutique.cl/tienda/pedido/{recibo.pk}/',
    }


def _ctx_bienvenida():
    u = _user_fake()
    return {
        # La funcion pasa "usuario", el template usa "user" — pasamos ambos
        # para que el preview muestre el mail "como deberia" mientras el
        # bug se fixea.
        'usuario': u,
        'user': u,
        'site_url': 'https://ideasboutique.cl/tienda/',
        'tienda_url': 'https://ideasboutique.cl/tienda/',
    }


def _ctx_reset_password():
    u = _user_fake()
    return {
        'usuario': u,
        'user': u,
        'reset_url': 'https://ideasboutique.cl/cuenta/reset/Mg/abc123-token-largo-aleatorio/',
    }


def _ctx_stock_disponible():
    variante = _variante_fake(producto_nombre='Polera Piqué SFJ', valores=('M',))
    return {
        # La funcion pasa "producto" + "pdp_url", el template usa
        # "variante" + "producto_url". Bug en emails.py — pasamos ambos.
        'variante': variante,
        'producto': variante.producto,
        'producto_url': f'https://ideasboutique.cl/tienda/p/{variante.producto.pk}/',
        'pdp_url': f'https://ideasboutique.cl/tienda/p/{variante.producto.pk}/',
        'unsub_url': 'https://ideasboutique.cl/tienda/avisame/cancelar/xyz789/',
    }


def _ctx_carrito_abandonado():
    return _carrito_data_fake()


def _ctx_pedir_resena():
    recibo = _recibo_fake()
    # Template usa producto.nombre y cliente_nombre, funcion solo pasa recibo
    producto = SimpleNamespace(nombre='Polera Piqué SFJ · Talla M')
    return {
        'recibo': recibo,
        'producto': producto,
        'cliente_nombre': recibo.cliente_nombre,
        'resena_url': f'https://ideasboutique.cl/tienda/pedido/{recibo.pk}/resena/',
    }


def _ctx_recordatorio_familia():
    return _familia_fake()


PREVIEWS: list[PreviewEntry] = [
    PreviewEntry(
        slug='boleta',
        nombre='Boleta de compra',
        descripcion='Se envía al cliente apenas se confirma el pago de un pedido online. Lleva el detalle, total, y link a la boleta SII si DTE_EMISSOR está activo.',
        template='emails/boleta_compra.html',
        subject_template='Boleta #10247 · Ideas Boutique',
        para_quien='Cliente',
        contexto_fn=_ctx_boleta,
    ),
    PreviewEntry(
        slug='aviso-dueno',
        nombre='Aviso a Blanca · nueva venta',
        descripcion='Notificación interna a la dueña cuando entra un pedido online pagado. Va a los correos de `OWNER_NOTIFICATION_EMAIL` (acepta varios, separados por coma) + despachadores activos.',
        template='emails/aviso_dueno_orden.html',
        subject_template='Nueva venta online #10247 · $87.700',
        para_quien='Blanca (dueña)',
        contexto_fn=_ctx_aviso_dueno,
    ),
    PreviewEntry(
        slug='aviso-transferencia',
        nombre='Aviso interno · pedido esperando transferencia',
        descripcion='Cuando un cliente elige transferencia directa: avisa al dueño que hay un abono por vigilar en la cartola. Solo a `OWNER_NOTIFICATION_EMAIL` (los despachadores aún no tienen nada que empacar).',
        template='emails/aviso_dueno_transferencia.html',
        subject_template='Pedido #10247 esperando transferencia · $92.600',
        para_quien='Blanca + Eduardo (dueños)',
        contexto_fn=_ctx_aviso_transferencia,
    ),
    PreviewEntry(
        slug='instrucciones-transferencia',
        nombre='Instrucciones de transferencia · cliente',
        descripcion='Datos de la cuenta + monto + referencia para el cliente que eligió transferencia directa. Se envía al iniciar el pedido.',
        template='emails/transferencia_instrucciones.html',
        subject_template='Datos para transferir · Pedido #10247',
        para_quien='Cliente',
        contexto_fn=_ctx_instrucciones_transferencia,
    ),
    PreviewEntry(
        slug='bienvenida',
        nombre='Bienvenida · registro de cuenta',
        descripcion='Se manda cuando un cliente nuevo crea cuenta en la tienda. Apagado por feature flag por default.',
        template='emails/registro_bienvenida.html',
        subject_template='Bienvenida a Ideas Boutique, María',
        para_quien='Cliente nuevo',
        contexto_fn=_ctx_bienvenida,
        feature_flag='FEATURE_EMAIL_BIENVENIDA',
    ),
    PreviewEntry(
        slug='reset-password',
        nombre='Recuperar contraseña',
        descripcion='Link con token de reset cuando el cliente pide "Olvidé mi contraseña". Apagado por feature flag por default.',
        template='emails/recuperar_password.html',
        subject_template='Recuperar contraseña · Ideas Boutique',
        para_quien='Cliente',
        contexto_fn=_ctx_reset_password,
        feature_flag='FEATURE_EMAIL_RESET_PASSWORD',
    ),
    PreviewEntry(
        slug='stock-disponible',
        nombre='Volvió la talla · stock disponible',
        descripcion='Cliente había pedido "Avísame cuando vuelva" en una talla agotada. Se dispara cuando vuelve a entrar stock de esa variante.',
        template='emails/stock_disponible.html',
        subject_template='¡Volvió! Polera Piqué SFJ',
        para_quien='Cliente suscrito',
        contexto_fn=_ctx_stock_disponible,
        feature_flag='FEATURE_EMAIL_STOCK_DISPONIBLE',
    ),
    PreviewEntry(
        slug='carrito-abandonado',
        nombre='Carrito abandonado · +24h',
        descripcion='Cron diario recoge carritos sin checkout de hace 24h y manda este mail con el contenido del carrito guardado.',
        template='emails/carrito_abandonado.html',
        subject_template='Te guardamos lo que dejaste en el carrito',
        para_quien='Cliente que abandonó',
        contexto_fn=_ctx_carrito_abandonado,
        feature_flag='FEATURE_EMAIL_CARRITO_ABANDONADO',
    ),
    PreviewEntry(
        slug='pedir-resena',
        nombre='Pedir reseña · +14d',
        descripcion='+14 días post-compra, le pide al cliente que deje opinion del producto.',
        template='emails/pedir_resena.html',
        subject_template='¿Qué te pareció tu compra?',
        para_quien='Cliente con compra de hace 2 semanas',
        contexto_fn=_ctx_pedir_resena,
        feature_flag='FEATURE_EMAIL_PEDIR_RESENA',
    ),
    PreviewEntry(
        slug='recordatorio-familia',
        nombre='Recordatorio familia · febrero',
        descripcion='Una vez al año (febrero), avisa a familias con hijos en colegio que renueven el uniforme. Cron anual.',
        template='emails/recordatorio_familia.html',
        subject_template='Llegó febrero · ¿sigue quedando el uniforme?',
        para_quien='Familia con compras de uniforme escolar',
        contexto_fn=_ctx_recordatorio_familia,
        feature_flag='FEATURE_EMAIL_RECORDATORIO_FAMILIA',
    ),
]


def get_preview(slug: str) -> PreviewEntry | None:
    return next((p for p in PREVIEWS if p.slug == slug), None)
