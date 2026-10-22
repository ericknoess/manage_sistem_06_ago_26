# procesos/services.py

from datetime import date, timedelta

from django.utils import timezone
from django.db.models import Count, Max
from roster.models import TurnoDia, Operador
from .models import (
    OperacionProceso, RequerimientoPersonalFase, FaseLote, AsignacionFaseOperador,
    MaterialOperacion, MaterialFase, EquipoOperacion, EquipoFase, ReservaEquipo,
)


class CPMCalculatorService:
    """
    Servicio de dominio para calcular la Ruta Crítica (CPM), tiempos tempranos (ES, EF),
    tiempos tardíos (LS, LF) y holguras (Float/Slack) de las operaciones de un proceso maestro.
    """

    def __init__(self, operaciones):
        self.operaciones = list(operaciones)

    def calcular_cpm(self):
        if not self.operaciones:
            return {
                "tiempo_total_proceso": 0.0,
                "operaciones_cpm": []
            }

        tiempos = {}
        
        # =====================================================================
        # 1. FORWARD PASS (Paso hacia adelante: cálculo de ES y EF)
        # =====================================================================
        for op in self.operaciones:
            es = 0.0
            ef = 0.0
            desfase = op.desfase_horas or 0.0
            duracion = op.duracion_horas or 0.0
            
            pred_id = op.predecesora_id
            if pred_id and pred_id in tiempos:
                pred_info = tiempos[pred_id]
                tipo_dep = op.tipo_dependencia or 'FS'
                
                if tipo_dep == 'SS':  # Start-to-Start (Inicio a Inicio)
                    es = pred_info['es'] + desfase
                elif tipo_dep == 'OFFSET':  # Desfase fijo general
                    es = pred_info['es'] + desfase
                else:  # FS (Finish-to-Start) - Dependencia Lineal
                    es = pred_info['ef'] + desfase
            
            ef = es + duracion
            tiempos[op.id] = {
                'es': es,
                'ef': ef,
                'duracion': duracion,
                'op': op
            }

        tiempo_total_proyecto = max([info['ef'] for info in tiempos.values()], default=0.0)

        # =====================================================================
        # 2. BACKWARD PASS (Paso hacia atrás: cálculo de LS y LF)
        # =====================================================================
        # Inicializamos todas las tareas asumiendo el tiempo total del proyecto
        for op in self.operaciones:
            tiempos[op.id]['lf'] = tiempo_total_proyecto
            tiempos[op.id]['ls'] = tiempo_total_proyecto - tiempos[op.id]['duracion']

        # Iteramos en reversa para propagar las restricciones matemáticas de las sucesoras
        for op in reversed(self.operaciones):
            current_info = tiempos[op.id]
            sucesora_ops = [o for o in self.operaciones if o.predecesora_id == op.id]
            
            if sucesora_ops:
                # Límites preliminares basados en el final del proyecto
                min_lf_requerido = current_info['lf']
                min_ls_requerido = current_info['ls']
                
                for suc in sucesora_ops:
                    suc_info = tiempos[suc.id]
                    tipo_dep = suc.tipo_dependencia or 'FS'
                    desfase = suc.desfase_horas or 0.0
                    
                    if tipo_dep == 'SS' or tipo_dep == 'OFFSET':
                        # Para Start-to-Start: La sucesora restringe la hora máxima de INICIO de la predecesora
                        limite_ls = suc_info['ls'] - desfase
                        if limite_ls < min_ls_requerido:
                            min_ls_requerido = limite_ls
                    else: 
                        # Para Finish-to-Start: La sucesora restringe la hora máxima de FIN de la predecesora
                        limite_lf = suc_info['ls'] - desfase
                        if limite_lf < min_lf_requerido:
                            min_lf_requerido = limite_lf
                
                # Consolidación Matemática (La restricción más estricta gana)
                nuevo_lf = min(min_lf_requerido, min_ls_requerido + current_info['duracion'])
                
                current_info['lf'] = nuevo_lf
                current_info['ls'] = nuevo_lf - current_info['duracion']

        # =====================================================================
        # 3. CÁLCULO DE HOLGURA (SLACK) Y DEFINICIÓN DE RUTA CRÍTICA
        # =====================================================================
        resultado_detalles = []
        for op in self.operaciones:
            info = tiempos[op.id]
            es = info['es']
            ef = info['ef']
            ls = info['ls']
            lf = info['lf']
            
            # Cálculo de la holgura total
            holgura = round(ls - es, 2)
            
            # Es Crítica si la holgura es 0. Tolerancia de redondeo (0.01) por cálculo en floats.
            es_critica = abs(holgura) <= 0.01

            resultado_detalles.append({
                "id": op.id,
                "identificador_paso": op.identificador_paso,
                "nombre": op.nombre,
                "tipo_operacion": op.tipo_operacion,
                "duracion_horas": op.duracion_horas,
                "es": round(es, 2),
                "ef": round(ef, 2),
                "ls": round(ls, 2),
                "lf": round(lf, 2),
                "holgura": holgura,
                "es_critica": es_critica,
                "personal_requerido": op.personal_requerido,
                "equipos": [f"{e.tipo.nombre} ×{e.cantidad}" for e in op.equipos.all()],
            })

        return {
            "tiempo_total_proceso": round(tiempo_total_proyecto, 2),
            "operaciones_cpm": resultado_detalles
        }


