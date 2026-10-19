# procesos/services.py

from datetime import date, timedelta

from django.utils import timezone
from django.db.models import Count
from roster.models import TurnoDia, Operador
from .models import OperacionProceso, RequerimientoPersonalFase, FaseLote, AsignacionFaseOperador


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
                "tipo_equipo_requerido": op.tipo_equipo_requerido,
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
    enganchándolas a la ventana de su predecesora: la real si ya se completó, la programada si no.

    `nota_tarea` y `nota_muestreo` admiten los marcadores {paso} (predecesora inmediata) y {origen}.
    Devuelve la cantidad de fases actualizadas.
    """
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

