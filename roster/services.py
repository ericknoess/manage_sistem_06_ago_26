# roster/services.py

from django.db import transaction
from datetime import timedelta
from .models import TurnoDia, SecuenciaRol, TipoTurno

def expandir_secuencia(secuencia, fecha_inicio, fecha_fin):
    """
    Genera una lista de códigos de turno para el rango de fechas proporcionado
    basado en la secuencia de rol.
    """
    detalles = list(secuencia.detalles.all().order_by('orden'))
    # Convertimos la secuencia en una lista plana de turnos [M, M, M, M, M, OFF, OFF, ...]
    patron = []
    for detalle in detalles:
        codigo = detalle.tipo_turno_id if hasattr(detalle, 'tipo_turno_id') else str(detalle.tipo_turno)
        patron.extend([codigo] * detalle.dias)
    
    longitud_patron = len(patron)
    if longitud_patron == 0:
        return []

    resultados = []
    delta = (fecha_fin - fecha_inicio).days
    
    for i in range(delta + 1):
        fecha_actual = fecha_inicio + timedelta(days=i)
        # El índice se calcula mediante el módulo para que sea cíclico
        turno = patron[i % longitud_patron]
        resultados.append({'fecha': fecha_actual, 'codigo': turno})
        
    return resultados

@transaction.atomic
def aplicar_carga_masiva(operadores, secuencia, fecha_inicio, fecha_fin, estrategia='mantener'):
    """
    Ejecuta la carga masiva dentro de una transacción atómica.
    Estrategia 'mantener': no sobrescribe.
    Estrategia 'reemplazar': borra existentes y crea nuevos.
    """
    turnos_a_crear = []
    
    # Obtenemos los turnos generados por la secuencia
    plan_turnos = expandir_secuencia(secuencia, fecha_inicio, fecha_fin)
    
    for operador in operadores:
        if estrategia == 'reemplazar':
            # Eliminamos registros existentes en el rango
            TurnoDia.objects.filter(
                operador=operador, 
                fecha__gte=fecha_inicio, 
                fecha__lte=fecha_fin
            ).delete()
        
        for item in plan_turnos:
            # Si estrategia is 'mantener', filtramos/validamos antes de crear
            if estrategia == 'mantener':
                if TurnoDia.objects.filter(operador=operador, fecha=item['fecha']).exists():
                    continue
            
            # CORRECCIÓN: Resolvemos el objeto TipoTurno o su ID para asignarlo a tipo_turno_id
            codigo_turno = item['codigo']
            tipo_turno_obj = None
            if codigo_turno and str(codigo_turno).strip() != '':
                tipo_turno_obj, _ = TipoTurno.objects.get_or_create(
                    codigo=str(codigo_turno).upper().strip(),
                    defaults={
                        'nombre': f'Turno {str(codigo_turno).upper().strip()}',
                        'color_fondo': '#3b82f6',
                        'color_texto': '#ffffff',
                        'es_descanso': False,
                        'activo': True
                    }
                )

            turnos_a_crear.append(TurnoDia(
                operador=operador,
                fecha=item['fecha'],
                tipo_turno=tipo_turno_obj
            ))
            
    # Creamos todos los registros en lote para optimizar rendimiento
    if turnos_a_crear:
        TurnoDia.objects.bulk_create(turnos_a_crear)
    
    return len(turnos_a_crear)