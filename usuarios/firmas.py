# usuarios/firmas.py — Firma electrónica (21 CFR Part 11) y bloqueo por intentos fallidos.
#
# Una acción crítica pide volver a escribir la contraseña (usuario web) o el PIN (operador en /mobile/).
# La firma queda ligada al registro de la bitácora con nombre, fecha y significado.
# Tras MAX_INTENTOS fallos seguidos (login o firma) la cuenta o el PIN se bloquean hasta que
# un administrador los desbloquee (admin de Django o `manage.py desbloquear_usuario`).

from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone

MAX_INTENTOS = getattr(settings, 'FIRMA_MAX_INTENTOS', 5)

# Acciones que exigen firma y lo que la persona afirma al firmar
SIGNIFICADOS = {
    'ABORTAR_LOTE': 'Autorizo el aborto del lote',
    'ELIMINAR_LOTE': 'Autorizo la eliminación del lote planeado',
    'ARCHIVAR_LOTE': 'Autorizo el archivo del lote completado',
    'FASE_EN_PROGRESO': 'Inicio la ejecución de la fase',
    'FASE_COMPLETADA': 'Ejecución completada y verificada',
    'FASE_PENDIENTE': 'Autorizo regresar la fase a pendiente',
    'FASE_OMITIDA': 'Autorizo omitir la fase',
    'CAMBIAR_EQUIPO': 'Autorizo el cambio de equipo durante la ejecución',
    'ENTREGAR_MATERIAL': 'Entrego el material indicado',
    'RECIBIR_MATERIAL': 'Recibo el material conforme',
    'RECHAZAR_MATERIAL': 'Rechazo el material entregado',
    'DEVOLVER_MATERIAL': 'Devuelvo el material sobrante',
    'CORREGIR_DATO': 'Corrijo el dato de proceso registrado',
    'CERRAR_EVENTO': 'Evalúo y cierro el evento GMP',
    'ANULAR_EVENTO': 'Autorizo anular el evento GMP registrado por error',
}


class FirmaRechazada(Exception):
    """La firma falta o no es válida. `codigo` orienta al front: FIRMA_REQUERIDA, FIRMA_INVALIDA, CUENTA_BLOQUEADA."""

    def __init__(self, mensaje, codigo, estado_http=400):
        super().__init__(mensaje)
        self.mensaje, self.codigo, self.estado_http = mensaje, codigo, estado_http

    def como_respuesta(self):
        return {'error': self.mensaje, 'codigo': self.codigo}


def perfil_de(usuario):
    from .models import Perfil
    perfil, _ = Perfil.objects.get_or_create(usuario=usuario)
    return perfil


# --- Usuarios web --------------------------------------------------------------------------

def registrar_fallo_usuario(usuario, request, origen):
    """Suma un intento fallido; al llegar al máximo bloquea la cuenta. Devuelve los intentos restantes (0 = bloqueada)."""
    from auditoria.services import registrar
    perfil = perfil_de(usuario)
    perfil.intentos_fallidos += 1
    restantes = max(MAX_INTENTOS - perfil.intentos_fallidos, 0)
    if restantes == 0 and not perfil.bloqueado:
        perfil.bloqueado, perfil.bloqueado_en = True, timezone.now()
        usuario.is_active = False  # Django deja de autenticarla, también en sesiones abiertas
        usuario.save(update_fields=['is_active'])
        registrar(request, 'SESION', 'CUENTA_BLOQUEADA',
                  f"Cuenta {usuario.get_username()} bloqueada tras {MAX_INTENTOS} intentos fallidos ({origen})",
                  objeto=usuario, actor=usuario.get_full_name() or usuario.get_username())
    perfil.save(update_fields=['intentos_fallidos', 'bloqueado', 'bloqueado_en'])
    return restantes


def reiniciar_intentos_usuario(usuario):
    from .models import Perfil
    Perfil.objects.filter(usuario=usuario, intentos_fallidos__gt=0).update(intentos_fallidos=0)


def desbloquear_usuario(usuario):
    perfil = perfil_de(usuario)
    perfil.intentos_fallidos, perfil.bloqueado, perfil.bloqueado_en = 0, False, None
    perfil.save(update_fields=['intentos_fallidos', 'bloqueado', 'bloqueado_en'])
    usuario.is_active = True
    usuario.save(update_fields=['is_active'])


# --- Operadores (PIN) ----------------------------------------------------------------------

