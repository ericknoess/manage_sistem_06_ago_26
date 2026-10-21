from django.apps import AppConfig


def _cerrar_terminal_operador(sender, request, user, **kwargs):
    """Al entrar un usuario web se cierra la terminal del operador en esa sesión:
    cada sesión tiene una sola identidad, para que la firma y la bitácora no se mezclen."""
    if request is not None and hasattr(request, 'session'):
        request.session.pop('operador_id', None)


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'
    verbose_name = 'Usuarios y roles'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in
        user_logged_in.connect(_cerrar_terminal_operador, dispatch_uid='usuarios_cerrar_terminal_operador')
