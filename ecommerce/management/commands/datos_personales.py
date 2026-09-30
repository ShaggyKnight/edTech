"""Atiende solicitudes de derechos de datos personales (Ley 21.719).

Para clientes que compraron sin cuenta y escriben por correo o WhatsApp
(los que tienen cuenta lo hacen solos desde "Mi perfil"):

    djmanage datos_personales exportar correo@ejemplo.cl > datos.json
    djmanage datos_personales suprimir correo@ejemplo.cl              # simulacion
    djmanage datos_personales suprimir correo@ejemplo.cl --confirmar

Plazo legal para responder: 30 dias corridos (prorrogable una vez por
otros 30). Procedimiento completo en docs/ley_21719.md.
"""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ecommerce.privacidad import datos_de, pedidos_en_curso, suprimir_datos


class Command(BaseCommand):
    help = ('Derechos de datos personales (Ley 21.719): "exportar" muestra en JSON '
            'todo lo que guardamos de un correo; "suprimir" lo elimina/anonimiza '
            '(solo simula, salvo --confirmar).')

    def add_arguments(self, parser):
        parser.add_argument('accion', choices=['exportar', 'suprimir'])
        parser.add_argument('email', help='Correo con el que la persona compro o se registro.')
        parser.add_argument('--confirmar', action='store_true',
                            help='Aplica la supresion. Sin esto solo muestra lo que haria.')

    def handle(self, accion, email, confirmar=False, **opciones):
        email = email.strip().lower()
        usuario = get_user_model().objects.filter(email__iexact=email).first()

        if accion == 'exportar':
            self.stdout.write(json.dumps(datos_de(email, usuario), ensure_ascii=False, indent=2))
            return

        if usuario is not None and (usuario.is_staff or usuario.is_superuser
                                    or usuario.groups.exists()):
            raise CommandError('Ese correo es de una cuenta del equipo: no se elimina por esta vía.')
        en_curso = list(pedidos_en_curso(email, usuario).values_list('pk', flat=True))
        if en_curso:
            raise CommandError(
                f'Tiene pedidos en curso ({", ".join(f"#{pk}" for pk in en_curso)}): '
                f'entrégalos o anúlalos antes de suprimir sus datos.'
            )

        datos = datos_de(email, usuario)
        self.stdout.write(f'Datos de {email}:')
        self.stdout.write(f'  cuenta: {"sí" if datos["cuenta"] else "no"}')
        self.stdout.write(f'  pedidos: {len(datos["pedidos"])} (se anonimizan, salvo facturas)')
        self.stdout.write(f'  avisos de reposición: {len(datos["avisos_de_reposicion"])} (se eliminan)')
        self.stdout.write(f'  reseñas: {len(datos["resenas"])} (se eliminan)')

        if not confirmar:
            self.stdout.write(self.style.WARNING(
                'SIMULACIÓN: no se cambió nada. Repite con --confirmar para aplicarlo.'))
            return

        resumen = suprimir_datos(email, usuario)
        self.stdout.write(self.style.SUCCESS(
            f'Listo: cuenta eliminada={resumen["cuenta_eliminada"]}, '
            f'pedidos anonimizados={resumen["pedidos_anonimizados"]}, '
            f'facturas conservadas={resumen["facturas_conservadas"]}, '
            f'avisos eliminados={resumen["avisos_eliminados"]}, '
            f'reseñas eliminadas={resumen["resenas_eliminadas"]}.'
        ))
