# eventos/services.py — Reporte, creación automática, cierre y anulación de eventos GMP.
#
# Reportar: cualquier persona con sesión (web o tablet con PIN). Cerrar o anular: permiso `evaluar_evento`
# (Calidad, Supervisor de turno, Jefatura, Administrador), con firma electrónica, y nunca quien lo reportó
# (regla de cuatro ojos; un usuario web y su Perfil.operador son la misma persona).
# Automáticos: dato capturado fuera de especificación (uno por dato) e inicio de tarea fuera de su ventana.

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from auditoria.services import firmar, quien, registrar

from .models import EventoGMP

TEXTO_MINIMO = 10
# Clasificaciones que son desviación: piden el número del sistema de calidad
CLASIFICACIONES_DESVIACION = ('MENOR', 'MAYOR', 'CRITICA')


class ErrorEvento(Exception):
    """Regla de negocio violada al reportar, cerrar o anular un evento."""


# ------------------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------------------

def _siguiente_folio(anio):
    prefijo = f"EV-{anio}-"
    ultimo = (EventoGMP.objects.filter(folio__startswith=prefijo).order_by('-folio').values_list('folio', flat=True).first())
    numero = int(ultimo.rsplit('-', 1)[1]) + 1 if ultimo else 1
    return f"{prefijo}{numero:04d}"


def _crear(**campos):
    """Crea el evento con el siguiente folio del año (reintenta si dos se crean a la vez)."""
    anio = timezone.localtime(timezone.now()).year
    for _ in range(5):
        try:
            with transaction.atomic():
                return EventoGMP.objects.create(folio=_siguiente_folio(anio), **campos)
        except IntegrityError:
            continue
    raise ErrorEvento("No se pudo asignar el folio del evento; vuelve a intentarlo.")


def nombre_tarea(fase):
    if fase is None:
        return ''
    op = fase.operacion_maestra
    nombre = fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo and fase.nombre_tarea_dinamica else op.nombre
    return f"[{op.identificador_paso}] {nombre}"


def _personas(usuario, operador):
    from procesos.services import _personas as personas
    return personas(usuario, operador)


def es_quien_reporto(evento, usuario, operador):
    """True si quien actúa es la misma persona que reportó el evento (regla de cuatro ojos)."""
    return bool(_personas(usuario, operador) & _personas(evento.reportado_por_usuario, evento.reportado_por_operador))


def _registrar(request, accion, evento, descripcion, cambios=None, motivo='', actor=None):
    return registrar(request, 'EVENTO', accion, descripcion, objeto=evento, lote=evento.lote, fase=evento.fase,
                     cambios=cambios or {}, motivo=motivo, actor=actor)


# ------------------------------------------------------------------------------
# Reporte manual
# ------------------------------------------------------------------------------

def _validar_lote(lote):
    if lote.archivado:
        raise ErrorEvento(f"El lote {lote.identificador_lote} está archivado: ya no admite eventos.")


@transaction.atomic
def reportar_evento(request, *, lote=None, fase=None, tipo, titulo, descripcion, accion_inmediata='', ocurrio_en=None, equipo=None):
    """Registra un evento reportado por una persona. `fase` (opcional) fija el lote si no se da."""
    if fase is not None:
        if lote is not None and fase.lote_id != lote.pk:
            raise ErrorEvento("La tarea no pertenece a ese lote.")
        lote = fase.lote
    if lote is None:
        raise ErrorEvento("Indica el lote del evento.")
    _validar_lote(lote)
    if tipo not in dict(EventoGMP.TIPO_CHOICES):
        raise ErrorEvento("Elige el tipo de evento.")
    titulo, descripcion = (titulo or '').strip(), (descripcion or '').strip()
    if len(titulo) < 5:
        raise ErrorEvento("Escribe un título breve del evento (mínimo 5 caracteres).")
    if len(descripcion) < TEXTO_MINIMO:
        raise ErrorEvento(f"Describe qué pasó (mínimo {TEXTO_MINIMO} caracteres).")
    ahora = timezone.now()
    ocurrio_en = ocurrio_en or ahora
    if ocurrio_en > ahora + timedelta(minutes=5):
        raise ErrorEvento("La hora del evento no puede ser futura.")

    usuario, operador, nombre, _ = quien(request)
    evento = _crear(lote=lote, fase=fase, tipo=tipo, origen='MANUAL', titulo=titulo[:200], descripcion=descripcion,
                    accion_inmediata=(accion_inmediata or '').strip(), ocurrio_en=ocurrio_en, equipo=equipo,
                    reportado_por_usuario=usuario, reportado_por_operador=operador, reportado_por_nombre=nombre[:150])
    _registrar(request, 'REPORTAR_EVENTO', evento, f"Evento {evento.folio} reportado: {evento.titulo} · lote {lote.identificador_lote}",
               cambios={'tipo': [None, evento.get_tipo_display()], 'titulo': [None, evento.titulo],
                        'equipo': [None, str(equipo) if equipo else None]})
    return evento


