"""Emisión de Documentos Tributarios Electrónicos (DTE) al SII.

Tres piezas:

- `DteEmissor`: interfaz que toma un `ReciboVenta` ya pagado y devuelve
  un `DteResult` con el folio, el XML del timbre electrónico y la URL al
  PDF que el SII expone (cuando el servicio lo provee).
- `MockDteEmissor`: implementación de desarrollo. Genera folios secuenciales
  y un XML placeholder. Sirve para testear el flujo sin credenciales reales.
- `OpenFacturaEmissor`: adapter para OpenFactura de Haulmer (api.haulmer.com).
  Necesita `OPENFACTURA_API_KEY` y `OPENFACTURA_RUT_EMISOR` configurados.

Por defecto se usa `mock` (no llama a internet, no requiere setup). En
producción setear `DTE_EMISSOR=openfactura` en `.env`.

La emisión se invoca desde `pos.services.procesar_venta` y
`ecommerce.services.confirmar_pedido` después de que el pago sea exitoso.
Si la emisión falla, NO se rompe la venta — se loggea el error y el dueño
puede reintentar manualmente desde el admin (la venta queda pagada y el
recibo, sin folio, conserva todos los datos para reemitir).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from pos.models import ReciboVenta

log = logging.getLogger(__name__)


@dataclass
class DteResult:
    folio: str
    timbre_xml: str = ''
    url_pdf: str = ''
    raw: dict = field(default_factory=dict)


class DteEmissorError(Exception):
    """El servicio de emisión rechazó o falló al emitir el DTE."""


class DteEmissor(Protocol):
    provider: str

    def emitir(self, recibo: ReciboVenta) -> DteResult:  # pragma: no cover
        ...


# ----------------------------------------------------------------------------
# Mock para desarrollo y tests
# ----------------------------------------------------------------------------

class MockDteEmissor:
    """Emisor de juguete: genera folios determinísticos y XML placeholder."""
    provider = 'mock-dte'

    def emitir(self, recibo: ReciboVenta) -> DteResult:
        folio = f'M{recibo.pk:08d}'
        return DteResult(
            folio=folio,
            timbre_xml=f'<TED version="1.0"><DD>mock-{folio}</DD></TED>',
            url_pdf='',  # mock no genera PDF
            raw={'mock': True, 'recibo_id': recibo.pk},
        )


# ----------------------------------------------------------------------------
# OpenFactura (Haulmer) — adapter real
# ----------------------------------------------------------------------------

class OpenFacturaEmissor:
    """Emisor contra OpenFactura de Haulmer.

    Doc: https://developers.haulmer.com/docs/openfactura

    Endpoint principal:
        POST {base_url}/v2/dte/document
    Headers:
        apikey: <OPENFACTURA_API_KEY>
        Content-Type: application/json
    Body (resumen): tipo de DTE, RUT emisor, RUT receptor, items, totales.

    Esta implementación es el esqueleto: arma el payload desde el recibo,
    pero usa `requests` lazy para no agregar la dependencia hard al proyecto
    si nadie la necesita en dev. Se activa con `DTE_EMISSOR=openfactura`.
    """
    provider = 'openfactura'

    def __init__(self):
        self.api_key = getattr(settings, 'OPENFACTURA_API_KEY', '')
        self.base_url = getattr(
            settings, 'OPENFACTURA_BASE_URL', 'https://api.haulmer.com'
        ).rstrip('/')
        self.rut_emisor = getattr(settings, 'OPENFACTURA_RUT_EMISOR', '')
        if not self.api_key or not self.rut_emisor:
            raise DteEmissorError(
                'OpenFactura no configurado: definir OPENFACTURA_API_KEY y '
                'OPENFACTURA_RUT_EMISOR en el entorno.'
            )

    def emitir(self, recibo: ReciboVenta) -> DteResult:
        try:
            import requests  # type: ignore  # lazy import
        except ImportError as exc:
            raise DteEmissorError(
                'Falta el paquete `requests` para usar OpenFactura. '
                '`pip install requests` o cambiá DTE_EMISSOR=mock.'
            ) from exc

        payload = self._build_payload(recibo)
        url = f'{self.base_url}/v2/dte/document'
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={
                    'apikey': self.api_key,
                    'Content-Type': 'application/json',
                },
                timeout=15,
            )
        except requests.exceptions.RequestException as exc:
            raise DteEmissorError(f'OpenFactura request error: {exc}') from exc

        if resp.status_code >= 400:
            raise DteEmissorError(
                f'OpenFactura HTTP {resp.status_code}: {resp.text[:300]}'
            )

        data = resp.json() if resp.content else {}
        # OpenFactura devuelve algo como:
        # {"folio": "12345", "ted": "<TED ...>", "url_pdf": "https://..."}
        folio = str(data.get('folio') or data.get('Folio') or '')
        if not folio:
            raise DteEmissorError(
                f'OpenFactura no devolvió folio en la respuesta: {data}'
            )
        return DteResult(
            folio=folio,
            timbre_xml=data.get('ted') or data.get('TED') or '',
            url_pdf=data.get('url_pdf') or data.get('UrlPdf') or '',
            raw=data,
        )

    def _build_payload(self, recibo: ReciboVenta) -> dict:
        """Arma el payload mínimo para OpenFactura.

        Doc oficial define un esquema más rico (descuento por línea,
        impuestos adicionales, etc). Para boleta electrónica simple (tipo
        39) basta con: emisor, receptor opcional, items, totales.
        """
        tipo = recibo.dte_tipo or int(getattr(settings, 'TUU_DTE_TIPO', 39))
        detalles = []
        for idx, d in enumerate(recibo.detalles.all(), start=1):
            detalles.append({
                'NroLinDet': idx,
                'NmbItem': d.descripcion[:80],
                'QtyItem': float(d.cantidad),
                'PrcItem': float(d.precio_unitario),
                'MontoItem': float(d.cantidad * d.precio_unitario - d.descuento),
            })
        return {
            'TipoDTE': tipo,
            'Emisor': {'RUTEmisor': self.rut_emisor},
            'Receptor': {
                'RUTRecep': recibo.cliente_rut or '66666666-6',  # genérico boleta
                'RznSocRecep': recibo.cliente_nombre or 'Consumidor final',
            },
            'Detalle': detalles,
            'Totales': {
                'MntNeto': float(recibo.subtotal - recibo.descuento),
                'MntTotal': float(recibo.total),
            },
            'IdempotencyKey': recibo.payment_idempotency_key or str(uuid.uuid4()),
        }


# ----------------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------------

_BUILTIN = {
    'mock': MockDteEmissor,
    'openfactura': OpenFacturaEmissor,
    '': None,  # vacío = no emitir
    'none': None,
}


def get_emissor() -> Optional[DteEmissor]:
    """Devuelve la instancia del emisor activo, o None si está deshabilitado.

    `settings.DTE_EMISSOR` puede ser:
      - 'mock' o 'openfactura' (built-in)
      - dotted path a una clase custom (ej: 'apps.dte.MiEmissor')
      - 'none' o '' para deshabilitar emisión
    """
    raw = (getattr(settings, 'DTE_EMISSOR', 'mock') or '').lower().strip()
    if raw in _BUILTIN:
        cls = _BUILTIN[raw]
        if cls is None:
            return None
        return cls()
    # dotted path
    cls = import_string(raw)
    return cls()


def emitir_si_corresponde(recibo: ReciboVenta) -> Optional[DteResult]:
    """Emite el DTE para un recibo pagado y persiste folio/timbre/url.

    Política de error: NO romper la venta si la emisión falla. Se loggea y
    se devuelve None — el recibo queda pagado pero sin folio, el dueño
    puede reemitir manualmente desde el admin más tarde.
    """
    if recibo.estado != ReciboVenta.ESTADO_PAGADO:
        return None
    if recibo.dte_folio:
        return None  # ya emitido (idempotencia)

    emissor = get_emissor()
    if emissor is None:
        return None

    try:
        result = emissor.emitir(recibo)
    except DteEmissorError as exc:
        log.warning(
            'Emisión DTE falló para recibo #%s (provider=%s): %s',
            recibo.pk, getattr(emissor, 'provider', '?'), exc,
        )
        return None
    except Exception:  # noqa: BLE001 — protección de la venta
        log.exception('Error inesperado emitiendo DTE para recibo #%s', recibo.pk)
        return None

    recibo.dte_folio = result.folio
    recibo.dte_timbre_xml = result.timbre_xml
    recibo.dte_url_pdf = result.url_pdf
    recibo.save(update_fields=[
        'dte_folio', 'dte_timbre_xml', 'dte_url_pdf', 'modificado',
    ])
    log.info(
        'DTE emitido: recibo=#%s folio=%s provider=%s',
        recibo.pk, result.folio, getattr(emissor, 'provider', '?'),
    )
    return result