def validar_disponibilidad_personal_fase(operacion_id: int, fecha_evaluacion: date):
    """
    Motor de Validación por Competencias (Skill-Matching Engine):
    Compara los requerimientos de personal por rol de una operación CPM 
    frente a la disponibilidad real de operadores en el Roster para una fecha dada.
    """
    try:
        operacion = OperacionProceso.objects.prefetch_related('requerimientos_rol__rol').get(id=operacion_id)
    except OperacionProceso.DoesNotExist:
        return {
            "valido": False,
            "error": "La operación especificada no existe."
        }

    requerimientos = operacion.requerimientos_rol.all()
    
    if not requerimientos.exists():
        return {
            "valido": True,
            "mensaje": "La fase no tiene requerimientos específicos de roles configurados."
        }

    turnos_activos = TurnoDia.objects.filter(
        fecha=fecha_evaluacion,
        operador__activo=True,
        tipo_turno__activo=True,
        tipo_turno__es_descanso=False
    ).select_related('operador__rol', 'tipo_turno')

    disponibilidad_por_rol = {}
    for turno in turnos_activos:
        operador = turno.operador
        if operador and operador.rol:
            rol_id = operador.rol.id
            disponibilidad_por_rol[rol_id] = disponibilidad_por_rol.get(rol_id, 0) + 1

    detalles_cumplimiento = []
    cumple_total = True

    for req in requerimientos:
        rol_requerido = req.rol
        cantidad_demandada = req.cantidad
        cantidad_disponible = disponibilidad_por_rol.get(rol_requerido.id, 0)

        satisfecho = cantidad_disponible >= cantidad_demandada
        if not satisfecho:
            cumple_total = False

        detalles_cumplimiento.append({
            "rol_id": rol_requerido.id,
            "rol_nombre": rol_requerido.nombre,
            "cantidad_demandada": cantidad_demandada,
            "cantidad_disponible": cantidad_disponible,
            "brecha": max(0, cantidad_demandada - cantidad_disponible),
            "cumplido": satisfecho
        })

    return {
        "valido": True,
        "operacion_id": operacion.id,
        "operacion_nombre": operacion.nombre,
        "fecha": fecha_evaluacion.strftime('%Y-%m-%d'),
        "cumple_requerimientos_global": cumple_total,
        "detalles": detalles_cumplimiento
    }


# ==============================================================================
# PROGRAMACIÓN DE FASES (fecha-hora completas: soporta fases de varios días)
# ==============================================================================

def inicio_por_dependencia(operacion, inicio_predecesora, fin_predecesora):
    """Inicio más temprano de una operación según su regla de dependencia con la predecesora."""
    desfase = timedelta(hours=operacion.desfase_horas or 0.0)
    if (operacion.tipo_dependencia or 'FS') in ('SS', 'OFFSET'):
        return inicio_predecesora + desfase
    return fin_predecesora + desfase


