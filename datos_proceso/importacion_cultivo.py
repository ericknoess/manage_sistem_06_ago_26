# datos_proceso/importacion_cultivo.py — Importa el histórico de la app Cultivo (lotes de EPO) al MES.
#
# Cultivo guarda un registro por muestreo (cada 6 h) en `app_parametros_epo`, con tres formularios: P (parámetros
# del reactor, siempre), GyL (glucosa y lactato, cada 12 h) y C (cuenta celular, cada 24 h). Aquí:
#   1. Se crea (una vez) la receta «EPO – Cultivo (histórico)»: etapas PO4 y PR1, cada una con una incubación que
#      muestrea cada 6 h y las tres secciones; la curva Modelo_2024 de células y los indicadores del carnet
#      (ABC de células, % del ABC objetivo, gramos estimados).
#   2. Cada lote de Cultivo pasa a un lote del MES con sus incubaciones y un muestreo completado por registro, cuya
#      toma lleva los valores de las secciones registradas. La hora de la toma es la hora programada de Cultivo
#      (`fecha_obj`, Cultivo no guarda la real), así que las edades quedan iguales a las de Cultivo.
#   3. Volver a importar es seguro: los muestreos que ya existen no se tocan; solo se agregan los nuevos
#      (sirve para traer los lotes que siguen en curso en Cultivo).
# Lectura de Cultivo: `leer_cultivo` (PostgreSQL con psycopg2). El resto trabaja con diccionarios, sin conexión.

import csv
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction

from auditoria.services import registrar
from procesos.models import EtapaProceso, FaseLote, LoteProduccion, OperacionProceso, ProcesoMaestro
from .models import IndicadorProceso, ParametroProceso, ParametroSeccion, SeccionCaptura, TomaDatos, ValorParametro
from .planes import compactar_planes
from .services import _snapshot_parametro

NOMBRE_RECETA = 'EPO – Cultivo (histórico)'
ACTOR = 'Importación desde Cultivo'
FRECUENCIA_HORAS = 6

# (código en el MES, nombre, unidad, tipo) por columna de Cultivo. Unidades a confirmar en /parametros/.
PARAMETROS = {
    'volumen': ('volumen_reactor', 'Volumen del reactor', 'L', 'NUMERO'),
    'agitacion': ('agitacion', 'Agitación', 'rpm', 'NUMERO'),
    'temperatura': ('temperatura', 'Temperatura', '°C', 'NUMERO'),
    'oxigeno_disuelto': ('oxigeno_disuelto', 'Oxígeno disuelto', '%', 'NUMERO'),
    'ph_modulo': ('ph_modulo', 'pH (módulo)', '', 'NUMERO'),
    'rotametro_L': ('rotametro_l', 'Rotámetro L', '', 'NUMERO'),
    'rotametro_m': ('rotametro_m', 'Rotámetro m', '', 'NUMERO'),
    'rotametro_2': ('rotametro_2', 'Rotámetro 2', '', 'NUMERO'),
    'mezcla_aire': ('mezcla_aire', 'Mezcla: aire', '%', 'NUMERO'),
    'mezcla_co2': ('mezcla_co2', 'Mezcla: CO₂', '%', 'NUMERO'),
    'mezcla_nitrogeno': ('mezcla_n2', 'Mezcla: nitrógeno', '%', 'NUMERO'),
    'mezcla_oxigeno': ('mezcla_o2', 'Mezcla: oxígeno', '%', 'NUMERO'),
    'flujo_total_gases_directo': ('flujo_gases_directo', 'Flujo total de gases (directo)', '', 'NUMERO'),
    'flujo_total_gases_superficial': ('flujo_gases_superficial', 'Flujo total de gases (superficial)', '', 'NUMERO'),
    'flujo_aire_directo': ('flujo_aire_directo', 'Flujo de aire (directo)', '', 'NUMERO'),
    'flujo_co2_directo': ('flujo_co2_directo', 'Flujo de CO₂ (directo)', '', 'NUMERO'),
    'flujo_nitrogeno_directo': ('flujo_n2_directo', 'Flujo de nitrógeno (directo)', '', 'NUMERO'),
    'flujo_oxigeno_directo': ('flujo_o2_directo', 'Flujo de oxígeno (directo)', '', 'NUMERO'),
    'flujo_de_medio': ('flujo_medio', 'Flujo de medio', '', 'NUMERO'),
    'drenado_continuo': ('drenado_continuo', 'Drenado continuo', '', 'NUMERO'),
    'denadro_bach': ('drenado_batch', 'Drenado batch', '', 'NUMERO'),
    'vcg': ('espuma', 'Espuma', 'cm', 'NUMERO'),
    'state3': ('observaciones', 'Observaciones', '', 'TEXTO'),
    'ph_externo': ('ph_externo', 'pH externo', '', 'NUMERO'),
    'glucosa': ('glucosa', 'Glucosa', 'g/L', 'NUMERO'),
    'lactato': ('lactato', 'Lactato', 'g/L', 'NUMERO'),
    'osmolaridad': ('osmolalidad', 'Osmolalidad', 'mOsm/kg', 'NUMERO'),
    'celulas': ('celulas', 'Densidad celular', '10⁶ cél/mL', 'NUMERO'),
    'viabilidad': ('viabilidad', 'Viabilidad', '%', 'NUMERO'),
    'celulas_salida': ('celulas_por_campo', 'Células por campo', '', 'NUMERO'),
    'volumen_de_medio_colectado': ('volumen_medio_colectado', 'Volumen de medio colectado', '', 'NUMERO'),
    'lote_medio_de_cultivo': ('lote_medio', 'Lote de medio de cultivo', '', 'TEXTO'),
}

