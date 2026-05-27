from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Cargar el signal post_save que crea PerfilUsuario para cada
        # User nuevo. Importar models registra el @receiver.
        from . import models  # noqa: F401
