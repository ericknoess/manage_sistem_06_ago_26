from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auditoria'
    verbose_name = 'Auditoría (audit trail GxP)'

    def ready(self):
        from . import signals  # noqa: F401  (registra inicios y cierres de sesión)