# (clave, nombre, columna de estatus en Cultivo, cada N horas, columnas) en el orden de los formularios de Cultivo
SECCIONES = [
    ('P', 'Parámetros del reactor', 'estatus_P', 0, [
        'volumen', 'agitacion', 'temperatura', 'oxigeno_disuelto', 'ph_modulo',
        'rotametro_L', 'rotametro_m', 'rotametro_2', 'mezcla_aire', 'mezcla_co2', 'mezcla_nitrogeno', 'mezcla_oxigeno',
        'flujo_total_gases_directo', 'flujo_total_gases_superficial', 'flujo_aire_directo', 'flujo_co2_directo',
        'flujo_nitrogeno_directo', 'flujo_oxigeno_directo', 'flujo_de_medio', 'drenado_continuo', 'denadro_bach', 'vcg',
        'state3']),
    ('GyL', 'Glucosa y lactato', 'estatus_GyL', 12, ['ph_externo', 'glucosa', 'lactato', 'osmolaridad']),
    ('C', 'Cuenta celular', 'estatus_C', 24, [
        'celulas', 'viabilidad', 'celulas_salida', 'volumen_de_medio_colectado', 'lote_medio_de_cultivo']),
]

# Etapas de Cultivo: (nombre, paso, actividad, duración nominal en h, columna de inicio en `app_lotes`)
ETAPAS = [
    ('PO4', 'T1', 'Propagación PO4', 168, 'fecha_inicio'),
    ('PR1', 'T2', 'Perfusión PR1', 1200, 'fecha_inicio_PR1'),
]

# Indicadores del carnet de Cultivo (views.py: ABC por trapecios contra la edad global; gramos = ABC / 1000 − k)
INDICADORES = [
    ('abc_cel', 'ABC de células', '10⁶ cél·h/mL', 1, 'AREA', ''),
    ('apego_cel', 'Apego a Modelo_2024', '%', 1, 'APEGO', ''),
    ('pct_abc', '% del ABC objetivo (25,000)', '%', 1, 'FORMULA', 'abc_cel / 25000 * 100'),
    ('gramos_obj', 'Gramos estimados (objetivo)', 'g', 1, 'FORMULA', 'abc_cel / 1000 - 5.5'),
    ('gramos_min', 'Gramos estimados (mínimo)', 'g', 1, 'FORMULA', 'abc_cel / 1000 - 7'),
    ('gramos_max', 'Gramos estimados (máximo)', 'g', 1, 'FORMULA', 'abc_cel / 1000 - 2.5'),
]

REGISTRADO = 'registrado'


class ErrorImportacion(Exception):
    pass


# ==============================================================================
# LECTURA DE CULTIVO
# ==============================================================================

COLUMNAS_LOTE = ['lote', 'status', 'fecha_inicio', 'fecha_inicio_PR1', 'fecha_termino', 'tipoReactor']
COLUMNAS_REGISTRO = (['id', 'lote_id', 'etapa', 'edad', 'muestra', 'fecha_obj', 'registro']
                     + [s[2] for s in SECCIONES] + list(PARAMETROS))


