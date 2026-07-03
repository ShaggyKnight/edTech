"""Khipu — pago por transferencia bancaria (API v3, REAL).

Khipu es un agregador chileno de transferencias bancarias. El cliente
elige su banco, se loguea via su webapp, y autoriza la transferencia.
Comision aproximada 0,79% — la mas baja del mercado chileno.

Estado: INTEGRACION REAL contra la API 3.0. Si falta KHIPU_API_KEY en
el .env, cae a modo mock (simulador local) — asi dev/staging siguen
funcionando sin credenciales.

Docs: docs.khipu.com (API 3.0)
Soporte: comercios@khipu.com

Settings esperados:
    KHIPU_API_KEY=...       # API Key del panel ("x-api-key" en cada llamada)
    KHIPU_SECRET=...        # "Llave de cobrador" — SOLO para verificar la
                            # firma HMAC de los webhooks (no viaja en requests)
    KHIPU_RECEIVER_ID=...   # Id de cobrador (informativo / soporte)
    KHIPU_BASE_URL=https://payment-api.khipu.com
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from django.conf import settings
from django.urls import reverse

from ecommerce.gateways.base import (
    OnlinePaymentGateway, OnlinePaymentInit, WebhookResult,
)
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
    PaymentGatewayError, PaymentResult,
)

log = logging.getLogger(__name__)

# Tolerancia del timestamp del webhook (anti-replay). Khipu manda
# `t=<epoch millis>` en la firma; descartamos mensajes mas viejos.
WEBHOOK_MAX_EDAD_SEGUNDOS = 15 * 60


class KhipuGateway(OnlinePaymentGateway):
    provider = 'khipu'
    nombre_publico = 'Transferencia bancaria'
    subtitulo = 'Pagas desde tu banco con Khipu — sin tarjeta'
    icono = '🏦'
    comision_descripcion = '0,79% por transferencia · sin fee fijo'

    def __init__(self):
        self.api_key = getattr(settings, 'KHIPU_API_KEY', '')
        # "Llave de cobrador" del panel — clave del HMAC de los webhooks.
        self.secret = getattr(settings, 'KHIPU_SECRET', '')
        self.receiver_id = getattr(settings, 'KHIPU_RECEIVER_ID', '')
        self.base_url = getattr(
            settings, 'KHIPU_BASE_URL', 'https://payment-api.khipu.com',
        ).rstrip('/')
        self.mock_mode = not self.api_key
        if self.mock_mode and not settings.DEBUG:
            log.warning(
                'KhipuGateway en MOCK_MODE en prod — falta KHIPU_API_KEY '
                'en .env.',
            )
        if self.api_key and not self.secret:
            log.warning(
                'KHIPU_API_KEY seteada pero falta KHIPU_SECRET (llave de '
                'cobrador) — los webhooks se van a rechazar por firma.',
            )

    # ─── Flujo principal ───────────────────────────────────────────

    def iniciar_pago(self, recibo, return_url):
        if self.mock_mode:
            return self._mock_iniciar_pago(recibo, return_url)

        payload = self._build_payload(recibo, return_url)
        try:
            resp = requests.post(
                f'{self.base_url}/v3/payments',
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise PaymentGatewayError(f'Khipu request error: {exc}') from exc
        if resp.status_code >= 400:
            raise PaymentGatewayError(
                f'Khipu {resp.status_code}: {resp.text[:300]}',
            )
        data = resp.json()
        # Khipu devuelve varias URLs de checkout. `simplified_transfer_url`
        # es la PWA rapida (sin registro); `payment_url` el flujo completo.
        checkout = data.get('simplified_transfer_url') or data.get('payment_url')
        if not checkout or not data.get('payment_id'):
            raise PaymentGatewayError(
                f'Khipu respondio sin payment_url/payment_id: {str(data)[:300]}',
            )
        return OnlinePaymentInit(
            redirect_url=checkout,
            token=data['payment_id'],
            provider=self.provider,
        )

    def confirmar_pago(self, token):
        if self.mock_mode:
            return self._mock_confirmar_pago(token)

        try:
            resp = requests.get(
                f'{self.base_url}/v3/payments/{token}',
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            # Red caida ≠ pago fallido: devolvemos PENDIENTE para que el
            # flujo reintente (webhook o refresh del retorno) en vez de
            # marcar fallido un pago que pudo salir bien.
            return PaymentResult(
                estado=ESTADO_PENDIENTE, provider=self.provider,
                detalle=f'Khipu red error (reintentar): {exc}',
            )
        if resp.status_code >= 400:
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider,
                detalle=f'Khipu {resp.status_code}: {resp.text[:200]}',
            )
        return self._map_estado(resp.json())

    def webhook(self, request):
        """Procesa una notificacion `notify_url` de Khipu (API 3.0).

        Khipu manda el objeto de pago como JSON y firma el body con
        HMAC-SHA256 usando la "llave de cobrador" (KHIPU_SECRET). El
        header es `x-khipu-signature: t=<epoch_ms>,s=<firma base64>` y
        el string firmado es `<t>.<body>`.
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
        """Khipu API 3.0 autentica con el header `x-api-key`."""
        return {
            'x-api-key': self.api_key,
            'Content-Type': 'application/json',
        }

    def _notify_url(self, return_url: str) -> str:
        """URL absoluta del webhook, derivada del origen del return_url.

        No se puede usar `request.build_absolute_uri` aca (no hay request)
        ni un `.replace()` sobre el path (fragil): tomamos scheme+host del
        return_url que ya viene absoluto y le colgamos la ruta real del
        webhook via reverse().
        """
        partes = urlsplit(return_url)
        path = reverse('ecommerce:pago_webhook',
                       kwargs={'gateway': self.provider})
        return urlunsplit((partes.scheme, partes.netloc, path, '', ''))

    def _build_payload(self, recibo, return_url):
        payload = {
            'subject': f'Compra Ideas Boutique #{recibo.pk}',
            # CLP no tiene decimales — Khipu espera el monto como numero.
            'amount': int(recibo.total),
            'currency': 'CLP',
            'transaction_id': f'IBR-{recibo.pk:08d}',
            'custom': str(recibo.pk),
            'body': f'Pedido #{recibo.pk} — Ideas Boutique',
            'return_url': return_url,
            # Si el cliente cancela en Khipu, vuelve al retorno igual:
            # confirmar_pago va a ver status=pending y la pantalla lo
            # muestra como pago no completado (puede reintentar).
            'cancel_url': return_url,
            'notify_url': self._notify_url(return_url),
        }
        if recibo.cliente_email:
            payload['payer_email'] = recibo.cliente_email
        if recibo.cliente_nombre:
            payload['payer_name'] = recibo.cliente_nombre
        return payload

    def _verificar_firma(self, body: bytes, signature_header: str) -> bool:
        if not self.secret or not signature_header:
            return False
        # Header formato `t=<epoch_ms>,s=<firma>` (Khipu 3.0).
        partes = dict(p.strip().split('=', 1)
                      for p in signature_header.split(',') if '=' in p)
        firma_recibida = partes.get('s', '')
        timestamp = partes.get('t', '')
        if not firma_recibida or not timestamp:
            return False

        # Anti-replay: descartar notificaciones muy viejas.
        try:
            edad = abs(time.time() - int(timestamp) / 1000.0)
            if edad > WEBHOOK_MAX_EDAD_SEGUNDOS:
                log.warning('Webhook Khipu con timestamp viejo (%.0fs).', edad)
                return False
        except ValueError:
            return False

        firmable = f'{timestamp}.'.encode('utf-8') + body
        digest = hmac.new(
            self.secret.encode('utf-8'), firmable, hashlib.sha256,
        ).digest()
        # Khipu manda la firma en base64 (ej. `s=GYzpj...dg=`). Aceptamos
        # tambien hex por si el formato cambia entre versiones del panel.
        firma_b64 = base64.b64encode(digest).decode('ascii')
        firma_hex = digest.hex()
        return (
            hmac.compare_digest(firma_b64, firma_recibida)
            or hmac.compare_digest(firma_hex, firma_recibida.lower())
        )

    def _map_estado(self, data: dict) -> PaymentResult:
        """Khipu status: `pending` (esperando pago), `verifying`
        (transferencia hecha, conciliando) y `done` (acreditado).
        `status_detail` agrega el motivo fino cuando aplica.
        """
        estado_khipu = (data.get('status') or '').lower()
        detalle_khipu = (data.get('status_detail') or '').lower()

        mapping = {
            'done':      ESTADO_PAGADO,
            'verifying': ESTADO_PENDIENTE,
            'pending':   ESTADO_PENDIENTE,
        }
        estado = mapping.get(estado_khipu, ESTADO_PENDIENTE)

        # status_detail puede degradar un estado: un pago devuelto o
        # marcado como abuso NO debe quedar como pagado.
        if detalle_khipu in ('rejected_by_payer', 'marked_as_abuse'):
            estado = ESTADO_FALLIDO
        elif detalle_khipu == 'reversed':
            estado = ESTADO_CANCELADO

        return PaymentResult(
            estado=estado, provider=self.provider,
            reference=str(data.get('payment_id')
                          or data.get('transaction_id') or ''),
            detalle=f'Khipu status={estado_khipu}'
                    + (f' detail={detalle_khipu}' if detalle_khipu else ''),
        )

    def _parsear_recibo_pk(self, transaction_id: str) -> int | None:
        if not transaction_id.startswith('IBR-'):
            return None
        try:
            return int(transaction_id[4:])
        except ValueError:
            return None

    # ─── Modo mock (sin KHIPU_API_KEY) ─────────────────────────────

    def _mock_iniciar_pago(self, recibo, return_url):
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
