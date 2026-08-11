# roster/services.py

from django.db import transaction
from datetime import timedelta
from .models import TurnoDia, SecuenciaRol

def expandir_secuencia(secuencia, fecha_inicio, fecha_fin):
    """
    Genera una lista de códigos de turno para el rango de fechas proporcionado
    basado en la secuencia de rol.
    """
    detalles = list(secuencia.detalles.all().order_by('orden'))
    # Convertimos la secuencia en una lista plana de turnos [M, M, M, M, M, OFF, OFF, ...]
    patron = []
    for detalle in detalles:
        patron.extend([detalle.codigo_turno] * detalle.dias)
    
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
            # Si estrategia es 'mantener', filtramos/validamos antes de crear
            if estrategia == 'mantener':
                if TurnoDia.objects.filter(operador=operador, fecha=item['fecha']).exists():
                    continue
            
            turnos_a_crear.append(TurnoDia(
                operador=operador,
                fecha=item['fecha'],
                codigo_turno=item['codigo']
            ))
            
    # Creamos todos los registros en lote para optimizar rendimiento
    TurnoDia.objects.bulk_create(turnos_a_crear)
    
    return len(turnos_a_crear)