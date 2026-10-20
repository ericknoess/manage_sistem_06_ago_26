# usuarios/views.py

from django.contrib.auth import views as auth_views
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .roles import TODOS


class LoginView(auth_views.LoginView):
    template_name = 'usuarios/login.html'
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    next_page = 'login'


@method_decorator(ensure_csrf_cookie, name='dispatch')
class SesionAPIView(APIView):
    """Usuario conectado, sus roles y permisos. Las pantallas lo usan para mostrar u ocultar acciones;
    la API vuelve a validar cada permiso, así que ocultar un botón no es la única barrera."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        usuario = request.user
        perfil = getattr(usuario, 'perfil', None)
        roles = list(usuario.groups.order_by('name').values_list('name', flat=True))
        if usuario.is_superuser and 'Administrador' not in roles:
            roles.insert(0, 'Administrador')
        return Response({
            'usuario': usuario.get_username(),
            'nombre': usuario.get_full_name() or usuario.get_username(),
            'roles': roles,
            'permisos': [p for p in TODOS if usuario.has_perm(f'usuarios.{p}')],
            'es_superusuario': usuario.is_superuser,
            'puesto': perfil.puesto if perfil else '',
            'operador_id': perfil.operador_id if perfil else None,
        })
