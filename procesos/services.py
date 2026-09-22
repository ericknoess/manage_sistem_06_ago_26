# procesos/services.py

from datetime import date
from django.db.models import Count
from roster.models import TurnoDia, Operador
from .models import OperacionProceso, RequerimientoPersonalFase


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