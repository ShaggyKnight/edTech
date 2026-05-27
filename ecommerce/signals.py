"""Signals del ecommerce.

Hoy:
  - StockTienda.post_save -> si la variante volvio a tener stock > 0 y
    hay avisos pendientes para esa variante, los manda y los marca como
    notificados.

Filosofia: el signal hace lo MINIMO. La logica de validacion (feature
flag, build del unsub_url, etc.) la delega a ecommerce.emails.

Failure mode: si el envio falla (SMTP caido, template roto, etc), el
aviso queda en estado pendiente y se vuelve a intentar en la proxima
actualizacion de stock. NO bloquea el guardado del StockTienda — la
operacion de bodega es prioritaria.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

log = logging.getLogger(__name__)


@receiver(post_save, sender='bodega.StockTienda')
def _disparar_avisos_si_vuelve_stock(sender, instance, **kwargs):
    """Cuando un StockTienda se guarda con cantidad > 0 para una variante
    que tiene avisos pendientes, mandamos los emails.

    No filtramos por "ANTES estaba en 0" porque:
      1) Es info que requeriria leer el row previo (consulta extra).
      2) Si un aviso quedo pendiente y la variante ya tenia stock, igual
         queremos despachar el aviso — el cliente esta esperando.
      3) Una vez enviado, el aviso queda con notificado=now y no se
         dispara de nuevo aunque el signal se vuelva a invocar.
    """
    # Solo notificamos cuando la variante esta en la tienda que surte
    # la venta online. Si tienen multi-tienda, los movimientos de stock
    # en otras sucursales NO disparan emails.
    tienda_online_id = getattr(settings, 'ECOMMERCE_TIENDA_ID', None) or 0
    if tienda_online_id and instance.tienda_id != int(tienda_online_id):
        return

    if instance.cantidad <= 0:
        return
    if instance.variante_id is None:
        return  # stock por producto directo, no nos atane

    # Lazy import: evitamos circular (apps.py carga signals antes que
    # los modelos esten 100% listos en el registry).
    from .emails import enviar_stock_disponible
    from .models import AvisoStockReposicion

    avisos = list(
        AvisoStockReposicion.objects
        .filter(
            variante_id=instance.variante_id,
            notificado__isnull=True,
            cancelado__isnull=True,
        )
    )
    if not avisos:
        return

    site_url = (getattr(settings, 'SITE_URL', '') or 'https://ideasboutique.cl').rstrip('/')
    now = timezone.now()
    enviados = 0

    for aviso in avisos:
        unsub_url = site_url + reverse('ecommerce:avisame_cancelar', args=[aviso.token])
        ok = False
        try:
            ok = enviar_stock_disponible(
                instance.variante,
                aviso.email,
                unsub_url=unsub_url,
            )
        except Exception:  # noqa: BLE001
            log.exception(
                'Aviso #%s: fallo enviar a %s', aviso.pk, aviso.email,
            )
        if ok:
            aviso.notificado = now
            aviso.save(update_fields=['notificado'])
            enviados += 1

    if enviados:
        log.info(
            'Aviso reposicion: variante=%s, enviados=%s/%s',
            instance.variante_id, enviados, len(avisos),
        )
