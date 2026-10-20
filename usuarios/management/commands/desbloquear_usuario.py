# Rescate: desbloquea una cuenta bloqueada por intentos fallidos (por ejemplo, el único administrador).
#   python manage.py desbloquear_usuario <usuario>

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from auditoria.models import RegistroAuditoria
from usuarios.firmas import desbloquear_usuario


class Command(BaseCommand):
    help = 'Desbloquea una cuenta bloqueada por intentos fallidos de login o firma.'

    def add_arguments(self, parser):
        parser.add_argument('usuario')

    def handle(self, *args, **opciones):
        usuario = get_user_model().objects.filter(username=opciones['usuario']).first()
        if usuario is None:
            raise CommandError(f"No existe el usuario '{opciones['usuario']}'.")
        desbloquear_usuario(usuario)
        RegistroAuditoria.objects.create(
            actor='Consola (manage.py)', categoria='SESION', accion='CUENTA_DESBLOQUEADA',
            descripcion=f"Cuenta {usuario.get_username()} desbloqueada desde la consola",
            objeto_tipo='user', objeto_id=str(usuario.pk),
        )
        self.stdout.write(self.style.SUCCESS(f"Cuenta '{usuario.get_username()}' desbloqueada."))
