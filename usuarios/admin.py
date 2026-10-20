# usuarios/admin.py — Alta de usuarios y asignación de roles desde el admin de Django.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Perfil


class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    autocomplete_fields = ('operador',)
    verbose_name_plural = 'Perfil (puesto y registro en el roster)'


class UsuarioAdmin(UserAdmin):
    inlines = (PerfilInline,)
    list_display = ('username', 'first_name', 'last_name', 'roles', 'is_active', 'last_login')
    list_filter = ('groups', 'is_active', 'is_superuser')

    @admin.display(description='Roles')
    def roles(self, obj):
        return ', '.join(obj.groups.order_by('name').values_list('name', flat=True)) or ('Administrador' if obj.is_superuser else '—')


admin.site.unregister(User)
admin.site.register(User, UsuarioAdmin)
