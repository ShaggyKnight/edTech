from django.apps import AppConfig


class EcommerceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ecommerce'

    def ready(self):
        # Carga el signal post_save de StockTienda para disparar emails
        # de "vuelve la talla". Importar registra el @receiver.
        from . import signals  # noqa: F401
