"""KLAP — pasarela de pago online (tarjetas de credito y debito).

Multicaja/Tata. Comision aproximada 1,39% debito + 2,75% credito.
Sin fee fijo mensual. API server-to-server con commerce_id + api_key.

Estado: ESQUELETO. La estructura matchea la API real esperada pero
hoy es un mock funcional (no toca red). Cuando se obtengan las
credenciales reales, descomentar los bloques HTTP marcados con `[REAL]`
y borrar los bloques `[MOCK]`.

Docs (cuando estes activado): developers.klap.cl
Soporte: comercios@klap.cl

Settings esperados en .env:
    KLAP_COMMERCE_ID=...
    KLAP_API_KEY=...
    KLAP_WEBHOOK_SECRET=...
    KLAP_BASE_URL=https://api.klap.cl   # o sandbox.klap.cl en cert
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

from django.conf import settings

from ecommerce.gateways.base import (
    OnlinePaymentGateway, OnlinePaymentInit, WebhookResult,
)
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
    PaymentGatewayError, PaymentResult,
)

log = logging.getLogger(__name__)


class KlapGateway(OnlinePaymentGateway):
    provider = 'klap'
    nombre_publico = 'Tarjeta de credito o debito'
    subtitulo = 'Pagas con KLAP — Visa, Mastercard, Redcompra'
    icono = '💳'
    comision_descripcion = '1,39% debito · 2,75% credito · sin fee fijo'

    def __init__(self):
        self.commerce_id = getattr(settings, 'KLAP_COMMERCE_ID', '')
        self.api_key = getattr(settings, 'KLAP_API_KEY', '')
        self.webhook_secret = getattr(settings, 'KLAP_WEBHOOK_SECRET', '')
        self.base_url = getattr(
            settings, 'KLAP_BASE_URL', 'https://sandbox.klap.cl',
        ).rstrip('/')
        # MODO MOCK: si no hay credenciales, el adapter funciona pero
        # contra una simulacion local (util en dev/staging sin tocar
        # KLAP). En prod ESTO debe fallar duro.
        self.mock_mode = not (self.commerce_id and self.api_key)
        if self.mock_mode and not settings.DEBUG:
            log.warning(
                'KlapGateway en MOCK_MODE en prod — faltan KLAP_COMMERCE_ID '
                'o KLAP_API_KEY en .env. Las "transacciones" no son reales.'
            )

    # ─── Flujo principal ────────────────────────────────────────────

    def iniciar_pago(self, recibo, return_url):
        """Crea la transaccion en KLAP y devuelve la URL del checkout
        hosted al que hay que redirigir al cliente."""
        if self.mock_mode:
            return self._mock_iniciar_pago(recibo, return_url)

        # [REAL] — descomentar cuando haya credenciales
        # payload = self._build_payload(recibo, return_url)
        # try:
        #     resp = requests.post(
        #         f'{self.base_url}/v1/transactions',
        #         json=payload,
        #         headers=self._headers(),
        #         timeout=15,
        #     )
        # except requests.RequestException as exc:
        #     raise PaymentGatewayError(f'KLAP request error: {exc}') from exc
        # if resp.status_code >= 400:
        #     raise PaymentGatewayError(
        #         f'KLAP {resp.status_code}: {resp.text[:300]}',
        #     )
        # data = resp.json()
        # return OnlinePaymentInit(
        #     redirect_url=data['checkout_url'],
        #     token=data['transaction_id'],
        #     provider=self.provider,
        # )
        raise PaymentGatewayError(
            'KlapGateway: integracion real no implementada. '
            'Definir KLAP_COMMERCE_ID y KLAP_API_KEY para usar mock_mode.',
        )

    def confirmar_pago(self, token):
        """Consulta el estado de la transaccion. Llamada al volver el
        cliente al sitio (redirect post-pago)."""
        if self.mock_mode:
            return self._mock_confirmar_pago(token)

        # [REAL]
        # try:
        #     resp = requests.get(
        #         f'{self.base_url}/v1/transactions/{token}',
        #         headers=self._headers(),
        #         timeout=15,
        #     )
        # except requests.RequestException as exc:
        #     return PaymentResult(
        #         estado=ESTADO_FALLIDO, provider=self.provider,
        #         detalle=f'KLAP red error: {exc}',
        #     )
        # if resp.status_code >= 400:
        #     return PaymentResult(
        #         estado=ESTADO_FALLIDO, provider=self.provider,
        #         detalle=f'KLAP {resp.status_code}',
        #     )
        # data = resp.json()
        # return self._map_estado(data)
        return PaymentResult(
            estado=ESTADO_FALLIDO, provider=self.provider,
            detalle='KlapGateway: integracion real no implementada',
        )

    def webhook(self, request):
        """Procesa una notificacion server-to-server de KLAP.

        KLAP firma el body con HMAC-SHA256 usando KLAP_WEBHOOK_SECRET.
        El header esperado es `X-Klap-Signature: sha256=<hex>`.
        """
        signature_header = request.headers.get('X-Klap-Signature', '')
        body = request.body

        if not self._verificar_firma(body, signature_header):
            log.warning('Webhook KLAP con firma invalida — ignorado.')
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

        token = data.get('transaction_id') or data.get('token')
        merchant_ref = data.get('merchant_reference', '')
        recibo_pk = self._parsear_recibo_pk(merchant_ref)

        result = self._map_estado(data)
        log.info(
            'Webhook KLAP procesado: token=%s recibo=%s estado=%s',
            token, recibo_pk, result.estado,
        )
        return WebhookResult(
            recibo_pk=recibo_pk, payment_result=result, handled=True,
        )

    # ─── Helpers internos ──────────────────────────────────────────

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'X-Klap-Commerce-Id': self.commerce_id,
            'Content-Type': 'application/json',
        }

    def _build_payload(self, recibo, return_url):
        """Construye el body para POST /v1/transactions.

        merchant_reference embebe el pk del recibo asi cuando vuelve el
        callback sabemos a que ReciboVenta asociar el pago.
        """
        return {
            'amount': int(recibo.total),
            'currency': 'CLP',
            'merchant_reference': f'IBR-{recibo.pk:08d}',
            'return_url': return_url,
            'description': f'Compra Ideas Boutique #{recibo.pk}',
            'customer': {
                'name': recibo.cliente_nombre or 'Cliente',
                'email': recibo.cliente_email or '',
            },
            'idempotency_key': recibo.payment_idempotency_key
                                or str(uuid.uuid4()),
        }

    def _verificar_firma(self, body: bytes, signature_header: str) -> bool:
        """Valida la firma HMAC del webhook. Constante-time compare."""
        if not self.webhook_secret or not signature_header:
            return False
        # Formato esperado: "sha256=<hex>"
        partes = signature_header.split('=', 1)
        if len(partes) != 2 or partes[0] != 'sha256':
            return False
        firma_recibida = partes[1]
        firma_esperada = hmac.new(
            self.webhook_secret.encode('utf-8'),
            body, hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(firma_esperada, firma_recibida)

    def _map_estado(self, data: dict) -> PaymentResult:
        """Mapea el estado de KLAP a PaymentResult. KLAP usa strings tipo
        `approved`, `rejected`, `pending`, `cancelled`."""
        estado_klap = (data.get('status') or '').lower()
        mapping = {
            'approved': ESTADO_PAGADO,
            'paid':     ESTADO_PAGADO,
            'success':  ESTADO_PAGADO,
            'pending':  ESTADO_PENDIENTE,
            'rejected': ESTADO_FALLIDO,
            'declined': ESTADO_FALLIDO,
            'failed':   ESTADO_FALLIDO,
            'error':    ESTADO_FALLIDO,
            'cancelled': ESTADO_CANCELADO,
            'canceled': ESTADO_CANCELADO,
        }
        estado = mapping.get(estado_klap, ESTADO_PENDIENTE)
        return PaymentResult(
            estado=estado, provider=self.provider,
            reference=str(data.get('authorization_code')
                          or data.get('transaction_id') or ''),
            detalle=f'KLAP status={estado_klap}',
        )

    def _parsear_recibo_pk(self, merchant_ref: str) -> int | None:
        """`IBR-00000042` -> 42."""
        if not merchant_ref.startswith('IBR-'):
            return None
        try:
            return int(merchant_ref[4:])
        except ValueError:
            return None

    # ─── Modo mock (sin credenciales / dev) ────────────────────────

    def _mock_iniciar_pago(self, recibo, return_url):
        from django.urls import reverse
        token = f'KLAP-MOCK-{recibo.pk}'
        redirect_url = (
            reverse('ecommerce:mock_pago') +
            f'?token={token}&return_url={return_url}&gateway=klap'
        )
        return OnlinePaymentInit(
            redirect_url=redirect_url, token=token, provider=self.provider,
        )

    def _mock_confirmar_pago(self, token):
        if ':fail' in token:
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider,
                detalle='Mock KLAP rechazado',
            )
        if ':cancel' in token:
            return PaymentResult(
                estado=ESTADO_CANCELADO, provider=self.provider,
                detalle='Mock KLAP cancelado',
            )
        return PaymentResult(
            estado=ESTADO_PAGADO, provider=self.provider,
            reference=f'KLAP-AUTH-{token}',
            detalle='Mock KLAP aprobado',
        )