def leer_cultivo(dsn, lotes=None):
    """
    Lee los lotes de EPO y sus registros de la base de Cultivo (`dsn` de libpq; la contraseña, si hace falta, en PGPASSWORD).
    Devuelve {'lotes': [dict], 'registros': {lote: [dict]}} con los nombres de columna de Cultivo.
    """
    import psycopg2
    conexion = psycopg2.connect(dsn)
    try:
        conexion.set_session(readonly=True)
        with conexion.cursor() as cur:
            filtro, args = ('WHERE lote = ANY(%s)', [list(lotes)]) if lotes else ('', [])
            cur.execute(f'SELECT {", ".join(f"{chr(34)}{c}{chr(34)}" for c in COLUMNAS_LOTE)} FROM app_lotes {filtro} '
                        f'ORDER BY fecha_inicio, lote', args)
            datos_lotes = [dict(zip(COLUMNAS_LOTE, fila)) for fila in cur.fetchall()]
            cur.execute(f'SELECT {", ".join(f"{chr(34)}{c}{chr(34)}" for c in COLUMNAS_REGISTRO)} FROM app_parametros_epo '
                        f'WHERE lote_id = ANY(%s) ORDER BY lote_id, etapa, edad, id', [[l['lote'] for l in datos_lotes]])
            registros = defaultdict(list)
            for fila in cur.fetchall():
                registro = dict(zip(COLUMNAS_REGISTRO, fila))
                registros[registro['lote_id']].append(registro)
    finally:
        conexion.close()
    return {'lotes': datos_lotes, 'registros': dict(registros)}


def leer_curva_modelo(ruta, nombre='Modelo_2024'):
    """[[edad global h, células]] de la curva de referencia de Cultivo (`app/datos_modelo.csv`)."""
    curva = []
    with open(ruta, encoding='utf-8-sig', newline='') as archivo:
        for fila in csv.DictReader(archivo):
            if fila.get('lote') == nombre and fila.get('celulas') and fila.get('edad_global'):
                curva.append([float(fila['edad_global']), float(fila['celulas'])])
    return sorted(curva)


# ==============================================================================
# RECETA
# ==============================================================================

def _parametro(columna):
    codigo, nombre, unidad, tipo = PARAMETROS[columna]
    param, creado = ParametroProceso.objects.get_or_create(
        codigo=codigo, defaults={'nombre': nombre, 'unidad': unidad, 'tipo_dato': tipo, 'decimales': 2,
                                 'descripcion': f"Columna «{columna}» de Cultivo."})
    if param.tipo_dato != tipo or param.es_calculado:
        raise ErrorImportacion(f"El parámetro «{codigo}» ya existe en el catálogo con otro tipo; renómbralo antes de importar.")
    return param, creado


@transaction.atomic
def preparar_receta(curva=None):
    """
    Receta del histórico (la crea si no existe; si existe no la cambia). Devuelve (receta, estructura, creada), con
    estructura = {etapa: {'operacion', 'secciones': {clave: {columna: ParametroSeccion}}}}.
    """
    receta = ProcesoMaestro.objects.filter(nombre=NOMBRE_RECETA).first()
    creada = receta is None
    if creada:
        receta = ProcesoMaestro.objects.create(
            nombre=NOMBRE_RECETA,
            descripcion="Lotes de EPO importados de la app Cultivo (PO4 y PR1, muestreo cada 6 h). "
                        "La hora de cada toma es la hora programada en Cultivo.")
        parametros = {col: _parametro(col)[0] for col in PARAMETROS}
        anterior = None
        for orden, (etapa_nombre, paso, actividad, duracion, _) in enumerate(ETAPAS, start=1):
            etapa = EtapaProceso.objects.create(proceso=receta, nombre=etapa_nombre, orden=orden * 10)
            op = OperacionProceso.objects.create(
                proceso=receta, etapa=etapa, identificador_paso=paso, nombre=actividad, orden=orden,
                tipo_operacion='INCUBACION', duracion_horas=duracion, frecuencia_muestreo_horas=FRECUENCIA_HORAS,
                duracion_muestreo_horas=0.5, muestreo_inicial=True, captura_datos='MUESTREOS',
                predecesora=anterior, tipo_dependencia='FS', personal_requerido=1, ops_muestreo=1,
                edad_cero='INICIO', edad_cero_lote=(orden == 1))
            for orden_sec, (clave, nombre, _, cada, columnas) in enumerate(SECCIONES, start=1):
                seccion = SeccionCaptura.objects.create(
                    operacion=op, nombre=nombre, orden=orden_sec,
                    frecuencia='CADA_N' if cada else 'TODOS', cada_horas=cada,
                    muestra_fisica=(clave == 'GyL'), patron_codigo_muestra=f"{etapa_nombre}1-M{{n}}" if clave == 'GyL' else '')
                for orden_p, col in enumerate(columnas, start=1):
                    ParametroSeccion.objects.create(
                        seccion=seccion, parametro=parametros[col], orden=orden_p, obligatorio=False,
                        curva_referencia=(curva or []) if col == 'celulas' else [], eje_edad='LOTE')
            anterior = op
        for orden, (codigo, nombre, unidad, decimales, tipo, formula) in enumerate(INDICADORES, start=1):
            IndicadorProceso.objects.create(
                proceso=receta, codigo=codigo, nombre=nombre, unidad=unidad, decimales=decimales, orden=orden, tipo=tipo,
                parametro=None if tipo == 'FORMULA' else parametros['celulas'], formula=formula, eje_edad='LOTE')
        registrar(None, 'RECETA', 'IMPORTAR_RECETA', f"Receta «{NOMBRE_RECETA}» creada para el histórico de Cultivo",
                  objeto=receta, actor=ACTOR)
    return receta, _estructura(receta), creada


