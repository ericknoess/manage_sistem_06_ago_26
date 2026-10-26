from django.apps import AppConfig


class DatosProcesoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'datos_proceso'
    verbose_name = 'Datos de proceso'

    def ready(self):
        from . import signals  # noqa: F401  (invalida las series preparadas al cambiar un lote)