def construir_fases_lote(lote):
    """
    Genera (sin guardar) las fases de un lote a partir de la ruta CPM de su proceso maestro,
    incluyendo las subtareas de muestreo de las incubaciones.
    """
    operaciones = lote.proceso_maestro.operaciones.all()
    cpm = {item['id']: item for item in CPMCalculatorService(operaciones).calcular_cpm()['operaciones_cpm']}
    inicio_lote = lote.fecha_inicio_planeada
    fases = []

    for op in operaciones:
        cpm_info = cpm.get(op.id)
        if not cpm_info:
            fases.append(FaseLote(lote=lote, operacion_maestra=op, estado='PENDIENTE'))
            continue

        inicio = inicio_lote + timedelta(hours=cpm_info['es'])
        fin = inicio_lote + timedelta(hours=cpm_info['ef'])
        fases.append(FaseLote(
            lote=lote, operacion_maestra=op, estado='PENDIENTE',
            inicio_base_cpm=inicio, fin_base_cpm=fin, inicio_programado=inicio, fin_programado=fin,
        ))

        if op.tipo_operacion == 'INCUBACION' and op.frecuencia_muestreo_horas > 0:
            cantidad_muestreos = int(op.duracion_horas // op.frecuencia_muestreo_horas)
            for i in range(1, cantidad_muestreos + 1):
                horas_transcurridas = i * op.frecuencia_muestreo_horas
                inicio_muestreo = inicio + timedelta(hours=horas_transcurridas)
                fin_muestreo = inicio_muestreo + timedelta(hours=op.duracion_muestreo_horas)
                fases.append(FaseLote(
                    lote=lote, operacion_maestra=op, estado='PENDIENTE',
                    es_subtarea_muestreo=True, indice_muestreo=i,
                    nombre_tarea_dinamica=f"M-{horas_transcurridas}h - {op.nombre}",
                    inicio_base_cpm=inicio_muestreo, fin_base_cpm=fin_muestreo,
                    inicio_programado=inicio_muestreo, fin_programado=fin_muestreo,
                ))
    return fases


def validar_inicio_contra_predecesora(fase, nuevo_inicio):
    """Devuelve un mensaje de error si el nuevo inicio viola la dependencia con la predecesora, o None."""
    if fase.es_subtarea_muestreo:
        return None
    operacion = fase.operacion_maestra
    predecesora = operacion.predecesora
    if not predecesora:
        return None

    fase_pred = FaseLote.objects.filter(lote=fase.lote, operacion_maestra=predecesora, es_subtarea_muestreo=False).first()
    if not fase_pred or not fase_pred.inicio_programado or not fase_pred.fin_programado:
        return None

    limite_inferior = inicio_por_dependencia(operacion, fase_pred.inicio_programado, fase_pred.fin_programado)
    if nuevo_inicio >= limite_inferior:
        return None

    if (operacion.tipo_dependencia or 'FS') in ('SS', 'OFFSET'):
        regla = f"Inicio a Inicio (SS) con la fase [{predecesora.identificador_paso}]"
    else:
        regla = f"Fin a Inicio (FS) tras la fase [{predecesora.identificador_paso}]"
    formato = '%Y-%m-%d %H:%M'
    return (
        f"Violación GxP (Colisión Lógica): La tarea no puede iniciar a las {timezone.localtime(nuevo_inicio).strftime(formato)}. "
        f"Por regla de dependencia {regla}, lo más temprano que puede iniciar es a las {timezone.localtime(limite_inferior).strftime(formato)}."
    )


def propagar_programacion(fase_origen, nota_tarea, nota_muestreo):
    """
    Re-alinea en cascada las fases PENDIENTES que dependen de `fase_origen` (y sus muestreos),
    enganchándolas a la ventana de su predecesora: la real si ya se completó, el inicio real más la
    duración planeada si está en curso, y la programada si aún no inicia.

    `nota_tarea` y `nota_muestreo` admiten los marcadores {paso} (predecesora inmediata) y {origen}.
    Devuelve la cantidad de fases actualizadas.
    """
    if fase_origen.es_subtarea_muestreo:
        # Un muestreo no tiene sucesoras: las de su actividad dependen de la actividad, no del muestreo
        return 0
    todas_fases_lote = list(fase_origen.lote.fases.all().select_related('operacion_maestra'))
    origen = fase_origen.operacion_maestra.identificador_paso
    fases_a_actualizar = []
    fases_procesadas = {fase_origen.id}
    cola_propagacion = [fase_origen]

    while cola_propagacion:
        fase_actual = cola_propagacion.pop(0)
        paso = fase_actual.operacion_maestra.identificador_paso

        if fase_actual.estado == 'COMPLETADA' and fase_actual.fecha_fin_real:
            inicio_actual = fase_actual.fecha_inicio_real or fase_actual.fecha_fin_real
            fin_actual = fase_actual.fecha_fin_real
        elif fase_actual.estado == 'EN_PROGRESO' and fase_actual.fecha_inicio_real:
            inicio_actual = fase_actual.fecha_inicio_real
            fin_actual = inicio_actual + fase_actual.duracion_planeada
        else:
            inicio_actual, fin_actual = fase_actual.inicio_programado, fase_actual.fin_programado
        if not inicio_actual or not fin_actual:
            continue

        for f in todas_fases_lote:
            if f.es_subtarea_muestreo or f.id in fases_procesadas or f.estado != 'PENDIENTE':
                continue
            if f.operacion_maestra.predecesora_id != fase_actual.operacion_maestra_id:
                continue
            f.inicio_programado = inicio_por_dependencia(f.operacion_maestra, inicio_actual, fin_actual)
            f.fin_programado = f.inicio_programado + f.duracion_planeada
            f.motivo_reprogramacion = 'PRODUCCION'
            f.notas_reprogramacion = nota_tarea.format(paso=paso, origen=origen)
            fases_a_actualizar.append(f)
            fases_procesadas.add(f.id)
            cola_propagacion.append(f)

        if not fase_actual.es_subtarea_muestreo:
            for m in todas_fases_lote:
                if not m.es_subtarea_muestreo or m.id in fases_procesadas or m.estado != 'PENDIENTE':
                    continue
                if m.operacion_maestra_id != fase_actual.operacion_maestra_id:
                    continue
                m.inicio_programado = inicio_actual + timedelta(hours=m.indice_muestreo * m.operacion_maestra.frecuencia_muestreo_horas)
                m.fin_programado = m.inicio_programado + m.duracion_planeada
                m.motivo_reprogramacion = 'PRODUCCION'
                m.notas_reprogramacion = nota_muestreo.format(paso=paso, origen=origen)
                fases_a_actualizar.append(m)
                fases_procesadas.add(m.id)

    if fases_a_actualizar:
        FaseLote.objects.bulk_update(
            fases_a_actualizar,
            ['inicio_programado', 'fin_programado', 'motivo_reprogramacion', 'notas_reprogramacion']
        )
    return len(fases_a_actualizar)


def buscar_conflicto_operador(operador_id, fase):
    """
    Devuelve la asignación del operador cuya fase se traslapa con la ventana programada de `fase`
    (comparando fecha-hora completas, incluso entre días), o None si está libre.
    """
    if not fase.inicio_programado or not fase.fin_programado:
        return None
    return AsignacionFaseOperador.objects.filter(
        operador_id=operador_id,
        fase_lote__inicio_programado__lt=fase.fin_programado,
        fase_lote__fin_programado__gt=fase.inicio_programado,
    ).exclude(fase_lote=fase).exclude(fase_lote__estado='OMITIDA').select_related(
        'fase_lote', 'fase_lote__operacion_maestra'
    ).first()



# ==============================================================================
# MATERIALES: COPIA POR LOTE, AJUSTES GxP Y REQUERIMIENTOS POR DÍA Y HORA
# ==============================================================================

# ==============================================================================
# EJECUCIÓN EN PLANTA: VENTANA DE INICIO, DEPENDENCIAS Y ALERTAS DE PROGRAMACIÓN
# ==============================================================================

def formatear_hora(momento, formato='%d/%m %H:%M'):
    return timezone.localtime(momento).strftime(formato)


def _horas_legibles(delta):
    horas = abs(delta.total_seconds()) / 3600
    if horas >= 48:
        dias, resto = divmod(round(horas), 24)
        return f"{dias} d {resto} h" if resto else f"{dias} d"
    return f"{horas:.1f}".rstrip('0').rstrip('.') + ' h'


def bloqueo_por_dependencia(fase):
    """
    Mensaje si la fase todavía no puede iniciar por su dependencia, o None.
    FS: la predecesora debe estar completada (u omitida). SS/OFFSET: la predecesora debe haber iniciado.
    Un muestreo requiere que su actividad (la incubación) ya esté en curso.
    """
    operacion = fase.operacion_maestra
    if fase.es_subtarea_muestreo:
        actividad = FaseLote.objects.filter(lote=fase.lote, operacion_maestra=operacion, es_subtarea_muestreo=False).first()
        if actividad and actividad.estado not in ('EN_PROGRESO', 'COMPLETADA'):
            return f"Primero debe iniciar la actividad [{operacion.identificador_paso}] {operacion.nombre}."
        return None

    predecesora = operacion.predecesora
    if not predecesora:
        return None
    fase_pred = FaseLote.objects.filter(lote=fase.lote, operacion_maestra=predecesora, es_subtarea_muestreo=False).first()
    if not fase_pred or fase_pred.estado == 'OMITIDA':
        return None
    if (operacion.tipo_dependencia or 'FS') in ('SS', 'OFFSET'):
        if fase_pred.estado == 'PENDIENTE':
            return f"Primero debe iniciar [{predecesora.identificador_paso}] {predecesora.nombre} (dependencia Inicio a Inicio)."
    elif fase_pred.estado != 'COMPLETADA':
        return f"Primero debe completarse [{predecesora.identificador_paso}] {predecesora.nombre} (dependencia Fin a Inicio)."
    return None


def ventana_inicio(fase):
    """(desde, hasta) en que la fase puede iniciar sin desviación de horario, según la tolerancia de la receta."""
    if not fase.inicio_programado:
        return None, None
    op = fase.operacion_maestra
    return (fase.inicio_programado - timedelta(hours=op.tolerancia_antes_horas or 0),
            fase.inicio_programado + timedelta(hours=op.tolerancia_despues_horas or 0))


def evaluar_inicio(fase, ahora=None):
    """
    Revisa si la fase pendiente puede iniciar ahora. Devuelve un dict:
      bloqueo      mensaje si la dependencia o el equipo lo impiden (nadie puede iniciarla), o None
      codigo_bloqueo  DEPENDENCIA_PENDIENTE o EQUIPO_PENDIENTE
      desviacion   None (dentro de la ventana), 'ADELANTO' o 'RETRASO'
      mensaje      explicación de la desviación
      desde/hasta  ventana de inicio sin desviación
    """
    ahora = ahora or timezone.now()
    desde, hasta = ventana_inicio(fase)
    bloqueo, codigo = bloqueo_por_dependencia(fase), 'DEPENDENCIA_PENDIENTE'
    if not bloqueo:
        bloqueo, codigo = bloqueo_por_equipo(fase, ahora), 'EQUIPO_PENDIENTE'
    resultado = {'bloqueo': bloqueo, 'codigo_bloqueo': codigo if bloqueo else None,
                 'desviacion': None, 'mensaje': '', 'desde': desde, 'hasta': hasta}
    if desde and ahora < desde:
        resultado['desviacion'] = 'ADELANTO'
        resultado['mensaje'] = (f"Inicio adelantado {_horas_legibles(fase.inicio_programado - ahora)} respecto a lo programado "
                                f"({formatear_hora(fase.inicio_programado)}). Sin desviación puede iniciar a partir de las {formatear_hora(desde)}.")
    elif hasta and ahora > hasta:
        resultado['desviacion'] = 'RETRASO'
        resultado['mensaje'] = (f"Inicio con {_horas_legibles(ahora - fase.inicio_programado)} de retraso respecto a lo programado "
                                f"({formatear_hora(fase.inicio_programado)}). La tolerancia vencía a las {formatear_hora(hasta)}.")
    return resultado


def _turnos_por_operador(operador_ids, desde, hasta):
    """{operador_id: [(inicio, fin)]} de los turnos laborables entre dos fechas (incluye el día previo por turnos nocturnos)."""
    from datetime import datetime as dt
    ventanas = {}
    turnos = TurnoDia.objects.filter(
        operador_id__in=operador_ids, fecha__gte=desde - timedelta(days=1), fecha__lte=hasta,
        tipo_turno__activo=True, tipo_turno__es_descanso=False,
    ).select_related('tipo_turno')
    for t in turnos:
        tipo = t.tipo_turno
        if tipo.hora_inicio is None or tipo.hora_fin is None:
            inicio = timezone.make_aware(dt.combine(t.fecha, dt.min.time()))
            fin = inicio + timedelta(days=1)
        else:
            inicio = timezone.make_aware(dt.combine(t.fecha, tipo.hora_inicio))
            fin = timezone.make_aware(dt.combine(t.fecha, tipo.hora_fin))
            if fin <= inicio:
                fin += timedelta(days=1)  # turno nocturno
        ventanas.setdefault(t.operador_id, []).append((inicio, fin))
    return ventanas


def alertas_programacion(fases, ahora=None):
    """
    Revisa las fases pendientes (aún por iniciar) y devuelve {fase_id: [mensajes]} con lo que quedó mal
    tras reprogramaciones o ajustes automáticos:
      - operador asignado con otra tarea que se traslapa
      - operador sin turno laborable a la hora de inicio
      - material que, por el adelanto, debía estar listo antes de ahora
      - equipo reservado que se cruza con otra reserva, o que ya no está disponible o calificado
    """
    ahora = ahora or timezone.now()
    fases = [f for f in fases if f.estado == 'PENDIENTE' and f.inicio_programado and f.fin_programado and f.fin_programado > ahora]
    if not fases:
        return {}
    ids = [f.id for f in fases]
    asignaciones = list(AsignacionFaseOperador.objects.filter(fase_lote_id__in=ids).select_related('operador'))
    operador_ids = {a.operador_id for a in asignaciones}

    inicio_rango = min(f.inicio_programado for f in fases)
    fin_rango = max(f.fin_programado for f in fases)
    # Todas las asignaciones de esos operadores que tocan el rango, para detectar traslapes
    otras = list(AsignacionFaseOperador.objects.filter(
        operador_id__in=operador_ids, fase_lote__inicio_programado__lt=fin_rango, fase_lote__fin_programado__gt=inicio_rango,
    ).exclude(fase_lote__estado__in=['OMITIDA', 'COMPLETADA']).select_related('fase_lote', 'fase_lote__operacion_maestra', 'fase_lote__lote'))
    turnos = _turnos_por_operador(operador_ids, timezone.localtime(inicio_rango).date(), timezone.localtime(fin_rango).date())
    materiales = MaterialFase.objects.filter(fase_id__in=ids, activo=True).select_related('material')

    alertas = {}
    por_fase = {f.id: f for f in fases}
    for a in asignaciones:
        fase = por_fase[a.fase_lote_id]
        for o in otras:
            otra = o.fase_lote
            if o.operador_id != a.operador_id or otra.id == fase.id:
                continue
            if otra.inicio_programado < fase.fin_programado and otra.fin_programado > fase.inicio_programado:
                alertas.setdefault(fase.id, []).append(
                    f"👥 {a.operador.nombre} también está asignado a [{otra.operacion_maestra.identificador_paso}] "
                    f"{otra.nombre_tarea_dinamica or otra.operacion_maestra.nombre} (lote {otra.lote.identificador_lote}) "
                    f"de {formatear_hora(otra.inicio_programado)} a {formatear_hora(otra.fin_programado)}.")
        if not any(i <= fase.inicio_programado < f for i, f in turnos.get(a.operador_id, [])):
            alertas.setdefault(fase.id, []).append(f"🕒 {a.operador.nombre} no tiene turno a las {formatear_hora(fase.inicio_programado)}.")

    for m in materiales:
        fase = por_fase[m.fase_id]
        adelantada = fase.inicio_base_cpm and fase.inicio_programado < fase.inicio_base_cpm
        momento = fase.inicio_programado - timedelta(hours=m.anticipacion_horas or 0)
        if adelantada and m.anticipacion_horas and momento < ahora < fase.inicio_programado:
            alertas.setdefault(fase.id, []).append(
                f"📦 La actividad se adelantó: {m.material.nombre} debía estar listo desde las {formatear_hora(momento)} "
                f"({m.anticipacion_horas:g} h de anticipación).")

    for fase_id, mensajes in alertas_equipos(fases, ahora).items():
        alertas.setdefault(fase_id, []).extend(mensajes)
    return alertas


class ErrorMaterialFase(Exception):
    """Regla de negocio violada al modificar los materiales de una fase."""


def generar_materiales_lote(lote):
    """
    Copia los materiales de la receta a las fases ya guardadas del lote: los de la actividad
    a la fase principal y los marcados `MUESTREO` a cada subtarea de muestreo.
    """
    por_operacion = {}
    for mo in MaterialOperacion.objects.filter(operacion__proceso=lote.proceso_maestro_id).select_related('material'):
        por_operacion.setdefault(mo.operacion_id, []).append(mo)

    nuevos = []
    for fase in lote.fases.all():
        aplica = 'MUESTREO' if fase.es_subtarea_muestreo else 'ACTIVIDAD'
        for mo in por_operacion.get(fase.operacion_maestra_id, []):
            if mo.aplica_a == aplica:
                nuevos.append(MaterialFase(
                    fase=fase, material_id=mo.material_id, cantidad=mo.cantidad, unidad_medida=mo.material.unidad_medida,
                    cantidad_receta=mo.cantidad, anticipacion_horas=mo.anticipacion_horas,
                ))
    MaterialFase.objects.bulk_create(nuevos)
    return len(nuevos)


def _validar_fase_editable(fase):
    if fase.lote.estado in ('COMPLETADO', 'ABORTADO'):
        raise ErrorMaterialFase(f"El lote está {fase.lote.get_estado_display().lower()}; sus materiales ya no se modifican.")
    if fase.estado in ('COMPLETADA', 'OMITIDA'):
        raise ErrorMaterialFase(f"La fase está {fase.get_estado_display().lower()}; sus materiales ya no se modifican.")


def _validar_motivo(motivo):
    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise ErrorMaterialFase("Indique el motivo del cambio (mínimo 5 caracteres) para la trazabilidad GxP.")
    return motivo


def _validar_cantidad(cantidad):
    if cantidad is None or cantidad <= 0:
        raise ErrorMaterialFase("La cantidad debe ser mayor que cero.")


def ajustar_material_fase(material_fase, cantidad, anticipacion_horas, motivo):
    """Cambia cantidad y/o anticipación de un material del lote, conservando la cantidad de receta."""
    _validar_fase_editable(material_fase.fase)
    _validar_cantidad(cantidad)
    material_fase.cantidad = cantidad
    if anticipacion_horas is not None:
        material_fase.anticipacion_horas = anticipacion_horas
    material_fase.activo = True
    material_fase.motivo_ajuste = _validar_motivo(motivo)
    material_fase.ajustado_en = timezone.now()
    material_fase.save()
    return material_fase


def agregar_material_fase(fase, material, cantidad, anticipacion_horas, motivo):
    """Agrega a la fase un material que no venía en la receta (o reactiva uno retirado)."""
    _validar_fase_editable(fase)
    _validar_cantidad(cantidad)
    motivo = _validar_motivo(motivo)
    if not material.activo:
        raise ErrorMaterialFase(f"El material [{material.id}] está inactivo en el catálogo.")

    existente = MaterialFase.objects.filter(fase=fase, material=material).first()
    if existente and existente.activo:
        raise ErrorMaterialFase(f"[{material.id}] ya está en la fase; ajuste su cantidad en lugar de agregarlo.")
    if existente:
        # Al reactivarlo, la nueva cantidad se captura en la unidad vigente del catálogo
        existente.unidad_medida = material.unidad_medida
        return ajustar_material_fase(existente, cantidad, anticipacion_horas, motivo)
    return MaterialFase.objects.create(
        fase=fase, material=material, cantidad=cantidad, unidad_medida=material.unidad_medida,
        anticipacion_horas=anticipacion_horas or 0,
        motivo_ajuste=motivo, ajustado_en=timezone.now(),
    )


def retirar_material_fase(material_fase, motivo):
    """Baja lógica: el material deja de requerirse, pero el registro y su motivo se conservan."""
    _validar_fase_editable(material_fase.fase)
    material_fase.motivo_ajuste = _validar_motivo(motivo)
    material_fase.activo = False
    material_fase.ajustado_en = timezone.now()
    material_fase.save()
    return material_fase


def requerimientos_materiales(desde, hasta):
    """
    Materiales vigentes cuyo momento requerido (inicio programado de la fase menos la anticipación)
    cae en [desde, hasta). Sigue al forecast: si la fase se reprograma, el requerimiento se mueve.
    Excluye lotes abortados o archivados y fases completadas u omitidas.
    """
    base = MaterialFase.objects.filter(
        activo=True, fase__inicio_programado__isnull=False, fase__lote__archivado=False,
    ).exclude(fase__lote__estado='ABORTADO').exclude(fase__estado__in=['COMPLETADA', 'OMITIDA'])

    # La anticipación adelanta el requerimiento: se amplía la ventana de búsqueda por el máximo
    margen = timedelta(hours=base.aggregate(m=Max('anticipacion_horas'))['m'] or 0)
    candidatos = base.filter(
        fase__inicio_programado__gte=desde, fase__inicio_programado__lt=hasta + margen,
    ).select_related('material', 'fase__lote', 'fase__operacion_maestra')

    filas = [mf for mf in candidatos if desde <= mf.momento_requerido < hasta]
    filas.sort(key=lambda mf: (mf.momento_requerido, mf.material.nombre))
    return filas



# ==============================================================================
# EQUIPOS: COPIA POR LOTE, AJUSTES GxP, RESERVAS Y CAMBIO DURANTE LA EJECUCIÓN
# ==============================================================================

class ErrorEquipoFase(Exception):
    """Regla de negocio violada al modificar los equipos de una fase."""


def generar_equipos_lote(lote):
    """
    Copia los equipos de la receta a las fases ya guardadas del lote: los de la actividad a la fase
    principal y los marcados `MUESTREO` a cada subtarea de muestreo. Los equipos concretos se reservan después.
    """
    por_operacion = {}
    for eo in EquipoOperacion.objects.filter(operacion__proceso=lote.proceso_maestro_id):
        por_operacion.setdefault(eo.operacion_id, []).append(eo)

    nuevos = []
    for fase in lote.fases.all():
        aplica = 'MUESTREO' if fase.es_subtarea_muestreo else 'ACTIVIDAD'
        for eo in por_operacion.get(fase.operacion_maestra_id, []):
            if eo.aplica_a == aplica:
                nuevos.append(EquipoFase(
                    fase=fase, tipo_id=eo.tipo_id, cantidad=eo.cantidad, cantidad_receta=eo.cantidad,
                    horas_preparacion=eo.horas_preparacion, horas_limpieza=eo.horas_limpieza,
                ))
    EquipoFase.objects.bulk_create(nuevos)
    return len(nuevos)


def _validar_lote_vigente(fase):
    if fase.lote.estado in ('COMPLETADO', 'ABORTADO'):
        raise ErrorEquipoFase(f"El lote está {fase.lote.get_estado_display().lower()}; sus equipos ya no se modifican.")


def _validar_fase_por_iniciar(fase, que='sus equipos'):
    _validar_lote_vigente(fase)
    if fase.estado != 'PENDIENTE':
        detalle = " Para sustituir un equipo en uso, usa «Cambiar equipo»." if fase.estado == 'EN_PROGRESO' else ''
        raise ErrorEquipoFase(f"La fase está {fase.get_estado_display().lower()}; {que} ya no se modifican.{detalle}")


def _validar_motivo_equipo(motivo):
    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise ErrorEquipoFase("Indique el motivo del cambio (mínimo 5 caracteres) para la trazabilidad GxP.")
    return motivo


def _validar_horas_equipo(*horas):
    for h in horas:
        if h is not None and h < 0:
            raise ErrorEquipoFase("Las horas de preparación y limpieza no pueden ser negativas.")


def reservas_vigentes(equipo_fase):
    return [r for r in equipo_fase.reservas.all() if r.vigente]


def ajustar_equipo_fase(equipo_fase, cantidad, horas_preparacion, horas_limpieza, motivo):
    """Cambia la cantidad y/o las horas de preparación y limpieza de un requerimiento, conservando la de receta."""
    _validar_fase_por_iniciar(equipo_fase.fase)
    if cantidad is None or cantidad < 1:
        raise ErrorEquipoFase("La cantidad debe ser al menos 1.")
    _validar_horas_equipo(horas_preparacion, horas_limpieza)
    reservados = len(reservas_vigentes(equipo_fase)) if equipo_fase.activo else 0
    if cantidad < reservados:
        raise ErrorEquipoFase(f"Hay {reservados} equipo(s) reservado(s); libera alguno antes de bajar la cantidad a {cantidad}.")
    equipo_fase.cantidad = cantidad
    if horas_preparacion is not None:
        equipo_fase.horas_preparacion = horas_preparacion
    if horas_limpieza is not None:
        equipo_fase.horas_limpieza = horas_limpieza
    equipo_fase.activo = True
    equipo_fase.motivo_ajuste = _validar_motivo_equipo(motivo)
    equipo_fase.ajustado_en = timezone.now()
    equipo_fase.save()
    return equipo_fase


def agregar_equipo_fase(fase, tipo, cantidad, horas_preparacion, horas_limpieza, motivo):
    """Agrega a la fase un tipo de equipo que no venía en la receta (o reactiva uno retirado)."""
    _validar_fase_por_iniciar(fase)
    if not tipo.activo:
        raise ErrorEquipoFase(f"El tipo de equipo {tipo.nombre} está dado de baja.")
    existente = EquipoFase.objects.filter(fase=fase, tipo=tipo).first()
    if existente and existente.activo:
        raise ErrorEquipoFase(f"{tipo.nombre} ya está en la fase; ajusta su cantidad en lugar de agregarlo.")
    if existente:
        return ajustar_equipo_fase(existente, cantidad, horas_preparacion, horas_limpieza, motivo)
    if cantidad is None or cantidad < 1:
        raise ErrorEquipoFase("La cantidad debe ser al menos 1.")
    _validar_horas_equipo(horas_preparacion, horas_limpieza)
    return EquipoFase.objects.create(
        fase=fase, tipo=tipo, cantidad=cantidad, horas_preparacion=horas_preparacion or 0,
        horas_limpieza=horas_limpieza or 0, motivo_ajuste=_validar_motivo_equipo(motivo), ajustado_en=timezone.now(),
    )


def retirar_equipo_fase(equipo_fase, motivo):
    """Baja lógica del requerimiento; sus reservas se liberan con el mismo motivo."""
    _validar_fase_por_iniciar(equipo_fase.fase)
    motivo = _validar_motivo_equipo(motivo)
    equipo_fase.reservas.filter(activo=True, hasta__isnull=True).update(activo=False, motivo=f"Requerimiento retirado: {motivo}")
    equipo_fase.motivo_ajuste = motivo
    equipo_fase.activo = False
    equipo_fase.ajustado_en = timezone.now()
    equipo_fase.save()
    return equipo_fase


def reservas_que_ocupan(equipo, excluir_reserva_id=None):
    """Reservas que ocupan o ocuparon el equipo (excluye fases omitidas y lotes abortados o archivados)."""
    qs = ReservaEquipo.objects.filter(equipo=equipo, activo=True, equipo_fase__activo=True).exclude(
        equipo_fase__fase__estado='OMITIDA').exclude(equipo_fase__fase__lote__estado='ABORTADO').exclude(
        equipo_fase__fase__lote__archivado=True).select_related(
        'equipo_fase__fase__operacion_maestra', 'equipo_fase__fase__lote')
    if excluir_reserva_id:
        qs = qs.exclude(id=excluir_reserva_id)
    return qs


def buscar_conflicto_equipo(equipo, inicio, fin, excluir_reserva_id=None, excluir_equipo_fase_id=None):
    """Primera reserva del equipo cuyo tramo se traslapa con [inicio, fin), o None."""
    if inicio is None or fin is None:
        return None
    for reserva in reservas_que_ocupan(equipo, excluir_reserva_id):
        if excluir_equipo_fase_id and reserva.equipo_fase_id == excluir_equipo_fase_id:
            continue
        r_inicio, r_fin = reserva.ventana()
        if r_inicio and r_inicio < fin and r_fin > inicio:
            return reserva
    return None


def describir_reserva(reserva):
    fase = reserva.equipo_fase.fase
    r_inicio, r_fin = reserva.ventana()
    nombre = fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo else fase.operacion_maestra.nombre
    return (f"[{fase.operacion_maestra.identificador_paso}] {nombre} (lote {fase.lote.identificador_lote}) "
            f"de {formatear_hora(r_inicio)} a {formatear_hora(r_fin)}")


def motivo_no_disponible(equipo, inicio, fin, excluir_reserva_id=None, excluir_equipo_fase_id=None):
    """Por qué el equipo no sirve para ocuparlo en [inicio, fin): estado, calificación o un cruce; None si está libre."""
    motivo = equipo.motivo_no_reservable(fin)
    if motivo:
        return motivo
    conflicto = buscar_conflicto_equipo(equipo, inicio, fin, excluir_reserva_id, excluir_equipo_fase_id)
    if conflicto:
        return f"[{equipo.id}] está reservado para {describir_reserva(conflicto)}."
    return None


def equipos_candidatos(equipo_fase, desde=None):
    """Equipos activos del tipo pedido, cada uno con `motivo` (None si se puede reservar) para el selector."""
    from actividades.models import Equipo
    inicio, fin = equipo_fase.ventana_ocupacion()
    if desde and inicio and desde > inicio:
        inicio = desde
    ya = {r.equipo_id for r in reservas_vigentes(equipo_fase)}
    candidatos = []
    for equipo in Equipo.objects.filter(tipo_id=equipo_fase.tipo_id, activo=True).order_by('id'):
        motivo = "Ya está reservado en esta fase." if equipo.id in ya else motivo_no_disponible(
            equipo, inicio, fin, excluir_equipo_fase_id=equipo_fase.id)
        candidatos.append({'equipo': equipo, 'motivo': motivo})
    return candidatos


def reservar_equipo(equipo_fase, equipo):
    """Reserva un equipo concreto para el requerimiento de una fase por iniciar."""
    _validar_fase_por_iniciar(equipo_fase.fase, que='sus reservas')
    if not equipo_fase.activo:
        raise ErrorEquipoFase("Ese requerimiento de equipo está retirado.")
    if equipo.tipo_id != equipo_fase.tipo_id:
        raise ErrorEquipoFase(f"[{equipo.id}] es {equipo.tipo.nombre}; la fase pide {equipo_fase.tipo.nombre}.")
    vigentes = reservas_vigentes(equipo_fase)
    if any(r.equipo_id == equipo.id for r in vigentes):
        raise ErrorEquipoFase(f"[{equipo.id}] ya está reservado en esta fase.")
    if len(vigentes) >= equipo_fase.cantidad:
        raise ErrorEquipoFase(f"La fase ya tiene los {equipo_fase.cantidad} equipo(s) de {equipo_fase.tipo.nombre} que pide.")
    inicio, fin = equipo_fase.ventana_ocupacion()
    motivo = motivo_no_disponible(equipo, inicio, fin, excluir_equipo_fase_id=equipo_fase.id)
    if motivo:
        raise ErrorEquipoFase(motivo)
    return ReservaEquipo.objects.create(equipo_fase=equipo_fase, equipo=equipo)


def liberar_reserva(reserva, motivo=''):
    """Libera (baja lógica) la reserva de una fase por iniciar."""
    _validar_fase_por_iniciar(reserva.equipo_fase.fase, que='sus reservas')
    if not reserva.vigente:
        raise ErrorEquipoFase("Esa reserva ya no está vigente.")
    reserva.activo = False
    reserva.motivo = (motivo or '').strip()
    reserva.save(update_fields=['activo', 'motivo'])
    return reserva


def validar_cambio_equipo(reserva, nuevo_equipo, motivo, ahora=None):
    """Revisa que el equipo de una fase en ejecución se pueda sustituir; devuelve el motivo limpio o lanza ErrorEquipoFase."""
    ahora = ahora or timezone.now()
    fase = reserva.equipo_fase.fase
    _validar_lote_vigente(fase)
    if fase.estado != 'EN_PROGRESO':
        raise ErrorEquipoFase("Solo se cambia el equipo de una fase en ejecución; antes de iniciar, libera la reserva y reserva otro.")
    if not reserva.vigente:
        raise ErrorEquipoFase("Esa reserva ya no está vigente.")
    motivo = _validar_motivo_equipo(motivo)
    if nuevo_equipo.id == reserva.equipo_id:
        raise ErrorEquipoFase("Elige un equipo distinto al actual.")
    if nuevo_equipo.tipo_id != reserva.equipo_fase.tipo_id:
        raise ErrorEquipoFase(f"[{nuevo_equipo.id}] es {nuevo_equipo.tipo.nombre}; la fase pide {reserva.equipo_fase.tipo.nombre}.")
    if any(r.equipo_id == nuevo_equipo.id for r in reservas_vigentes(reserva.equipo_fase)):
        raise ErrorEquipoFase(f"[{nuevo_equipo.id}] ya está reservado en esta fase.")
    _, fin = reserva.equipo_fase.ventana_ocupacion()
    no_disponible = motivo_no_disponible(nuevo_equipo, ahora, fin, excluir_equipo_fase_id=reserva.equipo_fase_id)
    if no_disponible:
        raise ErrorEquipoFase(no_disponible)
    return motivo


def cambiar_equipo(reserva, nuevo_equipo, motivo, ahora=None):
    """
    Sustituye el equipo de una fase en ejecución: la reserva actual se cierra en este momento y el
    nuevo equipo queda reservado desde ahora hasta el fin (con limpieza). Devuelve la reserva nueva.
    """
    ahora = ahora or timezone.now()
    motivo = validar_cambio_equipo(reserva, nuevo_equipo, motivo, ahora)
    reserva.hasta, reserva.motivo = ahora, motivo
    reserva.save(update_fields=['hasta', 'motivo'])
    return ReservaEquipo.objects.create(equipo_fase=reserva.equipo_fase, equipo=nuevo_equipo, desde=ahora, motivo=motivo)


def bloqueo_por_equipo(fase, ahora=None):
    """Mensaje si a la fase le falta reservar equipo o un equipo reservado no está disponible, o None."""
    ahora = ahora or timezone.now()
    faltan = []
    for ef in fase.equipos.filter(activo=True).select_related('tipo').prefetch_related('reservas__equipo'):
        vigentes = reservas_vigentes(ef)
        if len(vigentes) < ef.cantidad:
            faltan.append(f"{ef.cantidad - len(vigentes)} {ef.tipo.nombre}")
        for r in vigentes:
            motivo = r.equipo.motivo_no_reservable(ahora)
            if motivo:
                return f"{motivo} Cámbialo en Planificación antes de iniciar."
    if faltan:
        return f"Falta reservar equipo: {', '.join(faltan)}. Resérvalo en Planificación antes de iniciar."
    return None


def alertas_equipos(fases, ahora=None):
    """{fase_id: [mensajes]} de reservas que, tras un ajuste, se cruzan con otra o ya no son válidas (estado o calificación)."""
    ahora = ahora or timezone.now()
    ids = [f.id for f in fases]
    alertas = {}
    reservas = ReservaEquipo.objects.filter(equipo_fase__fase_id__in=ids, equipo_fase__activo=True, activo=True,
                                            hasta__isnull=True).select_related('equipo', 'equipo_fase__fase__operacion_maestra', 'equipo_fase__fase__lote')
    for r in reservas:
        inicio, fin = r.ventana()
        if inicio is None:
            continue
        mensaje = r.equipo.motivo_no_reservable(fin)
        if not mensaje:
            conflicto = buscar_conflicto_equipo(r.equipo, inicio, fin, excluir_reserva_id=r.id, excluir_equipo_fase_id=r.equipo_fase_id)
            if conflicto:
                mensaje = f"[{r.equipo.id}] {r.equipo.nombre} se cruza con {describir_reserva(conflicto)}."
        if mensaje:
            alertas.setdefault(r.equipo_fase.fase_id, []).append(f"🏗️ {mensaje}")
    return alertas


def ocupacion_equipos(desde, hasta):
    """
    Para el monitor de equipos: tramos reservados que tocan [desde, hasta) y requerimientos de fases
    por iniciar o en curso que aún no tienen todos sus equipos reservados.
    """
    tramos = []
    reservas = ReservaEquipo.objects.filter(activo=True, equipo_fase__activo=True).exclude(
        equipo_fase__fase__estado='OMITIDA').exclude(equipo_fase__fase__lote__estado='ABORTADO').exclude(
        equipo_fase__fase__lote__archivado=True).select_related(
        'equipo__tipo', 'equipo_fase__tipo', 'equipo_fase__fase__operacion_maestra', 'equipo_fase__fase__lote')
    for r in reservas:
        inicio, fin = r.ventana()
        if inicio and inicio < hasta and fin > desde:
            tramos.append(r)

    pendientes = []
    requerimientos = EquipoFase.objects.filter(activo=True, fase__estado__in=['PENDIENTE', 'EN_PROGRESO'],
                                               fase__lote__archivado=False).exclude(fase__lote__estado='ABORTADO').select_related(
        'tipo', 'fase__operacion_maestra', 'fase__lote').prefetch_related('reservas')
    for ef in requerimientos:
        inicio, fin = ef.ventana_ocupacion()
        faltan = ef.cantidad - len(reservas_vigentes(ef))
        if faltan > 0 and inicio and inicio < hasta and fin > desde:
            pendientes.append((ef, faltan))
    return tramos, pendientes
