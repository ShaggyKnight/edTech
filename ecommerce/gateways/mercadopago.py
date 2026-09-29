"""Mercado Pago — Checkout Pro (API REST, REAL).

Mercado Pago es la billetera + pasarela más usada en Chile. Con Checkout
Pro el cliente es redirigido al entorno de Mercado Pago, paga con su
saldo, tarjeta de crédito/débito o cuotas, y vuelve a la tienda. Nosotros
NUNCA tocamos datos de tarjeta (PCI queda del lado de Mercado Pago).

Flujo (idéntico en forma al de Khipu):
  1. iniciar_pago  → POST /checkout/preferences → devuelve `init_point`
     (URL de checkout) al que redirigimos. El `external_reference` =
     "IBR-<pk>-<llave aleatoria>" es también el token del pedido: con él
     se reconoce el recibo después y arma la URL pública del pedido, así
     que NO puede ser adivinable (esa página muestra nombre, email y RUT).
  2. Cliente paga en Mercado Pago y vuelve al return_url.
  3. confirmar_pago(token) → GET /v1/payments/search?external_reference=…
     para leer el estado final del pago. Puede haber varios intentos: tras
     un rechazo, Checkout Pro deja pagar con otro medio en la misma
     preferencia — un intento aprobado manda.
  4. webhook → Mercado Pago avisa server-to-server con el payment_id;
     lo consultamos y aplicamos el resultado (cubre el caso de que el
     cliente cierre el browser antes de volver).

Estado: INTEGRACIÓN REAL. Sin MERCADOPAGO_ACCESS_TOKEN: en dev/tests cae
a modo mock (simulador local), igual que Khipu; en prod el gateway se
desactiva (ver ECOMMERCE_PERMITIR_SIMULADOR).

Docs: https://www.mercadopago.cl/developers/es/docs/checkout-pro/landing

Settings esperados:
    MERCADOPAGO_ACCESS_TOKEN=...    # "Access Token" del panel (Bearer). El
                                    # ambiente (prueba/producción) lo define
                                    # cuál uses: las credenciales de PRUEBA y de
                                    # PRODUCCIÓN ambas empiezan con APP_USR-.
    MERCADOPAGO_WEBHOOK_SECRET=...  # "Clave secreta" para validar la firma
                                    # x-signature de los webhooks.
    MERCADOPAGO_PUBLIC_KEY=...      # Public Key (informativo; sirve para el
                                    # SDK de frontend si algún día se usa).
    MERCADOPAGO_BASE_URL=https://api.mercadopago.com
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests
from django.conf import settings
from django.urls import reverse

from ecommerce.gateways.base import (
    OnlinePaymentGateway, OnlinePaymentInit, WebhookResult, simulador_permitido,
)
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
    PaymentGatewayError, PaymentResult,
)

log = logging.getLogger(__name__)

# Tolerancia del timestamp del webhook (anti-replay). Mercado Pago manda
# `ts=<epoch_segundos>` en la firma; descartamos avisos más viejos.
WEBHOOK_MAX_EDAD_SEGUNDOS = 15 * 60

# Prefijo del external_reference: "IBR-00000123-<llave>". El número de
# pedido lo hace legible en el panel de Mercado Pago; la llave aleatoria
# lo hace imposible de adivinar.
_REF_PREFIX = 'IBR-'


class MercadoPagoGateway(OnlinePaymentGateway):
    provider = 'mercadopago'
    nombre_publico = 'Mercado Pago'
    subtitulo = 'Billetera, tarjetas de crédito/débito y cuotas'
    icono = '💳'
    comision_descripcion = '≈3% + IVA · la plata cae en tu cuenta Mercado Pago'

    def __init__(self):
        self.access_token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', '')
        self.webhook_secret = getattr(settings, 'MERCADOPAGO_WEBHOOK_SECRET', '')
        self.base_url = getattr(
            settings, 'MERCADOPAGO_BASE_URL', 'https://api.mercadopago.com',
        ).rstrip('/')
        self.mock_mode = not self.access_token
        if self.mock_mode and not simulador_permitido():
            # Sin token en prod el gateway se desactiva (el registry lo
            # salta) en vez de caer al simulador y aprobar sin cobrar.
            raise PaymentGatewayError(
                'Mercado Pago sin MERCADOPAGO_ACCESS_TOKEN en .env — gateway desactivado.',
            )
        if self.access_token and not self.webhook_secret:
            log.warning(
                'MERCADOPAGO_ACCESS_TOKEN seteado pero falta '
                'MERCADOPAGO_WEBHOOK_SECRET — los webhooks se rechazan por firma.',
            )

    # ─── Flujo principal ───────────────────────────────────────────

    def iniciar_pago(self, recibo, return_url):
        if self.mock_mode:
            return self._mock_iniciar_pago(recibo, return_url)

        referencia = self._external_reference(recibo)
        payload = self._build_preference(recibo, return_url, referencia)
        try:
            resp = requests.post(
                f'{self.base_url}/checkout/preferences',
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise PaymentGatewayError(f'Mercado Pago request error: {exc}') from exc
        if resp.status_code >= 400:
            raise PaymentGatewayError(
                f'Mercado Pago {resp.status_code}: {resp.text[:300]}',
            )
        data = resp.json()
        # init_point = URL del checkout. Con el modelo actual de Mercado
        # Pago el ambiente (prueba vs producción) lo determina el Access
        # Token — las credenciales de PRUEBA y de PRODUCCIÓN ambas empiezan
        # con APP_USR-. sandbox_init_point queda como fallback para tokens
        # legacy TEST-.
        checkout = data.get('init_point') or data.get('sandbox_init_point')
        if not checkout:
            raise PaymentGatewayError(
                f'Mercado Pago respondió sin init_point: {str(data)[:300]}',
            )
        # El token es nuestro external_reference (no el id de preferencia):
        # confirmar_pedido lo usa para encontrar el recibo, y confirmar_pago
        # para buscar el pago en Mercado Pago.
        return OnlinePaymentInit(
            redirect_url=checkout,
            token=referencia,
            provider=self.provider,
        )

    def confirmar_pago(self, token):
        if self.mock_mode:
            return self._mock_confirmar_pago(token)

        try:
            resp = requests.get(
                f'{self.base_url}/v1/payments/search',
                params={
                    'external_reference': token,
                    'sort': 'date_created',
                    'criteria': 'desc',
                },
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            # Red caída ≠ pago fallido: PENDIENTE para reintentar por
            # webhook o refresh del retorno (no marcamos fallido a ciegas).
            return PaymentResult(
                estado=ESTADO_PENDIENTE, provider=self.provider,
                detalle=f'Mercado Pago red error (reintentar): {exc}',
            )
        if resp.status_code >= 400:
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider,
                detalle=f'Mercado Pago {resp.status_code}: {resp.text[:200]}',
            )
        pagos = (resp.json() or {}).get('results') or []
        if not pagos:
            # Todavía no hay pago (cliente abandonó o volvió sin pagar).
            return PaymentResult(
                estado=ESTADO_PENDIENTE, provider=self.provider,
                detalle='Mercado Pago sin pagos para el pedido aún',
            )
        # Puede haber varios intentos (tras un rechazo, Checkout Pro deja
        # pagar con otro medio en la misma preferencia). Uno aprobado manda;
        # si no, uno en proceso deja el pedido pendiente; si no, vale el
        # último intento (vienen ordenados del más nuevo al más viejo).
        resultados = [self._map_estado(p) for p in pagos]
        for estado in (ESTADO_PAGADO, ESTADO_PENDIENTE):
            for resultado in resultados:
                if resultado.estado == estado:
                    return resultado
        return resultados[0]

    def webhook(self, request):
        """Procesa una notificación de Mercado Pago (tipo `payment`).

        Mercado Pago avisa con `?type=payment&data.id=<payment_id>` y firma
        con HMAC-SHA256 en el header `x-signature: ts=<epoch>,v1=<hash>`.
        El manifest firmado es `id:<data.id>;request-id:<x-request-id>;ts:<ts>;`.
        Solo trae el id — hay que consultar el pago para saber el estado.
        """
        tipo = request.GET.get('type') or request.GET.get('topic') or ''
        data_id = request.GET.get('data.id') or request.GET.get('id') or ''
        if not data_id:
            # Algunos avisos mandan el id en el body en vez del query string.
            try:
                cuerpo = json.loads(request.body or b'{}')
                data_id = str((cuerpo.get('data') or {}).get('id') or
                              cuerpo.get('id') or '')
                tipo = tipo or cuerpo.get('type') or cuerpo.get('action') or ''
            except (json.JSONDecodeError, AttributeError):
                pass

        if 'payment' not in tipo:
            # merchant_order u otros topics que Checkout Pro también manda:
            # los reconocemos con 200 (handled=True) sin hacer nada — el
            # estado real lo sacamos de la notificación de pago. Devolver
            # 401 acá haría que Mercado Pago reintente y los marque fallidos.
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=True,
                detalle=f'Topic ignorado (200): {tipo!r}',
            )
        if not data_id:
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=False,
                detalle='Webhook sin data.id',
            )

        if not self._verificar_firma(request, data_id):
            log.warning('Webhook Mercado Pago con firma inválida — ignorado.')
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=False,
                detalle='Firma inválida',
            )

        try:
            resp = requests.get(
                f'{self.base_url}/v1/payments/{data_id}',
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=False,
                detalle=f'No se pudo consultar el pago: {exc}',
            )
        if resp.status_code >= 400:
            return WebhookResult(
                recibo_pk=None, payment_result=None, handled=False,
                detalle=f'Mercado Pago {resp.status_code} al consultar pago',
            )

        pago = resp.json()
        recibo_pk = self._recibo_pk(pago.get('external_reference') or '')
        result = self._map_estado(pago)
        log.info(
            'Webhook Mercado Pago procesado: payment_id=%s recibo=%s estado=%s',
            data_id, recibo_pk, result.estado,
        )
        return WebhookResult(
            recibo_pk=recibo_pk, payment_result=result, handled=True,
        )

    # ─── Helpers internos ──────────────────────────────────────────

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def _external_reference(self, recibo) -> str:
        """Referencia del pedido en Mercado Pago = token de su URL pública.

        Antes era "IBR-<pk>" a secas: cambiando el número se recorrían los
        pedidos de otros clientes en /tienda/pedido/<token>/. Ahora lleva
        la llave de idempotencia del recibo (uuid4, aleatoria).
        """
        llave = recibo.payment_idempotency_key or str(uuid.uuid4())
        return f'{_REF_PREFIX}{recibo.pk:08d}-{llave.replace("-", "")}'

    def _notify_url(self, return_url: str) -> str:
        """URL absoluta del webhook, derivada del origen del return_url
        (mismo truco que Khipu: no hay request acá para build_absolute_uri)."""
        partes = urlsplit(return_url)
        path = reverse('ecommerce:pago_webhook',
                       kwargs={'gateway': self.provider})
        return urlunsplit((partes.scheme, partes.netloc, path, '', ''))

    def _build_preference(self, recibo, return_url, referencia):
        preference = {
            'items': [{
                'title': f'Compra Ideas Boutique #{recibo.pk}',
                'quantity': 1,
                # CLP no tiene decimales — unit_price va como entero.
                'unit_price': int(recibo.total),
                'currency_id': 'CLP',
            }],
            'external_reference': referencia,
            'back_urls': {
                'success': return_url,
                'pending': return_url,
                'failure': return_url,
            },
            'statement_descriptor': 'IDEAS BOUTIQUE',
        }
        # notification_url (webhook) y auto_return: Mercado Pago exige URLs
        # públicas y válidas para ambos — con http://localhost los rechaza.
        # Se agregan solo cuando el retorno es HTTPS (prod). En local se
        # omiten para poder probar el flujo completo: el pago igual se
        # confirma por la búsqueda al volver (confirmar_pago).
        if return_url.startswith('https://'):
            preference['notification_url'] = self._notify_url(return_url)
            preference['auto_return'] = 'approved'
        payer = {}
        if recibo.cliente_email:
            payer['email'] = recibo.cliente_email
        if recibo.cliente_nombre:
            payer['name'] = recibo.cliente_nombre
        if payer:
            preference['payer'] = payer
        return preference

    def _verificar_firma(self, request, data_id: str) -> bool:
        if not self.webhook_secret:
            return False
        firma = request.headers.get('X-Signature', '')
        request_id = request.headers.get('X-Request-Id', '')
        if not firma:
            return False
        # Header formato `ts=<epoch>,v1=<hash>`.
        partes = dict(p.strip().split('=', 1)
                      for p in firma.split(',') if '=' in p)
        ts = partes.get('ts', '')
        v1 = partes.get('v1', '')
        if not ts or not v1:
            return False

        # Anti-replay: descartar avisos muy viejos (ts en segundos).
        try:
            edad = abs(time.time() - int(ts))
            if edad > WEBHOOK_MAX_EDAD_SEGUNDOS:
                log.warning('Webhook Mercado Pago con timestamp viejo (%.0fs).', edad)
                return False
        except ValueError:
            return False

        # El manifest usa el data.id en minúsculas si es alfanumérico.
        id_norm = data_id.lower() if data_id.isalnum() else data_id
        manifest = f'id:{id_norm};request-id:{request_id};ts:{ts};'
        digest = hmac.new(
            self.webhook_secret.encode('utf-8'),
            manifest.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(digest, v1)

    def _map_estado(self, pago: dict) -> PaymentResult:
        """Mapea el `status` de un pago Mercado Pago a nuestro estado.

        approved → pagado; pending/in_process/authorized → pendiente;
        rejected → fallido; cancelled/refunded/charged_back → cancelado.
        """
        estado_mp = (pago.get('status') or '').lower()
        detalle_mp = (pago.get('status_detail') or '').lower()

        mapping = {
            'approved':   ESTADO_PAGADO,
            'authorized': ESTADO_PENDIENTE,
            'in_process': ESTADO_PENDIENTE,
            'in_mediation': ESTADO_PENDIENTE,
            'pending':    ESTADO_PENDIENTE,
            'rejected':   ESTADO_FALLIDO,
            'cancelled':  ESTADO_CANCELADO,
            'refunded':   ESTADO_CANCELADO,
            'charged_back': ESTADO_CANCELADO,
        }
        estado = mapping.get(estado_mp, ESTADO_PENDIENTE)

        return PaymentResult(
            estado=estado, provider=self.provider,
            reference=str(pago.get('id') or ''),
            detalle=f'Mercado Pago status={estado_mp}'
                    + (f' detail={detalle_mp}' if detalle_mp else ''),
        )

    def _recibo_pk(self, external_reference: str) -> int | None:
        """external_reference → pk del recibo. Es el token con el que se
        creó la preferencia, guardado en `payment_reference`."""
        if not external_reference:
            return None
        from pos.models import ReciboVenta
        return (
            ReciboVenta.objects
            .filter(canal=ReciboVenta.CANAL_ONLINE,
                    payment_reference=external_reference)
            .values_list('pk', flat=True)
            .first()
        )

    # ─── Modo mock (sin MERCADOPAGO_ACCESS_TOKEN) ──────────────────

    def _mock_iniciar_pago(self, recibo, return_url):
        # En mock el token igual es el external_reference (mismo formato
        # no adivinable), para que confirmar_pedido encuentre el recibo.
        token = self._external_reference(recibo)
        redirect_url = (
            reverse('ecommerce:mock_pago') +
            f'?token={token}&return_url={return_url}&gateway=mercadopago'
        )
        return OnlinePaymentInit(
            redirect_url=redirect_url, token=token, provider=self.provider,
        )

    def _mock_confirmar_pago(self, token):
        if ':fail' in token:
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider,
                detalle='Mock Mercado Pago rechazado',
            )
        if ':cancel' in token:
            return PaymentResult(
                estado=ESTADO_CANCELADO, provider=self.provider,
                detalle='Mock Mercado Pago cancelado',
            )
        return PaymentResult(
            estado=ESTADO_PAGADO, provider=self.provider,
            reference=f'MP-{token}',
            detalle='Mock Mercado Pago aprobado',
        )
