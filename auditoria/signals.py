# auditoria/signals.py — Inicios de sesión, cierres e intentos fallidos.

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import RegistroAuditoria
from .services import _ip, registrar


@receiver(user_logged_in)
def sesion_iniciada(sender, request, user, **kwargs):
    registrar(request, 'SESION', 'LOGIN', f"Inicio de sesión de {user.get_username()}", objeto=user)


@receiver(user_logged_out)
def sesion_cerrada(sender, request, user, **kwargs):
    if user is not None:
        registrar(request, 'SESION', 'LOGOUT', f"Cierre de sesión de {user.get_username()}", objeto=user)


@receiver(user_login_failed)
def sesion_fallida(sender, credentials, request=None, **kwargs):
    usuario = (credentials or {}).get('username', '')
    RegistroAuditoria.objects.create(
        actor=usuario[:150] or 'Desconocido', ip=_ip(request), categoria='SESION', accion='LOGIN_FALLIDO',
        descripcion=f"Intento de inicio de sesión fallido para '{usuario}'",
    )
