# Ofertas por familia completa y por toda la tienda (lanzamiento de la
# tienda online). Se elimina el constraint `oferta_tiene_target`: una
# oferta sin producto, variante ni familia aplica a TODA la tienda.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0012_familia_umbral_stock_bajo'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='oferta',
            name='oferta_tiene_target',
        ),
        migrations.AddField(
            model_name='oferta',
            name='familia',
            field=models.ForeignKey(
                blank=True,
                help_text='Descuento a TODOS los productos de la familia. '
                          'Sin familia, producto ni variante = toda la tienda.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='ofertas',
                to='catalogo.familia',
            ),
        ),
    ]
