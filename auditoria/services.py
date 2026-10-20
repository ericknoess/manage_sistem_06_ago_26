# auditoria/services.py — Escritura de la bitácora de auditoría.

import json
from datetime import date, datetime
from decimal import Decimal

from .models import RegistroAuditoria

# Nunca se guardan en la bitácora
CAMPOS_SECRETOS = ('password', 'pin', 'token')
# Cambian solos en cada guardado; no aportan a la auditoría
CAMPOS_IGNORADOS = {'created_at', 'updated_at', 'creado_en', 'actualizado_en'}


def _ip(request):
    if request is None:
        return None
    reenviada = request.META.get('HTTP_X_FORWARDED_FOR')
    return (reenviada.split(',')[0].strip() if reenviada else request.META.get('REMOTE_ADDR')) or None


def quien(request):
    """(usuario, operador, nombre, roles) de quien hace la petición."""
    usuario = getattr(request, 'user', None)
    if usuario is not None and usuario.is_authenticated:
        roles = list(usuario.groups.order_by('name').values_list('name', flat=True))
        if usuario.is_superuser and 'Administrador' not in roles:
            roles.insert(0, 'Administrador')
        return usuario, None, usuario.get_full_name() or usuario.get_username(), ', '.join(roles)

    from usuarios.permisos import operador_de_sesion
    operador = operador_de_sesion(request) if request is not None else None
    if operador:
        return None, operador, f"{operador.nombre} ({operador.codigo_empleado})", 'Operador (PIN)'
    return None, None, 'Sistema', ''


def _valor_simple(valor):
    """Valores de la bitácora en formato JSON y legible."""
    if isinstance(valor, Decimal):
        return format(valor.normalize(), 'f') if valor == valor.to_integral() else str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, (list, tuple)):
        return [_valor_simple(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _valor_simple(v) for k, v in valor.items()}
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    return str(valor)


def _es_secreto(campo):
    return any(s in campo.lower() for s in CAMPOS_SECRETOS)


def limpiar(datos):
    """Quita secretos y campos automáticos de un dict de datos."""
    return {k: _valor_simple(v) for k, v in (datos or {}).items() if not _es_secreto(k) and k not in CAMPOS_IGNORADOS}


def diferencias(antes, despues):
    """{"campo": [antes, después]} solo para lo que cambió (o todo, si uno de los dos es None)."""
    antes, despues = limpiar(antes), limpiar(despues)
    claves = list(dict.fromkeys([*antes.keys(), *despues.keys()]))
    salida = {}
    for clave in claves:
        a, d = antes.get(clave), despues.get(clave)
        if json.dumps(a, sort_keys=True, default=str) != json.dumps(d, sort_keys=True, default=str):
            salida[clave] = [a, d]
    return salida


def registrar(request, categoria, accion, descripcion, *, objeto=None, objeto_tipo='', objeto_id='',
              lote=None, fase=None, lote_codigo='', motivo='', cambios=None, actor=None):
    """Agrega un registro a la bitácora. `objeto` llena tipo e id; `fase` también llena el lote.
    `lote_codigo` sirve cuando el lote ya no existe (se eliminó un lote planeado)."""
    usuario, operador, nombre_actor, roles = quien(request)
    actor = actor or nombre_actor
    if objeto is not None:
        objeto_tipo = objeto_tipo or objeto._meta.model_name
        objeto_id = objeto_id or str(objeto.pk)
    if fase is not None and lote is None:
        lote = fase.lote
    return RegistroAuditoria.objects.create(
        usuario=usuario, operador=operador, actor=actor[:150], roles=roles[:255], ip=_ip(request),
        categoria=categoria, accion=accion, descripcion=str(descripcion)[:500],
        objeto_tipo=objeto_tipo, objeto_id=str(objeto_id),
        lote=lote, lote_codigo=lote.identificador_lote if lote else lote_codigo, fase=fase,
        motivo=motivo or '', cambios=_valor_simple(cambios or {}),
    )
