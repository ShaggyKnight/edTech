"""Contrato base que todos los gateways online implementan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from pos.payments import PaymentResult

if TYPE_CHECKING:
    from django.http import HttpRequest
    from pos.models import ReciboVenta


@dataclass
class OnlinePaymentInit:
    """Resultado de iniciar un pago online.

    El cliente debe ser redirigido a `redirect_url`. Cuando vuelva al
    sitio, la vista de retorno usa `token` para consultar el estado
    final via `confirmar_pago(token)`.
    """
    redirect_url: str
    token: str
    provider: str


@dataclass
class WebhookResult:
    """Resultado del procesamiento de un webhook del gateway.

    `recibo_pk` permite asociar el evento al ReciboVenta. `payment_result`
    es el estado nuevo (pagado, fallido, etc.). El gateway es responsable
    de validar la firma/HMAC del webhook antes de devolver un resultado
    valido.
    """
    recibo_pk: Optional[int]
    payment_result: Optional[PaymentResult]
    handled: bool = True   # False = ignoramos (firma invalida, evento irrelevante)
    detalle: str = ''


class OnlinePaymentGateway:
    """Interfaz base para pasarelas asincronicas (redirect + callback)."""

    # Nombre interno (snake_case). Usado en setting y URLs de webhook.
    provider: str = ''

    # Nombre visible para el cliente en el checkout ("Tarjeta", "Transferencia").
    nombre_publico: str = ''

    # Subtitulo opcional para mostrar bajo el nombre (ej. "Visa, Mastercard").
    subtitulo: str = ''

    # Icono SVG/emoji opcional para el radio button.
    icono: str = ''

    # Comision aproximada para mostrar al admin (no al cliente).
    comision_descripcion: str = ''

    def iniciar_pago(self, recibo: 'ReciboVenta',
                     return_url: str) -> OnlinePaymentInit:
        """Inicia la transaccion en el proveedor.

        Devuelve la URL a la que hay que redirigir al cliente y el token
        que despues se usa para consultar el estado.
        """
        raise NotImplementedError

    def confirmar_pago(self, token: str) -> PaymentResult:
        """Consulta el estado final del pago (cliente volvio al sitio).

        Idempotente: si se llama varias veces con el mismo token, debe
        devolver el mismo resultado.
        """
        raise NotImplementedError

    def webhook(self, request: 'HttpRequest') -> WebhookResult:
        """Procesa un webhook del gateway. Default: no-op (gateways que
        solo usan retorno por redirect no necesitan implementarlo).
        """
        return WebhookResult(recibo_pk=None, payment_result=None,
                             handled=False, detalle='Gateway sin webhook.')