def _estructura(receta):
    por_codigo = {v[0]: col for col, v in PARAMETROS.items()}
    claves = {nombre: clave for clave, nombre, *_ in SECCIONES}
    estructura = {}
    operaciones = (OperacionProceso.objects.filter(proceso=receta, captura_datos='MUESTREOS')
                   .select_related('etapa').prefetch_related('secciones_captura__parametros__parametro'))
    for op in operaciones:
        secciones = {}
        for seccion in op.secciones_captura.all():
            clave = claves.get(seccion.nombre)
            if clave:
                secciones[clave] = {'nombre': seccion.nombre, 'usos': {
                    por_codigo[ps.parametro.codigo]: ps for ps in seccion.parametros.all() if ps.parametro.codigo in por_codigo}}
        estructura[op.etapa.nombre] = {'operacion': op, 'secciones': secciones}
    faltan = [e[0] for e in ETAPAS if e[0] not in estructura]
    if faltan:
        raise ErrorImportacion(f"A la receta «{NOMBRE_RECETA}» le falta la etapa {', '.join(faltan)} con su incubación.")
    return estructura


# ==============================================================================
# LOTES
# ==============================================================================

def _vacio(valor):
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _secciones_registradas(registro):
    """Claves de las secciones con datos en el registro (la P también si solo trae observaciones)."""
    claves = [clave for clave, _, estatus, *_ in SECCIONES if registro.get(estatus) == REGISTRADO]
    if 'P' not in claves and not _vacio(registro.get('state3')):
        claves.insert(0, 'P')
    return claves


def _peso(registro):
    return (len(_secciones_registradas(registro)), registro['id'])


def _valores(registro, claves):
    return {col: registro.get(col) for clave, _, _, _, columnas in SECCIONES if clave in claves
            for col in columnas if not _vacio(registro.get(col))}


def elegir_registros(registros):
    """
    Un registro por etapa y edad (Cultivo duplicó la PR1 de algunos lotes). Gana el que tiene más secciones registradas
    y, si empatan, el más reciente. Devuelve (elegidos, diferencias) con las diferencias de valores descartados.
    """
    grupos = defaultdict(list)
    for r in registros:
        if _secciones_registradas(r):
            grupos[(r['etapa'], r['edad'])].append(r)
    elegidos, diferencias = [], []
    for (etapa, edad), lista in grupos.items():
        lista.sort(key=_peso, reverse=True)
        ganador = lista[0]
        elegidos.append(ganador)
        valores_ganador = _valores(ganador, _secciones_registradas(ganador))
        for otro in lista[1:]:
            distintos = {col: [str(v), str(valores_ganador.get(col))]
                         for col, v in _valores(otro, _secciones_registradas(otro)).items() if valores_ganador.get(col) != v}
            if distintos:
                diferencias.append({'etapa': etapa, 'edad': edad, 'conservado': ganador['id'], 'descartado': otro['id'],
                                    'valores': distintos})
    elegidos.sort(key=lambda r: (r['fecha_obj'], r['id']))
    return elegidos, diferencias


