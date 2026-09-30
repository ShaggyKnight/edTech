"""Aplica la politica de conservacion de datos (Ley 21.719).

    djmanage purgar_datos_vencidos            # muestra lo que haria
    djmanage purgar_datos_vencidos --aplicar  # lo hace

Pensado para correr una vez al mes por cron. Los plazos viven en
settings (RETENCION_*) y son los mismos que se publican en /privacidad/:

- Pedidos no pagados (pendientes, rechazados, anulados): se anonimizan.
- Pedidos pagados (y cobrados sin stock, ya devueltos): se anonimizan los
  datos de contacto; la venta (productos y montos) queda para la
  contabilidad. Nunca un pedido online pagado que aun no se entrega.
- Facturas (DTE 33): no se tocan, la ley exige los datos del comprador.
- Avisos de reposicion cerrados o sin respuesta: se eliminan.
- Registros de intentos de acceso (django-axes) y sesiones vencidas: se
  eliminan.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from ecommerce.models import AvisoStockReposicion
from ecommerce.privacidad import DTE_FACTURA, anonimizar_recibos
from pos.models import ReciboVenta

R = ReciboVenta


class Command(BaseCommand):
    help = ('Aplica los plazos de conservacion de datos personales (Ley 21.719). '
            'Sin --aplicar solo muestra lo que haria.')

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true',
                            help='Anonimiza y borra. Sin esto solo muestra los conteos.')

    def handle(self, aplicar=False, **opciones):
        ahora = timezone.now()

        def limite(setting):
            return ahora - timedelta(days=getattr(settings, setting))

        con_datos = ~Q(cliente_nombre='', cliente_email='', cliente_telefono='',
                       cliente_direccion='', cliente_rut='', cliente_usuario__isnull=True)
        no_pagados = R.objects.filter(
            Q(estado__in=[R.ESTADO_PENDIENTE, R.ESTADO_CANCELADO])
            | Q(estado=R.ESTADO_FALLIDO, pago_recibido_en__isnull=True),
            creado__lt=limite('RETENCION_PEDIDOS_NO_PAGADOS_DIAS'),
        )
        pagados = R.objects.filter(
            Q(estado=R.ESTADO_PAGADO)
            | Q(estado=R.ESTADO_FALLIDO, pago_recibido_en__isnull=False),
            creado__lt=limite('RETENCION_PEDIDOS_PAGADOS_DIAS'),
        ).exclude(canal=R.CANAL_ONLINE, estado=R.ESTADO_PAGADO, despachado_en__isnull=True)
        recibos = R.objects.filter(
            Q(pk__in=no_pagados.values('pk')) | Q(pk__in=pagados.values('pk')),
        ).filter(con_datos).exclude(dte_tipo=DTE_FACTURA)

        limite_cerrados = limite('RETENCION_AVISOS_CERRADOS_DIAS')
        avisos = AvisoStockReposicion.objects.filter(
            Q(notificado__lt=limite_cerrados)
            | Q(cancelado__lt=limite_cerrados)
            | Q(notificado__isnull=True, cancelado__isnull=True,
                creado__lt=limite('RETENCION_AVISOS_PENDIENTES_DIAS'))
        )

        limite_accesos = limite('RETENCION_REGISTROS_ACCESO_DIAS')
        registros = [
            ('intentos fallidos de acceso', AccessAttempt.objects.filter(attempt_time__lt=limite_accesos)),
            ('historial de fallos de acceso', AccessFailureLog.objects.filter(attempt_time__lt=limite_accesos)),
            ('historial de accesos', AccessLog.objects.filter(attempt_time__lt=limite_accesos)),
            ('sesiones vencidas', Session.objects.filter(expire_date__lt=ahora)),
        ]

        self.stdout.write('Datos vencidos según la política de conservación:')
        self.stdout.write(f'  pedidos a anonimizar: {recibos.count()}')
        self.stdout.write(f'  avisos de reposición a eliminar: {avisos.count()}')
        for nombre, qs in registros:
            self.stdout.write(f'  {nombre} a eliminar: {qs.count()}')

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'SIMULACIÓN: no se cambió nada. Repite con --aplicar para hacerlo.'))
            return

        with transaction.atomic():
            anonimizados = anonimizar_recibos(recibos)
            borrados_avisos = avisos.delete()[0]
            borrados = {nombre: qs.delete()[0] for nombre, qs in registros}
        self.stdout.write(self.style.SUCCESS(
            f'Listo: {anonimizados} pedidos anonimizados, {borrados_avisos} avisos eliminados, '
            + ', '.join(f'{n} {nombre}' for nombre, n in borrados.items()) + '.'
        ))
