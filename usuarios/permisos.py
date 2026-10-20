# usuarios/permisos.py — Control de acceso de la API por acción y rol.

from rest_framework import exceptions, permissions
from rest_framework.authentication import SessionAuthentication

NOMBRES_PERMISO = {
    'instanciar_lote': 'crear lotes',
    'abortar_lote': 'abortar o archivar lotes',
    'reprogramar_fase': 'reprogramar fases',
    'asignar_personal': 'asignar personal o equipos',
    'ejecutar_fase': 'iniciar o completar fases',
    'ajustar_material_lote': 'ajustar materiales de un lote',
    'editar_receta': 'editar recetas',
    'archivar_receta': 'archivar recetas',
    'gestionar_catalogos': 'modificar catálogos',
    'gestionar_roster': 'modificar el roster',
    'gestionar_usuarios': 'gestionar usuarios',
}

# Marca para acciones POST que solo consultan (ej. validar disponibilidad): basta con tener sesión.
SOLO_SESION = None


def tiene_permiso(usuario, codigo):
    return bool(usuario and usuario.is_authenticated and usuario.has_perm(f'usuarios.{codigo}'))


def operador_de_sesion(request):
    """Operador que inició sesión con su PIN en /mobile/ (no es un usuario de Django)."""
    from roster.models import Operador
    operador_id = request.session.get('operador_id') if hasattr(request, 'session') else None
    if not operador_id:
        return None
    return Operador.objects.filter(id=operador_id, activo=True).first()


class SesionAutenticacion(SessionAuthentication):
    """Igual que la de DRF, pero responde 401 (no 403) sin sesión, para que el front distinga
    "inicia sesión" de "tu rol no lo permite"."""

    def authenticate_header(self, request):
        return 'Session'


class PermisoPorAccion(permissions.BasePermission):
    """
    Lectura: cualquier usuario con sesión. Escritura: el permiso que la vista declare en
    `permisos_por_accion` = {'create': 'instanciar_lote', 'abortar': 'abortar_lote', ...}
    o, si la acción no aparece, en `permiso_escritura`. Si no declara nada, se niega.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method.lower() not in view.http_method_names or (hasattr(view, 'action') and view.action is None):
            # Método que la ruta no admite: se deja pasar para que DRF responda 405
            return True
        codigo = self._permiso_requerido(view)
        if codigo is SOLO_SESION and self._accion_declarada(view):
            return True
        if not codigo:
            self.message = "Esta acción no está habilitada para ningún rol."
            return request.user.is_superuser
        if tiene_permiso(request.user, codigo):
            return True
        self.message = f"Tu rol no permite {NOMBRES_PERMISO.get(codigo, codigo)}."
        return False

    @staticmethod
    def _accion_declarada(view):
        return getattr(view, 'action', None) in getattr(view, 'permisos_por_accion', {})

    @staticmethod
    def _permiso_requerido(view):
        accion = getattr(view, 'action', None)
        por_accion = getattr(view, 'permisos_por_accion', {})
        if accion in por_accion:
            return por_accion[accion]
        return getattr(view, 'permiso_escritura', None)


class PermisoFaseLote(PermisoPorAccion):
    """
    Fases de lote: además de los roles con `ejecutar_fase`, el operador que entró con su PIN
    en /mobile/ puede iniciar o completar las fases donde está asignado (y solo esas).
    """

    def _via_operador(self, request, view):
        return getattr(view, 'action', None) == 'cambiar_estado' and not tiene_permiso(request.user, 'ejecutar_fase')

    def has_permission(self, request, view):
        if self._via_operador(request, view) and operador_de_sesion(request):
            if not request.user.is_authenticated:
                # Sin usuario de Django, DRF no revisa CSRF por su cuenta
                SesionAutenticacion().enforce_csrf(request)
            return True
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        if self._via_operador(request, view):
            operador = operador_de_sesion(request)
            if not (operador and obj.operadores_asignados.filter(operador=operador).exists()):
                # Se lanza directo: devolviendo False, DRF respondería 401 al no haber usuario de Django
                raise exceptions.PermissionDenied("Solo puedes iniciar o completar tareas que tienes asignadas.")
        return True