def _plan(estructura_etapa, registro, claves, hora):
    """Plan de la toma: las secciones registradas con los parámetros que trae el registro."""
    secciones = []
    muestra = (registro.get('muestra') or '').strip()
    for clave, *_ in SECCIONES:
        if clave not in claves or clave not in estructura_etapa['secciones']:
            continue
        sec = estructura_etapa['secciones'][clave]
        parametros = [_snapshot_parametro(ps) for col, ps in sec['usos'].items() if not _vacio(registro.get(col))]
        if not parametros:
            continue
        ps0 = next(iter(sec['usos'].values()))
        secciones.append({
            'seccion': ps0.seccion_id, 'nombre': sec['nombre'], 'muestra_fisica': clave == 'GyL',
            'codigo_muestra': muestra if clave == 'GyL' and muestra and not muestra.startswith('Edad') else '',
            'parametros': parametros,
        })
    return {'hora': hora, 'secciones': secciones, 'origen': 'Cultivo', 'registro_cultivo': registro['id']} if secciones else {}


def _numero(valor):
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def estado_lote(datos_lote, corte):
    """En curso si Cultivo no lo finalizó y su término programado es posterior al último dato (`corte`)."""
    if datos_lote.get('status') != 'Finalizado' and datos_lote.get('fecha_termino') and corte \
            and datos_lote['fecha_termino'] > corte:
        return 'EN_PROGRESO'
    return 'COMPLETADO'


