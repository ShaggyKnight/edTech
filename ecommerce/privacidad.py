"""Derechos de los titulares de datos (Ley 21.719): acceso, portabilidad
y supresion.

Lo usan la cuenta del cliente ("Descargar mis datos" / "Eliminar mi
cuenta") y el comando `datos_personales`, para atender a quienes compraron
sin cuenta y escriben por correo o WhatsApp.

Supresion = borrar lo que no hay por que guardar (cuenta, avisos de
reposicion, resenas) y ANONIMIZAR los pedidos: el registro de la venta
(productos, montos, fechas) se conserva por la ley tributaria, pero sin
nombre, correo, telefono, direccion ni RUT. Las facturas (DTE 33) si
llevan los datos del comprador por ley y no se tocan.
"""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from catalogo.models import Resena
from ecommerce.models import AvisoStockReposicion
from pos.models import ReciboVenta

DTE_FACTURA = 33

# Campos personales de un recibo y el valor con que quedan al anonimizar.
CAMPOS_PERSONALES_RECIBO = {
    'cliente_nombre': '',
    'cliente_email': '',
    'cliente_rut': '',
    'cliente_telefono': '',
    'cliente_direccion': '',
    'cliente_usuario': None,
}


def recibos_de(email: str, usuario=None):
    """Recibos (de cualquier canal) asociados al correo o a la cuenta."""
    filtro = Q(pk__in=[])
    if email:
        filtro |= Q(cliente_email__iexact=email)
    if usuario is not None:
        filtro |= Q(cliente_usuario=usuario)
    return ReciboVenta.objects.filter(filtro)


def pedidos_en_curso(email: str, usuario=None):
    """Pedidos que todavia necesitan los datos de contacto: pagados sin
    entregar y transferencias por confirmar."""
    return recibos_de(email, usuario).filter(
        Q(canal=ReciboVenta.CANAL_ONLINE, estado=ReciboVenta.ESTADO_PAGADO,
          despachado_en__isnull=True)
        | Q(estado=ReciboVenta.ESTADO_PENDIENTE, payment_provider='transferencia')
    )


def anonimizar_recibos(qs) -> int:
    """Borra los datos personales de los recibos (salvo facturas).
    Devuelve cuantos cambiaron."""
    return (
        qs.exclude(dte_tipo=DTE_FACTURA)
        .update(**CAMPOS_PERSONALES_RECIBO, modificado=timezone.now())
    )


def _fecha(valor):
    return valor.isoformat() if valor else None


def datos_de(email: str, usuario=None) -> dict:
    """Todo lo que la tienda guarda de una persona, en un formato ordenado
    y de uso comun (derechos de acceso y portabilidad)."""
    cuenta = None
    if usuario is not None:
        cuenta = {
            'usuario': usuario.get_username(),
            'correo': usuario.email,
            'nombre': usuario.first_name,
            'apellido': usuario.last_name,
            'fecha_registro': _fecha(usuario.date_joined),
            'ultimo_ingreso': _fecha(usuario.last_login),
        }

    pedidos = []
    recibos = (
        recibos_de(email, usuario)
        .prefetch_related('detalles')
        .order_by('creado')
    )
    for r in recibos:
        pedidos.append({
            'numero': r.pk,
            'fecha': _fecha(r.creado),
            'canal': r.get_canal_display(),
            'estado': r.get_estado_display(),
            'total': int(r.total),
            'medio_de_pago': r.payment_provider,
            'nombre': r.cliente_nombre,
            'correo': r.cliente_email,
            'telefono': r.cliente_telefono,
            'direccion': r.cliente_direccion,
            'rut': r.cliente_rut,
            'productos': [
                {
                    'descripcion': d.descripcion,
                    'cantidad': d.cantidad,
                    'precio_unitario': int(d.precio_unitario),
                    'descuento': int(d.descuento),
                }
                for d in r.detalles.all()
            ],
        })

    avisos = []
    resenas = []
    if email:
        for a in (AvisoStockReposicion.objects.filter(email__iexact=email)
                  .select_related('variante__producto')):
            avisos.append({
                'producto': a.variante.producto.nombre,
                'variante': a.variante.sku,
                'solicitado': _fecha(a.creado),
                'avisado': _fecha(a.notificado),
                'dado_de_baja': _fecha(a.cancelado),
            })
        for r in Resena.objects.filter(cliente_email__iexact=email).select_related('producto'):
            resenas.append({
                'producto': r.producto.nombre,
                'estrellas': r.estrellas,
                'titulo': r.titulo,
                'texto': r.texto,
                'nombre_publico': r.nombre_publico,
                'estado': r.get_estado_display(),
                'fecha': _fecha(r.creado),
            })

    return {
        'generado': _fecha(timezone.now()),
        'responsable': getattr(settings, 'EMPRESA_RAZON_SOCIAL', 'Ideas Boutique'),
        'contacto_privacidad': getattr(settings, 'PRIVACIDAD_EMAIL', ''),
        'correo_consultado': email,
        'cuenta': cuenta,
        'pedidos': pedidos,
        'avisos_de_reposicion': avisos,
        'resenas': resenas,
    }


@transaction.atomic
def suprimir_datos(email: str, usuario=None) -> dict:
    """Elimina y anonimiza los datos de una persona (derecho de supresion).

    Borra la cuenta (si viene), los avisos de reposicion y las resenas, y
    anonimiza sus pedidos salvo facturas. El que llama debe revisar antes
    `pedidos_en_curso`: un pedido sin entregar necesita el contacto.
    """
    recibos = recibos_de(email, usuario)
    facturas = recibos.filter(dte_tipo=DTE_FACTURA).count()
    pedidos = anonimizar_recibos(recibos)
    avisos = resenas = 0
    if email:
        avisos = AvisoStockReposicion.objects.filter(email__iexact=email).delete()[0]
        resenas = Resena.objects.filter(cliente_email__iexact=email).delete()[0]
    cuenta = False
    if usuario is not None:
        usuario.delete()
        cuenta = True
    return {
        'cuenta_eliminada': cuenta,
        'pedidos_anonimizados': pedidos,
        'facturas_conservadas': facturas,
        'avisos_eliminados': avisos,
        'resenas_eliminadas': resenas,
    }
