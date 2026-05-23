"""Khipu — pago por transferencia bancaria.

Khipu es un agregador chileno de transferencias bancarias. El cliente
elige su banco, se loguea via su webapp, y autoriza la transferencia.
Comision aproximada 0,79% — la mas baja del mercado chileno.

Estado: ESQUELETO. Mismo enfoque que klap.py: estructura matcheando la
API real, ejecucion en modo mock. Swap a producción con las
credenciales en .env.

Docs (cuando estes activado): docs.khipu.com (API 3.0 recomendada)
Soporte: comercios@khipu.com

Settings esperados:
    KHIPU_RECEIVER_ID=...
    KHIPU_SECRET=...           # firmar HMAC de requests
    KHIPU_BASE_URL=https://payment-api.khipu.com  # v3
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.conf import settings

from ecommerce.gateways.base import (
    OnlinePaymentGateway, OnlinePaymentInit, WebhookResult,
)
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
    PaymentGatewayError, PaymentResult,
)

log = logging.getLogger(__name__)


class KhipuGateway(OnlinePaymentGateway):
    provider = 'khipu'
    nombre_publico = 'Transferencia bancaria'
    subtitulo = 'Pagas desde tu banco con Khipu — comision mas baja'
    icono = '🏦'
    comision_descripcion = '0,79% por transferencia · sin fee fijo'

    def __init__(self):
        self.receiver_id = getattr(settings, 'KHIPU_RECEIVER_ID', '')
        self.secret = getattr(settings, 'KHIPU_SECRET', '')
        self.base_url = getattr(
            settings, 'KHIPU_BASE_URL', 'https://payment-api.khipu.com',
        ).rstrip('/')
        self.mock_mode = not (self.receiver_id and self.secret)
        if self.mock_mode and not settings.DEBUG:
            log.warning(
                'KhipuGateway en MOCK_MODE en prod — faltan KHIPU_RECEIVER_ID '
                'o KHIPU_SECRET en .env.',
            )

    # ─── Flujo principal ───────────────────────────────────────────

    def iniciar_pago(self, recibo, return_url):
        if self.mock_mode:
            return self._mock_iniciar_pago(recibo, return_url)

        # [REAL]
        # payload = self._build_payload(recibo, return_url)
        # try:
        #     resp = requests.post(
        #         f'{self.base_url}/v3/payments',
        #         json=payload,
        #         headers=self._headers(),
        #         timeout=15,
        #     )
        # except requests.RequestException as exc:
        #     raise PaymentGatewayError(f'Khipu request error: {exc}') from exc
        # if resp.status_code >= 400:
        #     raise PaymentGatewayError(
        #         f'Khipu {resp.status_code}: {resp.text[:300]}',
        #     )
        # data = resp.json()
        # # Khipu devuelve payment_url (checkout web) y simplified_transfer_url
        # # (PWA mas rapida). Preferimos la simplified.
        # checkout = data.get('simplified_transfer_url') or data['payment_url']
        # return OnlinePaymentInit(
        #     redirect_url=checkout,
        #     token=data['payment_id'],
        #     provider=self.provider,
        # )
        raise PaymentGatewayError(
            'KhipuGateway: integracion real no implementada. '
            'Definir KHIPU_RECEIVER_ID y KHIPU_SECRET en .env.',
        )

    def confirmar_pago(self, token):
        if self.mock_mode:
            return self._mock_confirmar_pago(token)

        # [REAL]
        # try:
        #     resp = requests.get(
        #         f'{self.base_url}/v3/payments/{token}',
        #         headers=self._headers(),
        #         timeout=15,
        #     )
        # except requests.RequestException as exc:
        #     return PaymentResult(
        #         estado=ESTADO_FALLIDO, provider=self.provider,
        #         detalle=f'Khipu red error: {exc}',
        #     )
        # if resp.status_code >= 400:
        #     return PaymentResult(
        #         estado=ESTADO_FALLIDO, provider=self.provider,
        #         detalle=f'Khipu {resp.status_code}',
        #     )
        # data = resp.json()
        # return self._map_estado(data)
        return PaymentResult(
            estado=ESTADO_FALLIDO, provider=self.provider,
            detalle='KhipuGateway: integracion real no implementada',
        )

    def webhook(self, request):
        """Procesa una notificacion `notify_url` de Khipu.

        Khipu firma con HMAC-SHA256. El header esperado es
        `X-Khipu-Signature` con formato `t=<timestamp>,s=<hex>`.
        """
        signature_header = request.headers.get('X-Khipu-Signature', '')
        body = request.body

        if not self._verificar_firma(body, signature_header):
            log.warning('Webhook Khipu con firma invalida — ignorado.')
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=False,
                detalle='Firma invalida',
            )

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=False,
                detalle='JSON invalido',
            )

        recibo_pk = self._parsear_recibo_pk(
            data.get('transaction_id', ''),
        )
        result = self._map_estado(data)
        log.info(
            'Webhook Khipu procesado: payment_id=%s recibo=%s estado=%s',
            data.get('payment_id'), recibo_pk, result.estado,
        )
        return WebhookResult(
            recibo_pk=recibo_pk, payment_result=result, handled=True,
        )

    # ─── Helpers internos ──────────────────────────────────────────

    def _headers(self):
        """Khipu API 3.0 usa Bearer con la secret key."""
        return {
            'Authorization': f'Bearer {self.secret}',
            'Content-Type': 'application/json',
        }

    def _build_payload(self, recibo, return_url):
        cancel_url = return_url.replace('/retorno/', '/cancel/')
        notify_url = return_url.replace(
            '/retorno/', '/pago/webhook/khipu/',
        )
        return {
            'subject': f'Compra Ideas Boutique #{recibo.pk}',
            'amount': float(recibo.total),
            'currency': 'CLP',
            'transaction_id': f'IBR-{recibo.pk:08d}',
            'custom': str(recibo.pk),
            'body': f'Pedido #{recibo.pk} — Ideas Boutique',
            'return_url': return_url,
            'cancel_url': cancel_url,
            'notify_url': notify_url,
            'notify_api_version': '3.0',
            'payer_email': recibo.cliente_email or '',
            'payer_name': recibo.cliente_nombre or '',
            'expires_date': None,  # Khipu default: 6 horas
        }

    def _verificar_firma(self, body: bytes, signature_header: str) -> bool:
        if not self.secret or not signature_header:
            return False
        # Header formato `t=<ts>,s=<hex>` (Khipu 3.0)
        partes = dict(p.split('=', 1) for p in signature_header.split(',')
                       if '=' in p)
        firma_recibida = partes.get('s', '')
        timestamp = partes.get('t', '')
        if not firma_recibida or not timestamp:
            return False
        firmable = f'{timestamp}.'.encode('utf-8') + body
        firma_esperada = hmac.new(
            self.secret.encode('utf-8'),
            firmable, hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(firma_esperada, firma_recibida)

    def _map_estado(self, data: dict) -> PaymentResult:
        """Khipu estados: pending, verifying, done, rejected, refunded,
        retained, reversed, claimed.
        """
        estado_khipu = (data.get('status') or '').lower()
        mapping = {
            'done':       ESTADO_PAGADO,
            'verifying':  ESTADO_PENDIENTE,
            'pending':    ESTADO_PENDIENTE,
            'rejected':   ESTADO_FALLIDO,
            'reversed':   ESTADO_FALLIDO,
            'retained':   ESTADO_PENDIENTE,
            'refunded':   ESTADO_CANCELADO,
            'claimed':    ESTADO_PENDIENTE,
        }
        estado = mapping.get(estado_khipu, ESTADO_PENDIENTE)
        return PaymentResult(
            estado=estado, provider=self.provider,
            reference=str(data.get('payment_id')
                          or data.get('transaction_id') or ''),
            detalle=f'Khipu status={estado_khipu}',
        )

    def _parsear_recibo_pk(self, transaction_id: str) -> int | None:
        if not transaction_id.startswith('IBR-'):
            return None
        try:
            return int(transaction_id[4:])
        except ValueError:
            return None

    # ─── Modo mock ─────────────────────────────────────────────────

    def _mock_iniciar_pago(self, recibo, return_url):
        from django.urls import reverse
        token = f'KHIPU-MOCK-{recibo.pk}'
        redirect_url = (
            reverse('ecommerce:mock_pago') +
            f'?token={token}&return_url={return_url}&gateway=khipu'
        )
        return OnlinePaymentInit(
            redirect_url=redirect_url, token=token, provider=self.provider,
        )

    def _mock_confirmar_pago(self, token):
        if ':fail' in token:
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider,
                detalle='Mock Khipu rechazado',
            )
        if ':cancel' in token:
            return PaymentResult(
                estado=ESTADO_CANCELADO, provider=self.provider,
                detalle='Mock Khipu cancelado',
            )
        return PaymentResult(
            estado=ESTADO_PAGADO, provider=self.provider,
            reference=f'KHIPU-{token}',
            detalle='Mock Khipu transferencia confirmada',
        )