@transaction.atomic
def importar_lote(datos_lote, registros, receta, estructura, corte):
    """
    Importa (o completa) un lote. Devuelve {'lote', 'estado', 'nuevo', 'tomas', 'valores', 'diferencias', 'aviso'}.
    """
    codigo = datos_lote['lote']
    resultado = {'lote': codigo, 'nuevo': False, 'tomas': 0, 'valores': 0, 'diferencias': [], 'aviso': ''}
    elegidos, resultado['diferencias'] = elegir_registros(registros)
    if not elegidos:
        resultado['aviso'] = 'Sin registros capturados en Cultivo; no se importa.'
        return resultado
    if not datos_lote.get('fecha_inicio'):
        resultado['aviso'] = 'Sin fecha de inicio en Cultivo; no se importa.'
        return resultado

    estado = estado_lote(datos_lote, corte)
    resultado['estado'] = estado
    lote = LoteProduccion.objects.filter(identificador_lote=codigo).first()
    if lote and lote.proceso_maestro_id != receta.id:
        resultado['aviso'] = f"Ya existe en el MES con la receta «{lote.proceso_maestro}»; no se toca."
        return resultado
    if lote is None:
        lote = LoteProduccion.objects.create(identificador_lote=codigo, proceso_maestro=receta, estado=estado,
                                             fecha_inicio_planeada=datos_lote['fecha_inicio'])
        resultado['nuevo'] = True

    ultimo_por_etapa = {}
    for r in elegidos:
        ultimo_por_etapa[r['etapa']] = r['fecha_obj']

    # Incubaciones (una por etapa con datos o con fecha de inicio en Cultivo)
    principales = {f.operacion_maestra_id: f for f in lote.fases.filter(es_subtarea_muestreo=False)}
    for i, (etapa, _, _, _, columna_inicio) in enumerate(ETAPAS):
        op = estructura[etapa]['operacion']
        inicio = datos_lote.get(columna_inicio)
        if not inicio:
            continue
        siguiente = next((datos_lote.get(e[4]) for e in ETAPAS[i + 1:] if datos_lote.get(e[4])), None)
        if siguiente:
            fin, estado_fase = siguiente, 'COMPLETADA'
        elif estado == 'COMPLETADO':
            fin = datos_lote.get('fecha_termino') if datos_lote.get('status') == 'Finalizado' else None
            fin, estado_fase = (fin or ultimo_por_etapa.get(etapa) or inicio), 'COMPLETADA'
        else:
            fin, estado_fase = None, 'EN_PROGRESO'
        fase = principales.get(op.id) or FaseLote(lote=lote, operacion_maestra=op)
        fase.estado = estado_fase
        fase.inicio_base_cpm = fase.inicio_programado = fase.fecha_inicio_real = inicio
        fase.fin_programado = fase.fin_base_cpm = fin or inicio + timedelta(hours=op.duracion_horas)
        fase.fecha_fin_real = fin
        fase.save()

    # Muestreos con su toma (solo los que aún no existen)
    existentes = {(f.operacion_maestra_id, f.indice_muestreo): f
                  for f in lote.fases.filter(es_subtarea_muestreo=True).prefetch_related('tomas_datos')}
    nuevos = []
    for r in elegidos:
        if r['etapa'] not in estructura:
            continue
        op = estructura[r['etapa']]['operacion']
        indice = int(r['edad']) // FRECUENCIA_HORAS
        fase = existentes.get((op.id, indice))
        if fase and any(not t.adicional for t in fase.tomas_datos.all()):
            continue
        claves = _secciones_registradas(r)
        plan = _plan(estructura[r['etapa']], r, claves, int(r['edad']))
        if not plan:
            continue
        momento = r['fecha_obj']
        if fase is None:
            fase = FaseLote(lote=lote, operacion_maestra=op, es_subtarea_muestreo=True, indice_muestreo=indice,
                            nombre_tarea_dinamica=f"M-{int(r['edad'])}h - {op.nombre}")
        fase.estado = 'COMPLETADA'
        fase.inicio_base_cpm = fase.inicio_programado = fase.fecha_inicio_real = momento
        fase.fin_base_cpm = fase.fin_programado = fase.fecha_fin_real = momento + timedelta(hours=op.duracion_muestreo_horas)
        fase.plan_captura = plan
        nuevos.append((fase, r, plan, claves))
    compactos = compactar_planes([plan for _, _, plan, _ in nuevos])
    for (fase, *_), compacto in zip(nuevos, compactos):
        fase.plan_captura = compacto
        fase.save()

    nombre = lambda r: f"{(r.get('registro') or '').strip() or 'Sin nombre'} (Cultivo)"
    tomas = TomaDatos.objects.bulk_create([
        TomaDatos(fase=fase, momento=r['fecha_obj'], plan=compacto, registrado_por_nombre=nombre(r)[:150],
                  codigos_muestra={s['nombre']: s['codigo_muestra'] for s in plan['secciones'] if s['codigo_muestra']})
        for (fase, r, plan, _), compacto in zip(nuevos, compactos)])
    valores = []
    for toma, (fase, r, plan, _) in zip(tomas, nuevos):
        for seccion in plan['secciones']:
            for p in seccion['parametros']:
                crudo = r[PARAMETROS_POR_CODIGO[p['codigo']]]
                es_numero = p['tipo'] == 'NUMERO'
                valores.append(ValorParametro(
                    toma=toma, parametro_id=p['parametro'], seccion_nombre=seccion['nombre'],
                    valor_numero=_numero(crudo) if es_numero else None,
                    valor_texto='' if es_numero else str(crudo).strip()[:500],
                    limites=p['limites'], registrado_por_nombre=toma.registrado_por_nombre))
    ValorParametro.objects.bulk_create(valores, batch_size=2000)
    resultado['tomas'], resultado['valores'] = len(tomas), len(valores)

    estado_anterior = None if resultado['nuevo'] else lote.estado
    cambio_estado = estado_anterior is not None and estado_anterior != estado
    if cambio_estado:
        lote.estado = estado
        lote.save(update_fields=['estado', 'updated_at'])
    if tomas or cambio_estado:
        detalle = f"{len(tomas)} tomas y {len(valores)} valores importados de Cultivo"
        if resultado['diferencias']:
            detalle += f"; {len(resultado['diferencias'])} registros duplicados en Cultivo descartados"
        registrar(None, 'DATOS_PROCESO', 'IMPORTAR_HISTORICO', detalle[:500], objeto=lote, lote=lote, actor=ACTOR,
                  cambios={'estado': [estado_anterior, estado]} if cambio_estado else None)
    return resultado


PARAMETROS_POR_CODIGO = {v[0]: col for col, v in PARAMETROS.items()}


def fecha_corte(datos):
    """Hora del último dato capturado en Cultivo (equivale a la fecha del respaldo)."""
    fechas = [r['fecha_obj'] for lista in datos['registros'].values() for r in lista
              if r.get('fecha_obj') and _secciones_registradas(r)]
    return max(fechas) if fechas else None


def importar(datos, curva=None):
    """Importa todos los lotes de `datos` (ver `leer_cultivo`). Devuelve el resumen por lote."""
    receta, estructura, creada = preparar_receta(curva)
    corte = fecha_corte(datos)
    resultados = [importar_lote(dl, datos['registros'].get(dl['lote'], []), receta, estructura, corte)
                  for dl in datos['lotes']]
    return {'receta': receta, 'receta_creada': creada, 'corte': corte, 'lotes': resultados}
