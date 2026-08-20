# procesos/services.py

class CPMCalculatorService:
    """
    Servicio de dominio para calcular la Ruta Crítica (CPM), tiempos tempranos (ES, EF),
    tiempos tardíos (LS, LF) y holguras (Float/Slack) de las operaciones de un proceso maestro.
    """

    def __init__(self, operaciones):
        # operaciones: queryset o lista de objetos OperacionProceso ordenados o recuperados del proceso
        self.operaciones = list(operaciones)

    def calcular_cpm(self):
        if not self.operaciones:
            return {
                "tiempo_total": 0,
                "detalles": []
            }

        # Diccionarios de almacenamiento temporal para el grafo
        tiempos = {}
        
        # 1. FORWARD PASS (Paso hacia adelante: cálculo de ES y EF)
        for op in self.operaciones:
            es = 0.0
            ef = 0.0
            desfase = op.desfase_horas or 0.0
            duracion = op.duracion_horas or 0.0
            
            # Buscar predecesora si existe
            pred_id = op.predecesora_id
            if pred_id and pred_id in tiempos:
                pred_info = tiempos[pred_id]
                tipo_dep = op.tipo_dependencia or 'FS'
                
                if tipo_dep == 'SS':  # Start-to-Start
                    es = pred_info['es'] + desfase
                elif tipo_dep == 'OFFSET':  # Desfase fijo / Calendario absoluto
                    es = pred_info['es'] + desfase
                else:  # Por defecto Finish-to-Start (FS)
                    es = pred_info['ef'] + desfase
            
            ef = es + duracion
            tiempos[op.id] = {
                'es': es,
                'ef': ef,
                'duracion': duracion,
                'op': op
            }

        # Tiempo total del proyecto (el mayor EF de todas las operaciones)
        tiempo_total_proyecto = max([info['ef'] for info in tiempos.values()], default=0.0)

        # 2. BACKWARD PASS (Paso hacia atrás: cálculo de LS y LF)
        # Ordenamos inversamente para evaluar desde el final hacia el inicio
        ops_inverso = sorted(self.operaciones, key=lambda x: tiempos[x.id]['ef'], reverse=True)
        
        # Inicializamos LF tardíos con el tiempo total del proyecto
        for op in self.operaciones:
            tiempos[op.id]['lf'] = tiempo_total_proyecto
            tiempos[op.id]['ls'] = tiempo_total_proyecto - tiempos[op.id]['duracion']

        # Recálculo de backward pass considerando las sucesoras
        for op in reversed(self.operaciones):
            current_info = tiempos[op.id]
            # Buscar qué operaciones tienen a 'op' como predecesora
            sucesora_ops = [o for o in self.operaciones if o.predecesora_id == op.id]
            
            if sucesora_ops:
                min_ls_sucesora = float('inf')
                for suc in sucesora_ops:
                    suc_info = tiempos[suc.id]
                    tipo_dep = suc.tipo_dependencia or 'FS'
                    # Ajuste inverso según la dependencia
                    if tipo_dep == 'SS':
                        val = suc_info['ls'] - suc.desfase_horas
                    else:
                        val = suc_info['ls'] - suc.desfase_horas # Simplificación de desfase en backward
                    if val < min_ls_sucesora:
                        min_ls_sucesora = val
                current_info['lf'] = min(current_info['lf'], min_ls_sucesora)
                current_info['ls'] = current_info['lf'] - current_info['duracion']

        # 3. CÁLCULO DE HOLGURA Y RUTA CRÍTICA
        resultado_detalles = []
        for op in self.operaciones:
            info = tiempos[op.id]
            es = info['es']
            ef = info['ef']
            ls = info['ls']
            lf = info['lf']
            
            # Holgura Total (Total Float)
            holgura = round(ls - es, 2)
            # Si la holgura es 0 (o muy cercana a 0 por redondeo), es Ruta Crítica
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