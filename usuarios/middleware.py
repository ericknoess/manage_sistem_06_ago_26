# usuarios/middleware.py

from django.conf import settings
from django.contrib.auth.views import redirect_to_login

# Rutas que no piden sesión de usuario: el login, la terminal del operador (usa su PIN),
# recursos estáticos, el admin (tiene su propio login) y la API (DRF responde 401/403 en JSON).
RUTAS_LIBRES = ('/login/', '/logout/', '/mobile/', '/static/', '/media/', '/admin/', '/api/', '/favicon.ico')


class LoginRequeridoMiddleware:
    """Manda al login cualquier pantalla abierta sin sesión."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(RUTAS_LIBRES):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return self.get_response(request)
