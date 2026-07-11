"""Transferencia bancaria DIRECTA — confirmacion manual de la dueña.

El respaldo activable de las pasarelas: sin comision, sin certificacion,
sin depender de terceros. El flujo:

  1. El cliente elige "Transferencia bancaria" en el checkout.
  2. El pedido queda PENDIENTE y se le muestran (pagina + correo) los
     datos de la cuenta, el monto exacto y el numero de pedido como
     referencia. El comprobante lo manda por WhatsApp (sin subir
     archivos al sitio).
  3. La dueña ve el abono en su banco y CONFIRMA el pago en la pestana
     "Por confirmar" de Despacho — recien ahi se descuenta stock, sale
     la boleta y el pedido entra a la cola normal.

Activable/desactivable por .env:
    ECOMMERCE_GATEWAYS_ACTIVOS=khipu,transferencia
    TRANSFERENCIA_NOMBRE / _RUT / _BANCO / _TIPO_CUENTA / _CUENTA

Si faltan los datos de la cuenta, el gateway no se activa (el registry
lo salta silenciosamente) — misma mecanica que un gateway sin
credenciales.
"""
from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.urls import reverse

from ecommerce.gateways.base import OnlinePaymentGateway, OnlinePaymentInit
from pos.payments import ESTADO_PENDIENTE, PaymentGatewayError, PaymentResult

log = logging.getLogger(__name__)


def datos_cuenta() -> dict:
    """Datos bancarios configurados en el .env (para la pagina y el correo)."""
    return {
        'nombre': getattr(settings, 'TRANSFERENCIA_NOMBRE', ''),
        'rut': getattr(settings, 'TRANSFERENCIA_RUT', ''),
        'banco': getattr(settings, 'TRANSFERENCIA_BANCO', ''),
        'tipo_cuenta': getattr(settings, 'TRANSFERENCIA_TIPO_CUENTA', ''),
        'cuenta': getattr(settings, 'TRANSFERENCIA_CUENTA', ''),
        'email': getattr(settings, 'TRANSFERENCIA_EMAIL', ''),
    }


class TransferenciaGateway(OnlinePaymentGateway):
    provider = 'transferencia'
    nombre_publico = 'Transferencia directa'
    subtitulo = 'Te damos los datos y confirmamos apenas llegue tu abono'
    icono = '💸'
    comision_descripcion = 'Sin comision — confirmacion manual de la dueña'

    def __init__(self):
        datos = datos_cuenta()
        # Sin cuenta configurada el gateway NO puede operar. Levantar
        # aca hace que get_gateways_activos() lo salte con un warning —
        # ese es el interruptor de "desactivado".
        if not (datos['nombre'] and datos['rut'] and datos['cuenta']):
            raise PaymentGatewayError(
                'Transferencia directa sin datos bancarios en .env '
                '(TRANSFERENCIA_NOMBRE / _RUT / _CUENTA).'
            )

    def iniciar_pago(self, recibo, return_url):
        # No hay pasarela: "iniciar el pago" es llevar al cliente a la
        # pagina interna con las instrucciones. El pedido queda
        # pendiente hasta la confirmacion manual.
        token = recibo.payment_idempotency_key or str(uuid.uuid4())
        redirect_url = reverse(
            'ecommerce:transferencia_instrucciones', args=[token],
        )
        log.info('Pedido #%s esperando transferencia directa.', recibo.pk)
        return OnlinePaymentInit(
            redirect_url=redirect_url, token=token, provider=self.provider,
        )

    def confirmar_pago(self, token):
        """NUNCA se autoconfirma: el pago lo valida la dueña a mano en
        Despacho (contra la cartola del banco)."""
        return PaymentResult(
            estado=ESTADO_PENDIENTE, provider=self.provider,
            detalle='Esperando transferencia y confirmación manual.',
        )
