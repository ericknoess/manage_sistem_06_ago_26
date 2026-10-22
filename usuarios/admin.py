# usuarios/admin.py — Alta de usuarios y asignación de roles desde el admin de Django.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .firmas import desbloquear_usuario
from .models import Perfil


class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    autocomplete_fields = ('operador',)
    readonly_fields = ('intentos_fallidos', 'bloqueado', 'bloqueado_en')
    verbose_name_plural = 'Perfil (puesto y registro en el roster)'


class UsuarioAdmin(UserAdmin):
    inlines = (PerfilInline,)
    list_display = ('username', 'first_name', 'last_name', 'roles', 'registro_roster', 'is_active', 'bloqueada', 'last_login')
    list_filter = ('groups', 'is_active', 'is_superuser', 'perfil__bloqueado')
    actions = ['desbloquear_cuentas']

    @admin.display(description='Bloqueada', boolean=True)
    def bloqueada(self, obj):
        return bool(getattr(getattr(obj, 'perfil', None), 'bloqueado', False))

    @admin.action(description='Desbloquear cuentas (intentos fallidos)')
    def desbloquear_cuentas(self, request, queryset):
        from auditoria.services import registrar
        bloqueadas = [u for u in queryset if self.bloqueada(u)]
        for usuario in bloqueadas:
            desbloquear_usuario(usuario)
            registrar(request, 'SESION', 'CUENTA_DESBLOQUEADA', f"Cuenta {usuario.get_username()} desbloqueada", objeto=usuario)
        self.message_user(request, f"{len(bloqueadas)} cuenta(s) desbloqueada(s).")

    @admin.display(description='Registro en el roster')
    def registro_roster(self, obj):
        # Sin registro ligado, la persona no puede usar en la tablet los permisos de su usuario web (ej. surtir)
        operador = getattr(getattr(obj, 'perfil', None), 'operador', None)
        return f"{operador.codigo_empleado} · {operador.nombre}" if operador else '—'

    @admin.display(description='Roles')
    def roles(self, obj):
        return ', '.join(obj.groups.order_by('name').values_list('name', flat=True)) or ('Administrador' if obj.is_superuser else '—')


admin.site.unregister(User)
admin.site.register(User, UsuarioAdmin)
