"""Abstracción de pasarela de pago para el POS presencial.

El resto del código habla con un `PaymentGateway` genérico; los detalles del
proveedor (TUU hoy, otros mañana) quedan confinados aquí. El gateway activo
se selecciona con `settings.PAYMENT_GATEWAY` (`mock` | `tuu`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings
from django.utils.module_loading import import_string

log = logging.getLogger(__name__)


ESTADO_PENDIENTE = 'pendiente'
ESTADO_PAGADO = 'pagado'
ESTADO_FALLIDO = 'fallido'
ESTADO_CANCELADO = 'cancelado'


@dataclass
class PaymentResult:
    """Resultado de un intento de cobro."""
    estado: str
    provider: str
    reference: str = ''
    detalle: str = ''

    @property
    def exitoso(self) -> bool:
        return self.estado == ESTADO_PAGADO


class PaymentGatewayError(Exception):
    """Error no recuperable del proveedor de pago."""


class PaymentGateway:
    """Interfaz base. Todas las pasarelas implementan `cobrar()`."""

    provider: str = ''

    def cobrar(self, recibo) -> PaymentResult:
        """Inicia y resuelve (o deja pendiente) un cobro por `recibo.total`.

        La implementación puede ser síncrona (Mock) o bloqueante con polling
        interno (Tuu). El caller espera un `PaymentResult` final.
        """
        raise NotImplementedError


class MockGateway(PaymentGateway):
    """Siempre cobra exitosamente. Para desarrollo y tests."""

    provider = 'mock'

    def cobrar(self, recibo) -> PaymentResult:
        return PaymentResult(
            estado=ESTADO_PAGADO,
            provider=self.provider,
            reference=f'MOCK-{recibo.pk}',
            detalle='Cobro simulado (MockGateway)',
        )


class TuuGateway(PaymentGateway):
    """Integración real con TUU (Haulmer) vía API Pago Remoto.

    Docs: https://developers.tuu.cl/docs/getting-started
    Endpoint: https://integrations.payment.haulmer.com
    """

    provider = 'tuu'
    BASE_URL = 'https://integrations.payment.haulmer.com'
    POLL_INTERVAL_SEG = 3
    POLL_TIMEOUT_SEG = 180

    ESTADO_MAP = {
        0: ESTADO_PENDIENTE,   # Pending
        1: ESTADO_PENDIENTE,   # Sent
        2: ESTADO_CANCELADO,   # Canceled
        3: ESTADO_PENDIENTE,   # Processing
        4: ESTADO_FALLIDO,     # Failed
        5: ESTADO_PAGADO,      # Completed
    }

    def __init__(self, api_key: Optional[str] = None, device: Optional[str] = None):
        self.api_key = api_key or getattr(settings, 'TUU_API_KEY', '')
        self.device = device or getattr(settings, 'TUU_DEVICE_SERIAL', '')
        if not self.api_key or not self.device:
            raise PaymentGatewayError(
                'TuuGateway requiere TUU_API_KEY y TUU_DEVICE_SERIAL en settings/.env'
            )

    def _headers(self):
        return {'X-API-Key': self.api_key, 'Content-Type': 'application/json'}

    def cobrar(self, recibo) -> PaymentResult:
        monto = int(recibo.total)
        idem = recibo.payment_idempotency_key
        if not idem:
            raise PaymentGatewayError('El recibo no tiene payment_idempotency_key asignado')

        payload = {
            'amount': monto,
            'device': self.device,
            'idempotencyKey': idem,
            'description': f'Recibo {recibo.pk}',
        }
        if recibo.dte_tipo:
            payload['dteType'] = recibo.dte_tipo

        try:
            resp = requests.post(
                f'{self.BASE_URL}/RemotePayment/v2/Create',
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            log.exception('Error iniciando cobro TUU')
            return PaymentResult(
                estado=ESTADO_FALLIDO,
                provider=self.provider,
                detalle=f'Error de red: {exc}',
            )

        if resp.status_code >= 400:
            return PaymentResult(
                estado=ESTADO_FALLIDO,
                provider=self.provider,
                detalle=f'TUU {resp.status_code}: {resp.text[:200]}',
            )

        return self._poll_hasta_resolver(idem)

    def _poll_hasta_resolver(self, idempotency_key: str) -> PaymentResult:
        deadline = time.monotonic() + self.POLL_TIMEOUT_SEG
        while time.monotonic() < deadline:
            time.sleep(self.POLL_INTERVAL_SEG)
            try:
                resp = requests.get(
                    f'{self.BASE_URL}/RemotePayment/v2/GetPaymentReques/{idempotency_key}',
                    headers=self._headers(),
                    timeout=15,
                )
            except requests.RequestException as exc:
                log.warning('Error en polling TUU: %s', exc)
                continue

            if resp.status_code >= 400:
                log.warning('TUU polling HTTP %s: %s', resp.status_code, resp.text[:200])
                continue

            data = resp.json()
            status_code = data.get('status')
            estado = self.ESTADO_MAP.get(status_code, ESTADO_PENDIENTE)
            if estado in (ESTADO_PAGADO, ESTADO_FALLIDO, ESTADO_CANCELADO):
                return PaymentResult(
                    estado=estado,
                    provider=self.provider,
                    reference=str(data.get('id', '')),
                    detalle=data.get('message', ''),
                )

        return PaymentResult(
            estado=ESTADO_FALLIDO,
            provider=self.provider,
            detalle=f'Timeout esperando respuesta de TUU (>{self.POLL_TIMEOUT_SEG}s)',
        )


_GATEWAYS = {
    'mock': MockGateway,
    'tuu': TuuGateway,
}


def get_gateway() -> PaymentGateway:
    """Devuelve la instancia del gateway configurado en settings."""
    nombre = getattr(settings, 'PAYMENT_GATEWAY', 'mock')
    if isinstance(nombre, str) and '.' in nombre:
        # Permite apuntar a una clase custom: settings.PAYMENT_GATEWAY = 'myapp.gateways.FooGateway'
        cls = import_string(nombre)
    else:
        cls = _GATEWAYS.get(nombre)
        if cls is None:
            raise PaymentGatewayError(f'PAYMENT_GATEWAY desconocido: {nombre!r}')
    return cls()