# ------------------------------------------------------------------------------
# Eventos automáticos
# ------------------------------------------------------------------------------

def _evento_automatico(request, *, lote, fase, tipo, titulo, descripcion, ocurrio_en, actor, valor=None):
    """Evento creado por el sistema; queda a nombre de quien hizo la acción que lo originó."""
    evento = _crear(lote=lote, fase=fase, tipo=tipo, origen='AUTOMATICO', titulo=titulo[:200], descripcion=descripcion,
                    ocurrio_en=ocurrio_en, valor=valor, reportado_por_usuario=actor['usuario'],
                    reportado_por_operador=actor['operador'], reportado_por_nombre=actor['nombre'][:150])
    _registrar(request, 'EVENTO_AUTOMATICO', evento, f"Evento {evento.folio} creado automáticamente: {evento.titulo} · lote {lote.identificador_lote}",
               cambios={'tipo': [None, evento.get_tipo_display()]})
    return evento


def _texto_numero(valor):
    from datos_proceso.services import texto_decimal
    return texto_decimal(valor)


def eventos_fuera_especificacion(request, toma):
    """Un evento por cada dato vigente de la toma fuera de especificación que aún no tenga uno abierto
    (al corregir un dato que sigue fuera, no se duplica). Devuelve los eventos creados."""
    valores = (toma.valores.filter(vigente=True, fuera_especificacion=True)
               .select_related('parametro', 'registrado_por_usuario', 'registrado_por_operador'))
    if not valores:
        return []
    fase = toma.fase
    abiertos = set(EventoGMP.objects.filter(estado='ABIERTO', tipo='FUERA_ESPECIFICACION', valor__toma=toma)
                   .values_list('valor__parametro_id', flat=True))
    creados = []
    for v in valores:
        if v.parametro_id in abiertos:
            continue
        lim = v.limites or {}
        unidad = f" {v.parametro.unidad}" if v.parametro.unidad else ''
        rango = f"{lim.get('especificacion_min') or '−∞'} a {lim.get('especificacion_max') or '∞'}{unidad}"
        dato = f"{v.parametro.nombre} = {_texto_numero(v.valor_numero)}{unidad}"
        descripcion = (f"{dato}, fuera de especificación ({rango}). Tarea {nombre_tarea(fase)}, "
                       f"toma del {timezone.localtime(toma.momento):%d/%m/%Y %H:%M}"
                       + (f", sección {v.seccion_nombre}" if v.seccion_nombre else '')
                       + (f". Valor corregido: {v.motivo_correccion}" if v.reemplaza_id else '') + '.')
        actor = {'usuario': v.registrado_por_usuario, 'operador': v.registrado_por_operador, 'nombre': v.registrado_por_nombre}
        creados.append(_evento_automatico(
            request, lote=fase.lote, fase=fase, tipo='FUERA_ESPECIFICACION', titulo=f"Fuera de especificación: {dato}",
            descripcion=descripcion, ocurrio_en=toma.momento, actor=actor, valor=v))
    return creados


def evento_inicio_fuera_ventana(request, fase, mensaje, motivo):
    """Evento de una tarea iniciada fuera de su ventana de tolerancia (con el motivo que dio quien la inició)."""
    usuario, operador, nombre, _ = quien(request)
    return _evento_automatico(
        request, lote=fase.lote, fase=fase, tipo='INICIO_FUERA_VENTANA', titulo=f"Inicio fuera de ventana: {nombre_tarea(fase)}",
        descripcion=f"{mensaje} Motivo: {motivo}", ocurrio_en=fase.fecha_inicio_real or timezone.now(),
        actor={'usuario': usuario, 'operador': operador, 'nombre': nombre})


# ------------------------------------------------------------------------------
# Evaluación: cerrar o anular (con firma)
# ------------------------------------------------------------------------------

def _validar_evaluador(evento, request):
    if evento.estado != 'ABIERTO':
        raise ErrorEvento(f"El evento {evento.folio} ya está {evento.get_estado_display().lower()}.")
    usuario, operador, _, _ = quien(request)
    if es_quien_reporto(evento, usuario, operador):
        raise ErrorEvento("Quien reportó el evento no puede evaluarlo ni anularlo (regla de cuatro ojos).")


