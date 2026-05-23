"""Gateway mock para dev y tests.

Redirige a una vista interna que simula la pasarela con botones
"Aprobar / Rechazar / Cancelar". No toca red. Tokens con sufijos
`:fail` o `:cancel` resuelven al estado correspondiente.
"""

from __future__ import annotations

from django.urls import reverse

from ecommerce.gateways.base import OnlinePaymentGateway, OnlinePaymentInit
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO,
    PaymentResult,
)


class MockOnlineGateway(OnlinePaymentGateway):
    provider = 'mock'
    nombre_publico = 'Mock (dev only)'
    subtitulo = 'Pasarela simulada — no toca red'
    icono = '🧪'
    comision_descripcion = 'N/A (mock)'

    def iniciar_pago(self, recibo, return_url):
        token = recibo.payment_idempotency_key or f'MOCK-{recibo.pk}'
        redirect_url = (
            reverse('ecommerce:mock_pago') +
            f'?token={token}&return_url={return_url}'
        )
        return OnlinePaymentInit(
            redirect_url=redirect_url, token=token, provider=self.provider,
        )

    def confirmar_pago(self, token):
        if token.endswith(':fail'):
            return PaymentResult(
                estado=ESTADO_FALLIDO, provider=self.provider,
                detalle='Mock rechazo',
            )
        if token.endswith(':cancel'):
            return PaymentResult(
                estado=ESTADO_CANCELADO, provider=self.provider,
                detalle='Mock cancelado',
            )
        return PaymentResult(
            estado=ESTADO_PAGADO, provider=self.provider, reference=token,
            detalle='Cobro simulado (MockOnlineGateway)',
        )
