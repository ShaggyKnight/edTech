"""Pasarela de pago online (ecommerce).

El POS presencial cobra de forma síncrona (`pos.payments`); aquí el flujo
es redirect-based: iniciamos la transacción, redirigimos al cliente al
proveedor (Webpay), y cuando vuelve confirmamos con un token.

Interfaz:
    init = gateway.iniciar_pago(recibo, return_url)  # devuelve URL para redirect
    result = gateway.confirmar_pago(token)          # resuelve PaymentResult final

El gateway activo se elige con `settings.ECOMMERCE_PAYMENT_GATEWAY`
(`mock` | `webpay` | ruta.a.ClaseGateway).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings
from django.urls import reverse
from django.utils.module_loading import import_string

from pos.payments import (
    ESTADO_CANCELADO,
    ESTADO_FALLIDO,
    ESTADO_PAGADO,
    ESTADO_PENDIENTE,
    PaymentGatewayError,
    PaymentResult,
)

log = logging.getLogger(__name__)


@dataclass
class OnlinePaymentInit:
    """Resultado de iniciar un pago online: a dónde redirigir al cliente."""
    redirect_url: str
    token: str
    provider: str


class OnlinePaymentGateway:
    """Interfaz base para pasarelas asincrónicas (redirect + commit)."""

    provider: str = ''

    def iniciar_pago(self, recibo, return_url: str) -> OnlinePaymentInit:
        raise NotImplementedError

    def confirmar_pago(self, token: str) -> PaymentResult:
        raise NotImplementedError


class MockOnlineGateway(OnlinePaymentGateway):
    """Simula un gateway redirect-based.

    Redirige a la vista `ecommerce:mock_pago` que pinta una mini-pasarela
    con botones "aprobar" / "rechazar". Útil para dev y E2E sin red.
    """

    provider = 'mock-online'

    def iniciar_pago(self, recibo, return_url: str) -> OnlinePaymentInit:
        token = recibo.payment_idempotency_key or f'MOCK-{recibo.pk}'
        redirect_url = (
            reverse('ecommerce:mock_pago') +
            f'?token={token}&return_url={return_url}'
        )
        return OnlinePaymentInit(
            redirect_url=redirect_url,
            token=token,
            provider=self.provider,
        )

    def confirmar_pago(self, token: str) -> PaymentResult:
        # El mock decide el resultado según un sufijo del token; por defecto paga.
        if token.endswith(':fail'):
            return PaymentResult(estado=ESTADO_FALLIDO, provider=self.provider, detalle='Mock rechazo')
        if token.endswith(':cancel'):
            return PaymentResult(estado=ESTADO_CANCELADO, provider=self.provider, detalle='Mock cancelado')
        return PaymentResult(
            estado=ESTADO_PAGADO,
            provider=self.provider,
            reference=token,
            detalle='Cobro simulado (MockOnlineGateway)',
        )


class WebpayGateway(OnlinePaymentGateway):
    """Webpay Plus (Transbank) REST.

    Docs: https://www.transbankdevelopers.cl/documentacion/webpay-plus
    Endpoints (integración):
        POST {BASE}/rswebpaytransaction/api/webpay/v1.2/transactions
        PUT  {BASE}/rswebpaytransaction/api/webpay/v1.2/transactions/{token}
    Headers:
        Tbk-Api-Key-Id: WEBPAY_COMMERCE_CODE
        Tbk-Api-Key-Secret: WEBPAY_API_KEY
    """

    provider = 'webpay'

    def __init__(
        self,
        commerce_code: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.commerce_code = commerce_code or getattr(settings, 'WEBPAY_COMMERCE_CODE', '')
        self.api_key = api_key or getattr(settings, 'WEBPAY_API_KEY', '')
        self.base_url = base_url or getattr(
            settings, 'WEBPAY_BASE_URL', 'https://webpay3gint.transbank.cl'
        )
        if not self.commerce_code or not self.api_key:
            raise PaymentGatewayError(
                'WebpayGateway requiere WEBPAY_COMMERCE_CODE y WEBPAY_API_KEY en settings/.env'
            )

    def _headers(self):
        return {
            'Tbk-Api-Key-Id': self.commerce_code,
            'Tbk-Api-Key-Secret': self.api_key,
            'Content-Type': 'application/json',
        }

    def iniciar_pago(self, recibo, return_url: str) -> OnlinePaymentInit:
        payload = {
            'buy_order': f'R{recibo.pk:08d}',
            'session_id': recibo.payment_idempotency_key or f'S{recibo.pk}',
            'amount': int(recibo.total),
            'return_url': return_url,
        }
        try:
            resp = requests.post(
                f'{self.base_url}/rswebpaytransaction/api/webpay/v1.2/transactions',
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise PaymentGatewayError(f'Error iniciando Webpay: {exc}') from exc

        if resp.status_code >= 400:
            raise PaymentGatewayError(f'Webpay {resp.status_code}: {resp.text[:200]}')

        data = resp.json()
        token = data['token']
        url = data['url']
        return OnlinePaymentInit(
            redirect_url=f'{url}?token_ws={token}',
            token=token,
            provider=self.provider,
        )

    def confirmar_pago(self, token: str) -> PaymentResult:
        try:
            resp = requests.put(
                f'{self.base_url}/rswebpaytransaction/api/webpay/v1.2/transactions/{token}',
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            log.exception('Error confirmando Webpay')
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider, detalle=f'Error de red: {exc}'
            )

        if resp.status_code >= 400:
            return PaymentResult(
                estado=ESTADO_FALLIDO,
                provider=self.provider,
                detalle=f'Webpay {resp.status_code}: {resp.text[:200]}',
            )

        data = resp.json()
        status = data.get('status', '').upper()
        response_code = data.get('response_code')
        estado = ESTADO_PENDIENTE
        if status == 'AUTHORIZED' and response_code == 0:
            estado = ESTADO_PAGADO
        elif status in ('FAILED', 'REVERSED', 'NULLIFIED'):
            estado = ESTADO_FALLIDO
        elif status == 'CANCELED':
            estado = ESTADO_CANCELADO
        return PaymentResult(
            estado=estado,
            provider=self.provider,
            reference=str(data.get('authorization_code', token)),
            detalle=f'status={status} code={response_code}',
        )


_GATEWAYS = {
    'mock': MockOnlineGateway,
    'webpay': WebpayGateway,
}


def get_online_gateway() -> OnlinePaymentGateway:
    """Devuelve la instancia del gateway online configurado en settings."""
    nombre = getattr(settings, 'ECOMMERCE_PAYMENT_GATEWAY', 'mock')
    if isinstance(nombre, str) and '.' in nombre:
        cls = import_string(nombre)
    else:
        cls = _GATEWAYS.get(nombre)
        if cls is None:
            raise PaymentGatewayError(f'ECOMMERCE_PAYMENT_GATEWAY desconocido: {nombre!r}')
    return cls()