def validar_cierre(evento, request, clasificacion, evaluacion, numero_desviacion):
    """Revisa todo antes de pedir la firma (un error de captura no cuenta como intento fallido)."""
    _validar_evaluador(evento, request)
    if clasificacion not in dict(EventoGMP.CLASIFICACION_CHOICES):
        raise ErrorEvento("Elige la clasificación del evento.")
    if len((evaluacion or '').strip()) < TEXTO_MINIMO:
        raise ErrorEvento(f"Escribe la evaluación del impacto (mínimo {TEXTO_MINIMO} caracteres).")
    if clasificacion in CLASIFICACIONES_DESVIACION and not (numero_desviacion or '').strip():
        raise ErrorEvento("Una desviación lleva su número en el sistema de calidad.")


@transaction.atomic
def cerrar_evento(request, evento, firmante, *, clasificacion, evaluacion, numero_desviacion=''):
    evento = EventoGMP.objects.select_for_update().get(pk=evento.pk)
    validar_cierre(evento, request, clasificacion, evaluacion, numero_desviacion)
    evento.estado, evento.clasificacion = 'CERRADO', clasificacion
    evento.evaluacion, evento.numero_desviacion = evaluacion.strip(), (numero_desviacion or '').strip()[:50]
    evento.cerrado_por_usuario, evento.cerrado_por_nombre = firmante['usuario'], firmante['nombre'][:150]
    evento.cerrado_en = timezone.now()
    registro = _registrar(request, 'CERRAR_EVENTO', evento, f"Evento {evento.folio} evaluado y cerrado: {evento.get_clasificacion_display()}",
                          cambios={'estado': ['ABIERTO', 'CERRADO'], 'clasificacion': [None, evento.get_clasificacion_display()],
                                   'numero_desviacion': [None, evento.numero_desviacion or None]},
                          motivo=evento.evaluacion)
    firmar(registro, firmante)
    evento.registro_cierre = registro
    evento.save()
    return evento


def validar_anulacion(evento, request, motivo):
    _validar_evaluador(evento, request)
    if len((motivo or '').strip()) < TEXTO_MINIMO:
        raise ErrorEvento(f"Escribe por qué se anula (mínimo {TEXTO_MINIMO} caracteres).")


@transaction.atomic
def anular_evento(request, evento, firmante, *, motivo):
    evento = EventoGMP.objects.select_for_update().get(pk=evento.pk)
    validar_anulacion(evento, request, motivo)
    evento.estado, evento.motivo_anulacion = 'ANULADO', motivo.strip()
    evento.cerrado_por_usuario, evento.cerrado_por_nombre = firmante['usuario'], firmante['nombre'][:150]
    evento.cerrado_en = timezone.now()
    registro = _registrar(request, 'ANULAR_EVENTO', evento, f"Evento {evento.folio} anulado",
                          cambios={'estado': ['ABIERTO', 'ANULADO']}, motivo=evento.motivo_anulacion)
    firmar(registro, firmante)
    evento.registro_cierre = registro
    evento.save()
    return evento


# ------------------------------------------------------------------------------
# Consulta
# ------------------------------------------------------------------------------

def eventos_abiertos(lote):
    return EventoGMP.objects.filter(lote=lote, estado='ABIERTO').count()


def eventos_informe(lote, etapa_id=None):
    """Eventos del lote para el informe (los de la etapa y los que no tienen tarea), con la firma del cierre."""
    eventos = (EventoGMP.objects.filter(lote=lote)
               .select_related('fase__operacion_maestra', 'equipo', 'valor__parametro', 'registro_cierre__firma')
               .order_by('ocurrio_en', 'id'))
    if etapa_id:
        from django.db.models import Q
        eventos = eventos.filter(Q(fase__isnull=True) | Q(fase__operacion_maestra__etapa_id=etapa_id))
    salida = []
    for e in eventos:
        firma = getattr(e.registro_cierre, 'firma', None) if e.registro_cierre_id else None
        salida.append({
            'folio': e.folio, 'ocurrio_en': e.ocurrio_en, 'tipo': e.get_tipo_display(), 'origen': e.get_origen_display(),
            'tarea': nombre_tarea(e.fase), 'equipo': str(e.equipo) if e.equipo_id else '', 'titulo': e.titulo,
            'descripcion': e.descripcion, 'accion_inmediata': e.accion_inmediata, 'reporto': e.reportado_por_nombre,
            'estado': e.get_estado_display(), 'clasificacion': e.get_clasificacion_display() if e.clasificacion else '',
            'numero_desviacion': e.numero_desviacion, 'evaluacion': e.evaluacion or e.motivo_anulacion,
            'firma': {'nombre': firma.nombre_firmante, 'significado': firma.significado, 'fecha': firma.fecha,
                      'metodo': firma.get_metodo_display()} if firma else None,
        })
    return salida