def registrar_fallo_pin(operador, request, origen):
    from auditoria.services import registrar
    operador.intentos_pin_fallidos += 1
    restantes = max(MAX_INTENTOS - operador.intentos_pin_fallidos, 0)
    if restantes == 0 and not operador.pin_bloqueado:
        operador.pin_bloqueado = True
        registrar(request, 'SESION', 'PIN_BLOQUEADO',
                  f"PIN de {operador.nombre} ({operador.codigo_empleado}) bloqueado tras {MAX_INTENTOS} intentos fallidos ({origen})",
                  objeto=operador, actor=f"Terminal: {operador.codigo_empleado}")
    operador.save(update_fields=['intentos_pin_fallidos', 'pin_bloqueado'])
    return restantes


def reiniciar_intentos_pin(operador):
    if operador.intentos_pin_fallidos:
        operador.intentos_pin_fallidos = 0
        operador.save(update_fields=['intentos_pin_fallidos'])


def desbloquear_pin(operador):
    operador.intentos_pin_fallidos, operador.pin_bloqueado = 0, False
    operador.save(update_fields=['intentos_pin_fallidos', 'pin_bloqueado'])


# --- Verificación de la firma -----------------------------------------------------------------

def verificar_firma(request, accion):
    """
    Valida la firma de la petición para `accion` (clave de SIGNIFICADOS).
    Usuario web: `firma_password`. Operador en la terminal: `firma_pin`. Opcional: `firma_comentario`.
    Devuelve los datos del firmante para `auditoria.services.firmar`; si no es válida lanza FirmaRechazada.
    """
    from auditoria.services import registrar
    from .permisos import operador_de_sesion

    significado = SIGNIFICADOS[accion]
    comentario = (request.data.get('firma_comentario') or '').strip()
    usuario = request.user

    if usuario.is_authenticated:
        if request.data.get('firma_pin') and not request.data.get('firma_password'):
            # La tablet firma con PIN, pero en este navegador se abrió una sesión web que cerró la terminal del operador
            raise FirmaRechazada(f"En este navegador se inició sesión web como «{usuario.get_username()}» y eso cerró la terminal. "
                                 "Vuelve a ingresar con tu número de empleado y PIN.", 'TERMINAL_CERRADA', 401)
        contrasena = request.data.get('firma_password')
        if not contrasena:
            raise FirmaRechazada(f"Esta acción requiere tu firma electrónica: «{significado}».", 'FIRMA_REQUERIDA')
        if not usuario.check_password(contrasena):
            restantes = registrar_fallo_usuario(usuario, request, 'firma electrónica')
            registrar(request, 'SESION', 'FIRMA_FALLIDA', f"Firma electrónica fallida: {significado}", objeto=usuario)
            if restantes == 0:
                logout(request._request if hasattr(request, '_request') else request)
                raise FirmaRechazada("Tu cuenta quedó bloqueada por intentos fallidos. Pide a un administrador que la desbloquee.",
                                     'CUENTA_BLOQUEADA', 403)
            raise FirmaRechazada(f"Contraseña incorrecta. Te quedan {restantes} intento(s) antes de bloquear la cuenta.", 'FIRMA_INVALIDA')
        reiniciar_intentos_usuario(usuario)
        return {'usuario': usuario, 'operador': None, 'nombre': usuario.get_full_name() or usuario.get_username(),
                'metodo': 'CONTRASENA', 'significado': significado, 'comentario': comentario}

    operador = operador_de_sesion(request)
    if operador:
        pin = request.data.get('firma_pin')
        if not pin:
            raise FirmaRechazada(f"Confirma con tu PIN: «{significado}».", 'FIRMA_REQUERIDA')
        if operador.pin_bloqueado or str(pin) != (operador.pin_acceso or ''):
            restantes = 0 if operador.pin_bloqueado else registrar_fallo_pin(operador, request, 'firma en terminal')
            registrar(request, 'SESION', 'FIRMA_FALLIDA', f"Firma con PIN fallida: {significado}", objeto=operador)
            if restantes == 0:
                request.session.pop('operador_id', None)
                raise FirmaRechazada("Tu PIN quedó bloqueado por intentos fallidos. Pide a tu supervisor o a un administrador que lo desbloquee.",
                                     'CUENTA_BLOQUEADA', 403)
            raise FirmaRechazada(f"PIN incorrecto. Te quedan {restantes} intento(s) antes de bloquearlo.", 'FIRMA_INVALIDA')
        reiniciar_intentos_pin(operador)
        return {'usuario': None, 'operador': operador, 'nombre': f"{operador.nombre} ({operador.codigo_empleado})",
                'metodo': 'PIN', 'significado': significado, 'comentario': comentario}

    raise FirmaRechazada("Inicia sesión para firmar.", 'FIRMA_REQUERIDA', 401)
