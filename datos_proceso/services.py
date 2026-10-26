# datos_proceso/services.py — Lógica de captura de datos de proceso.
#
# Flujo:
#   1. Receta: cada actividad dice si captura datos (al completar o en cada muestreo) y en qué secciones.
#   2. Al instanciar el lote, `generar_plan_captura` copia a cada fase lo que le toca (FaseLote.plan_captura).
#   3. En planta se registra una toma por fase (`registrar_toma`); los calculados salen de sus fórmulas y
#      cada valor se marca si queda fuera de especificación o de alerta.
#   4. Corregir (`corregir_valor`) nunca edita: crea un valor nuevo que reemplaza al anterior, con motivo.
# Edades: `edades_cero` da la edad 0 de cada etapa y del lote (la actividad marcada como edad 0, real o estimada).

from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from procesos.models import FaseLote, OperacionProceso
from .formulas import ErrorFormula, evaluar, variables
from .models import ParametroProceso, SeccionCaptura, ParametroSeccion, TomaDatos, ValorParametro

LIMITES = ('especificacion_min', 'especificacion_max', 'alerta_min', 'alerta_max')
MOTIVO_MINIMO = 10


class ErrorCaptura(Exception):
    """Regla de captura incumplida; el mensaje se muestra tal cual."""


def texto_decimal(valor):
    """Decimal → texto sin ceros de sobra (None si no hay valor)."""
    if valor is None:
        return None
    texto = format(valor.normalize(), 'f')
    return '0' if texto in ('-0', '') else texto


# ==============================================================================
# CATÁLOGO: VALIDACIÓN DE FÓRMULAS
# ==============================================================================

def validar_formula_parametro(formula, codigo_propio, parametros_por_codigo=None):
    """
    Revisa la fórmula de un parámetro calculado: escritura, que use parámetros numéricos que existan
    y que no haya referencias circulares. Devuelve los códigos que usa; lanza ErrorFormula si no es válida.
    """
    if parametros_por_codigo is None:
        parametros_por_codigo = {p.codigo: p for p in ParametroProceso.objects.all()}
    usadas = variables(formula)
    for codigo in usadas:
        if codigo == codigo_propio:
            raise ErrorFormula("La fórmula no puede usar al mismo parámetro que calcula.")
        parametro = parametros_por_codigo.get(codigo)
        if not parametro:
            raise ErrorFormula(f"No existe el parámetro «{codigo}» en el catálogo.")
        if parametro.tipo_dato != 'NUMERO':
            raise ErrorFormula(f"«{codigo}» no es numérico; las fórmulas solo usan parámetros numéricos.")

    pendientes, vistos = list(usadas), set()
    while pendientes:
        codigo = pendientes.pop()
        if codigo in vistos:
            continue
        vistos.add(codigo)
        parametro = parametros_por_codigo.get(codigo)
        if parametro and parametro.es_calculado:
            try:
                internas = variables(parametro.formula)
            except ErrorFormula:
                continue
            if codigo_propio in internas:
                raise ErrorFormula(f"Referencia circular: «{codigo}» ya se calcula a partir de este parámetro.")
            pendientes.extend(internas)
    return usadas


# ==============================================================================
# RECETA → LOTE: PLAN DE CAPTURA POR FASE
# ==============================================================================

def _snapshot_parametro(ps):
    p = ps.parametro
    return {
        'parametro': p.id, 'codigo': p.codigo, 'nombre': p.nombre, 'unidad': p.unidad, 'tipo': p.tipo_dato,
        'decimales': p.decimales, 'opciones': list(p.opciones or []), 'formula': (p.formula or '').strip(),
        'obligatorio': bool(ps.obligatorio and not p.es_calculado),
        'limites': {campo: texto_decimal(getattr(ps, campo)) for campo in LIMITES},
        'referencia': {
            'objetivo': texto_decimal(ps.objetivo), 'curva': list(ps.curva_referencia or []), 'eje_edad': ps.eje_edad,
        },
    }


def _codigo_muestra(seccion, consecutivo, hora):
    if not seccion.muestra_fisica or not seccion.patron_codigo_muestra:
        return ''
    return (seccion.patron_codigo_muestra
            .replace('{n}', f"{consecutivo:02d}")
            .replace('{h}', '' if hora is None else str(hora)))


def plan_de_operacion(operacion, hora=None, consecutivos=None):
    """
    Lo que se captura en la actividad (`hora`=None) o en su muestreo de la hora `hora`:
    {'hora', 'secciones': [{seccion, nombre, muestra_fisica, codigo_muestra, parametros: [snapshot…]}]}; {} si nada.
    """
    secciones = []
    for seccion in operacion.secciones_captura.all():
        if not seccion.aplica_en(hora):
            continue
        consecutivo = (consecutivos or {}).get(seccion.id, 1)
        secciones.append({
            'seccion': seccion.id, 'nombre': seccion.nombre, 'muestra_fisica': seccion.muestra_fisica,
            'codigo_muestra': _codigo_muestra(seccion, consecutivo, hora),
            'parametros': [_snapshot_parametro(ps) for ps in seccion.parametros.all()],
        })
    return {'hora': hora, 'secciones': secciones} if secciones else {}


def hora_de_muestreo(fase):
    """Hora nominal del muestreo desde el inicio de su incubación (M-12h → 12); None si no es muestreo."""
    if not fase.es_subtarea_muestreo:
        return None
    return fase.indice_muestreo * (fase.operacion_maestra.frecuencia_muestreo_horas or 0)


def generar_plan_captura(lote):
    """Copia a cada fase del lote lo que debe capturar, según su actividad en la receta. Devuelve cuántas fases capturan."""
    operaciones = {op.id: op for op in OperacionProceso.objects.filter(proceso=lote.proceso_maestro)
                   .prefetch_related('secciones_captura__parametros__parametro')}
    fases = sorted(lote.fases.select_related('operacion_maestra'), key=lambda f: (f.operacion_maestra_id, f.indice_muestreo))
    consecutivos, actualizar = {}, []
    for fase in fases:
        op = operaciones.get(fase.operacion_maestra_id)
        if not op or op.captura_datos == 'NINGUNA':
            continue
        if (op.captura_datos == 'MUESTREOS') != fase.es_subtarea_muestreo:
            continue  # en muestreos captura cada muestreo; al completar, solo la actividad
        hora = hora_de_muestreo(fase) if fase.es_subtarea_muestreo else None
        numeros = {}
        for seccion in op.secciones_captura.all():
            if seccion.aplica_en(hora):
                consecutivos[seccion.id] = consecutivos.get(seccion.id, 0) + 1
                numeros[seccion.id] = consecutivos[seccion.id]
        plan = plan_de_operacion(op, hora, numeros)
        if plan:
            fase.plan_captura = plan
            actualizar.append(fase)
    FaseLote.objects.bulk_update(actualizar, ['plan_captura'])
    return len(actualizar)


@transaction.atomic
def clonar_secciones(operacion_origen, operacion_nueva):
    """Copia las secciones de captura de una actividad a otra (al clonar una receta)."""
    for seccion in operacion_origen.secciones_captura.all():
        parametros = list(seccion.parametros.all())
        seccion.pk = None
        seccion.operacion = operacion_nueva
        seccion.save()
        ParametroSeccion.objects.bulk_create([
            ParametroSeccion(seccion=seccion, parametro_id=ps.parametro_id, orden=ps.orden, obligatorio=ps.obligatorio,
                             objetivo=ps.objetivo, curva_referencia=list(ps.curva_referencia or []), eje_edad=ps.eje_edad,
                             **{campo: getattr(ps, campo) for campo in LIMITES})
            for ps in parametros
        ])


# ==============================================================================
# EDAD 0 DE ETAPAS Y DEL LOTE
# ==============================================================================

def _info_cero(hito, fases, sin_hito):
    if hito:
        op = hito.operacion_maestra
        if op.edad_cero == 'FIN':
            real, programado, momento_txt = hito.fecha_fin_real, hito.fin_programado, 'al completar'
        else:
            real, programado, momento_txt = hito.fecha_inicio_real, hito.inicio_programado, 'al iniciar'
        return {'momento': real or programado, 'estimada': real is None,
                'origen': f"[{op.identificador_paso}] {op.nombre} ({momento_txt})"}
    candidatos = [(f.fecha_inicio_real or f.inicio_programado, f.fecha_inicio_real is None)
                  for f in fases if (f.fecha_inicio_real or f.inicio_programado)]
    if not candidatos:
        return {'momento': None, 'estimada': True, 'origen': sin_hito}
    momento, estimada = min(candidatos, key=lambda c: c[0])
    return {'momento': momento, 'estimada': estimada, 'origen': sin_hito}


def edades_cero(lote, fases=None):
    """
    Edad 0 de cada etapa del lote y del lote completo: {'lote': info, <etapa_id>: info}, con
    info = {'momento', 'estimada' (aún no ocurre: se usa la hora programada), 'origen' (de dónde sale)}.
    Sin actividad marcada como edad 0, se usa el primer inicio de la etapa o del lote.
    """
    if fases is None:
        fases = list(lote.fases.select_related('operacion_maestra'))
    principales = [f for f in fases if not f.es_subtarea_muestreo]
    por_etapa = {}
    for f in principales:
        por_etapa.setdefault(f.operacion_maestra.etapa_id, []).append(f)
    resultado = {}
    for etapa_id, lista in por_etapa.items():
        hito = next((f for f in lista if f.operacion_maestra.edad_cero), None)
        resultado[etapa_id] = _info_cero(hito, lista, 'Primer inicio de la etapa (no hay actividad de edad 0)')
    hito_lote = next((f for f in principales if f.operacion_maestra.edad_cero and f.operacion_maestra.edad_cero_lote), None)
    resultado['lote'] = _info_cero(hito_lote, principales, 'Primer inicio del lote (no hay actividad de edad 0 del lote)')
    return resultado


def edad_horas(momento, cero):
    if not momento or not cero or not cero.get('momento'):
        return None
    return round((momento - cero['momento']).total_seconds() / 3600, 2)


# ==============================================================================
# VALORES: INTERPRETACIÓN, CÁLCULOS Y LÍMITES
# ==============================================================================

def _vacio(crudo):
    return crudo is None or (isinstance(crudo, str) and not crudo.strip())


def _redondear(valor, decimales):
    try:
        return valor.quantize(Decimal(1).scaleb(-int(decimales or 0)), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ErrorCaptura("El número es demasiado grande.")


def interpretar_valor(param, crudo):
    """(valor_numero, valor_texto) a partir de lo capturado; (None, '') si viene vacío. ErrorCaptura si no es válido."""
    if _vacio(crudo):
        return None, ''
    tipo, nombre = param['tipo'], param['nombre']
    if tipo == 'NUMERO':
        try:
            valor = Decimal(str(crudo).strip().replace(',', '.'))
        except InvalidOperation:
            raise ErrorCaptura(f"«{nombre}» debe ser un número.")
        if not valor.is_finite():
            raise ErrorCaptura(f"«{nombre}» debe ser un número.")
        valor = _redondear(valor, param['decimales'])
        if abs(valor) >= Decimal('1e14'):
            raise ErrorCaptura(f"«{nombre}» es demasiado grande.")
        return valor, ''
    if tipo == 'BOOLEANO':
        texto = str(crudo).strip().lower()
        if texto in ('true', 'si', 'sí', '1'):
            return None, 'Sí'
        if texto in ('false', 'no', '0'):
            return None, 'No'
        raise ErrorCaptura(f"«{nombre}»: responde Sí o No.")
    if tipo == 'OPCION':
        texto = str(crudo).strip()
        if texto not in param['opciones']:
            raise ErrorCaptura(f"«{nombre}»: elige una de las opciones ({', '.join(param['opciones'])}).")
        return None, texto
    return None, str(crudo).strip()[:500]


def evaluar_limites(limites, valor):
    """(fuera_especificacion, fuera_alerta) de un valor numérico contra sus límites (texto o None)."""
    if valor is None:
        return False, False

    def fuera(minimo, maximo):
        return ((minimo is not None and valor < Decimal(minimo)) or (maximo is not None and valor > Decimal(maximo)))

    limites = limites or {}
    return (fuera(limites.get('especificacion_min'), limites.get('especificacion_max')),
            fuera(limites.get('alerta_min'), limites.get('alerta_max')))


def calcular(parametros, capturados):
    """
    Valores de los parámetros calculados de `parametros` (snapshots) a partir de `capturados` {codigo: Decimal|None}.
    Un calculado puede usar a otro calculado. Devuelve {codigo: Decimal|None} (None si falta algún dato).
    """
    conocidos = {c: float(v) for c, v in capturados.items() if v is not None}
    pendientes = [p for p in parametros if p['formula']]
    resultados = {}
    for _ in range(len(pendientes)):
        hubo_cambio = False
        for p in pendientes:
            if p['codigo'] in resultados:
                continue
            try:
                r = evaluar(p['formula'], conocidos)
            except ErrorFormula:
                r = None
            if r is None:
                continue
            try:
                valor = _redondear(Decimal(repr(r)), p['decimales'])
            except (ErrorCaptura, InvalidOperation):
                continue
            resultados[p['codigo']] = valor
            conocidos[p['codigo']] = float(valor)
            hubo_cambio = True
        if not hubo_cambio:
            break
    return {p['codigo']: resultados.get(p['codigo']) for p in pendientes}


def _parametros_de_plan(plan):
    """[(nombre de sección, snapshot)] en el orden del formulario."""
    return [(s['nombre'], p) for s in (plan or {}).get('secciones', []) for p in s['parametros']]


def preparar_valores(plan, crudos):
    """
    Interpreta lo capturado ({parametro_id: valor}) y calcula. Devuelve (filas, faltantes):
    filas = [{seccion, param, valor_numero, valor_texto, calculado, fuera_especificacion, fuera_alerta}],
    faltantes = nombres de obligatorios sin valor. Lanza ErrorCaptura si algún valor no es válido.
    """
    crudos = {str(k): v for k, v in (crudos or {}).items()}
    pares = _parametros_de_plan(plan)
    filas, capturados, errores = [], {}, []
    for seccion, p in pares:
        if p['formula']:
            continue
        try:
            numero, texto = interpretar_valor(p, crudos.get(str(p['parametro'])))
        except ErrorCaptura as e:
            errores.append(str(e))
            continue
        if p['tipo'] == 'NUMERO':
            capturados[p['codigo']] = numero
        filas.append({'seccion': seccion, 'param': p, 'valor_numero': numero, 'valor_texto': texto, 'calculado': False})
    if errores:
        raise ErrorCaptura(' '.join(errores))

    calculados = calcular([p for _, p in pares], capturados)
    for seccion, p in pares:
        if p['formula']:
            filas.append({'seccion': seccion, 'param': p, 'valor_numero': calculados.get(p['codigo']), 'valor_texto': '', 'calculado': True})
    orden = {p['parametro']: i for i, (_, p) in enumerate(pares)}
    filas.sort(key=lambda f: orden[f['param']['parametro']])
    for fila in filas:
        fila['fuera_especificacion'], fila['fuera_alerta'] = evaluar_limites(fila['param']['limites'], fila['valor_numero'])
    faltantes = [f['param']['nombre'] for f in filas
                 if f['param']['obligatorio'] and f['valor_numero'] is None and not f['valor_texto']]
    return filas, faltantes


def _tiene_valor(fila):
    return fila['valor_numero'] is not None or bool(fila['valor_texto'])


def avisos_limites(filas):
    """Mensajes legibles de los valores fuera de especificación o de alerta."""
    avisos = []
    for f in filas:
        if not (f['fuera_especificacion'] or f['fuera_alerta']):
            continue
        p, lim = f['param'], f['param']['limites']
        valor = f"{texto_decimal(f['valor_numero'])} {p['unidad']}".strip()
        if f['fuera_especificacion']:
            rango = f"{lim.get('especificacion_min') or '−∞'} a {lim.get('especificacion_max') or '∞'}"
            avisos.append(f"🚨 {p['nombre']} = {valor}: fuera de especificación ({rango}).")
        else:
            rango = f"{lim.get('alerta_min') or '−∞'} a {lim.get('alerta_max') or '∞'}"
            avisos.append(f"⚠️ {p['nombre']} = {valor}: fuera del rango de alerta ({rango}).")
    return avisos


# ==============================================================================
# REGISTRO Y CORRECCIÓN EN PLANTA
# ==============================================================================

def _validar_lote_abierto(fase):
    lote = fase.lote
    if lote.archivado or lote.estado in ('COMPLETADO', 'ABORTADO'):
        raise ErrorCaptura(f"El lote {lote.identificador_lote} está {lote.get_estado_display().lower()}: sus datos ya no se modifican.")


def _validar_momento(momento):
    ahora = timezone.now()
    if momento is None:
        return ahora
    if momento > ahora + timedelta(minutes=5):
        raise ErrorCaptura("La hora de la toma no puede ser futura.")
    return momento


def _crear_valores(toma, filas, actor):
    return ValorParametro.objects.bulk_create([
        ValorParametro(
            toma=toma, parametro_id=f['param']['parametro'], seccion_nombre=f['seccion'][:100],
            valor_numero=f['valor_numero'], valor_texto=f['valor_texto'], calculado=f['calculado'],
            limites=f['param']['limites'], fuera_especificacion=f['fuera_especificacion'], fuera_alerta=f['fuera_alerta'],
            registrado_por_usuario=actor['usuario'], registrado_por_operador=actor['operador'],
            registrado_por_nombre=actor['nombre'][:150],
        )
        for f in filas if _tiene_valor(f)
    ])


def operacion_admite_adicional(fase):
    """Una muestra adicional se registra en la incubación (no en un muestreo) que captura en muestreos y está en curso."""
    op = fase.operacion_maestra
    return (not fase.es_subtarea_muestreo and op.captura_datos == 'MUESTREOS' and op.tipo_operacion == 'INCUBACION')


@transaction.atomic
def registrar_toma(fase, crudos, actor, momento=None):
    """
    Registra los datos del calendario de una fase (una sola vez). La fase debe estar en curso.
    `actor` = {'usuario', 'operador', 'nombre'}. Devuelve (toma, filas).
    """
    fase = FaseLote.objects.select_for_update().select_related('lote', 'operacion_maestra').get(pk=fase.pk)
    _validar_lote_abierto(fase)
    plan = fase.plan_captura or {}
    if not plan.get('secciones'):
        raise ErrorCaptura("Esta tarea no captura datos de proceso.")
    if fase.estado != 'EN_PROGRESO':
        raise ErrorCaptura("Los datos se capturan con la tarea en curso: iníciala primero.")
    if fase.tomas_datos.filter(adicional=False).exists():
        raise ErrorCaptura("Los datos de esta tarea ya se capturaron. Para cambiar un valor usa «Corregir».")
    momento = _validar_momento(momento)

    filas, faltantes = preparar_valores(plan, crudos)
    if faltantes:
        raise ErrorCaptura(f"Faltan datos obligatorios: {', '.join(faltantes)}.")
    toma = TomaDatos.objects.create(
        fase=fase, momento=momento, plan=plan,
        codigos_muestra={s['nombre']: s['codigo_muestra'] for s in plan['secciones'] if s.get('codigo_muestra')},
        registrado_por_usuario=actor['usuario'], registrado_por_operador=actor['operador'],
        registrado_por_nombre=actor['nombre'][:150],
    )
    _crear_valores(toma, filas, actor)
    return toma, filas


@transaction.atomic
def registrar_toma_adicional(fase, crudos, actor, motivo, momento=None, codigo_muestra=''):
    """Muestra fuera del calendario en una incubación en curso: pide motivo; se capturan todas sus secciones (ninguna obligatoria)."""
    fase = FaseLote.objects.select_for_update().select_related('lote', 'operacion_maestra').get(pk=fase.pk)
    _validar_lote_abierto(fase)
    if not operacion_admite_adicional(fase):
        raise ErrorCaptura("Las muestras adicionales se registran en una incubación que captura datos en sus muestreos.")
    if fase.estado != 'EN_PROGRESO':
        raise ErrorCaptura("La incubación debe estar en curso para registrar una muestra adicional.")
    motivo = (motivo or '').strip()
    if len(motivo) < MOTIVO_MINIMO:
        raise ErrorCaptura(f"Escribe por qué se toma la muestra adicional (mínimo {MOTIVO_MINIMO} caracteres).")
    momento = _validar_momento(momento)

    op = OperacionProceso.objects.prefetch_related('secciones_captura__parametros__parametro').get(pk=fase.operacion_maestra_id)
    plan = plan_de_operacion(op, None)
    if not plan:
        raise ErrorCaptura("La actividad no tiene secciones de captura.")
    for seccion in plan['secciones']:
        seccion['codigo_muestra'] = ''
        for p in seccion['parametros']:
            p['obligatorio'] = False
    filas, _ = preparar_valores(plan, crudos)
    if not any(_tiene_valor(f) and not f['calculado'] for f in filas):
        raise ErrorCaptura("Captura al menos un valor.")
    codigo = (codigo_muestra or '').strip()[:60]
    toma = TomaDatos.objects.create(
        fase=fase, momento=momento, adicional=True, motivo=motivo, plan=plan,
        codigos_muestra={'Muestra adicional': codigo} if codigo else {},
        registrado_por_usuario=actor['usuario'], registrado_por_operador=actor['operador'],
        registrado_por_nombre=actor['nombre'][:150],
    )
    _crear_valores(toma, filas, actor)
    return toma, filas


def _snapshot_en_toma(toma, parametro_id):
    for nombre, p in _parametros_de_plan(toma.plan):
        if p['parametro'] == parametro_id:
            return nombre, p
    return None, None


def _nuevo_valor(toma, anterior, seccion, param, numero, texto, calculado, motivo, actor):
    fuera_esp, fuera_alerta = evaluar_limites(param['limites'], numero)
    nuevo = ValorParametro.objects.create(
        toma=toma, parametro_id=param['parametro'], seccion_nombre=(seccion or '')[:100],
        valor_numero=numero, valor_texto=texto, calculado=calculado, limites=param['limites'],
        fuera_especificacion=fuera_esp, fuera_alerta=fuera_alerta, reemplaza=anterior, motivo_correccion=motivo,
        registrado_por_usuario=actor['usuario'], registrado_por_operador=actor['operador'],
        registrado_por_nombre=actor['nombre'][:150],
    )
    if anterior:
        anterior.vigente = False
        anterior.save(update_fields=['vigente'])
    return nuevo


def _texto_valor(numero, texto):
    return texto_decimal(numero) if numero is not None else (texto or None)


@transaction.atomic
def corregir_valor(toma, parametro_id, crudo, motivo, actor):
    """
    Corrige (o agrega, si faltaba) el valor de un parámetro capturado en una toma. El valor anterior queda
    como historial (`vigente=False`) y los calculados que dependen de él se recalculan.
    Devuelve {codigo: [antes, después]} de todo lo que cambió.
    """
    toma = TomaDatos.objects.select_related('fase__lote', 'fase__operacion_maestra').get(pk=toma.pk)
    _validar_lote_abierto(toma.fase)
    motivo = (motivo or '').strip()
    if len(motivo) < MOTIVO_MINIMO:
        raise ErrorCaptura(f"Escribe el motivo de la corrección (mínimo {MOTIVO_MINIMO} caracteres).")
    seccion, param = _snapshot_en_toma(toma, int(parametro_id))
    if not param:
        raise ErrorCaptura("Ese parámetro no se capturó en esta toma.")
    if param['formula']:
        raise ErrorCaptura(f"«{param['nombre']}» es calculado: corrige los valores con que se calcula.")

    vigentes = {v.parametro_id: v for v in toma.valores.select_for_update().filter(vigente=True)}
    anterior = vigentes.get(param['parametro'])
    numero, texto = interpretar_valor(param, crudo)
    if numero is None and not texto:
        if param['obligatorio']:
            raise ErrorCaptura(f"«{param['nombre']}» es obligatorio: no se puede dejar vacío.")
        if not anterior:
            raise ErrorCaptura("Captura el valor que falta.")
    antes = _texto_valor(anterior.valor_numero, anterior.valor_texto) if anterior else None
    despues = _texto_valor(numero, texto)
    if antes == despues:
        raise ErrorCaptura("El valor es igual al actual.")

    cambios = {param['codigo']: [antes, despues]}
    nuevo = _nuevo_valor(toma, anterior, seccion, param, numero, texto, False, motivo, actor)
    vigentes[param['parametro']] = nuevo

    # Recalcula los parámetros calculados de la toma con los valores vigentes
    pares = _parametros_de_plan(toma.plan)
    capturados = {p['codigo']: vigentes[p['parametro']].valor_numero
                  for _, p in pares if p['tipo'] == 'NUMERO' and not p['formula'] and p['parametro'] in vigentes}
    recalculados = calcular([p for _, p in pares], capturados)
    for nombre_seccion, p in pares:
        if not p['formula']:
            continue
        previo = vigentes.get(p['parametro'])
        valor = recalculados.get(p['codigo'])
        if (previo.valor_numero if previo else None) == valor:
            continue
        _nuevo_valor(toma, previo, nombre_seccion, p, valor, '', True,
                     f"Recalculado por la corrección de «{param['nombre']}»: {motivo}", actor)
        cambios[p['codigo']] = [texto_decimal(previo.valor_numero) if previo else None, texto_decimal(valor)]
    return cambios


# ==============================================================================
# CONSULTA
# ==============================================================================

def toma_del_calendario(fase):
    return next((t for t in fase.tomas_datos.all() if not t.adicional), None)


def resumen_captura(fase):
    """Qué pide la fase y si ya se capturó (para tarjetas y tablas); None si no captura datos."""
    plan = fase.plan_captura or {}
    if not plan.get('secciones'):
        return None
    obligatorios = sum(1 for s in plan['secciones'] for p in s['parametros'] if p['obligatorio'])
    return {
        'requerida': obligatorios > 0, 'capturada': toma_del_calendario(fase) is not None,
        'secciones': [s['nombre'] for s in plan['secciones']], 'obligatorios': obligatorios,
    }


def datos_pendientes(fase):
    """Mensaje si la fase no puede completarse porque faltan sus datos obligatorios; None si puede."""
    resumen = resumen_captura(fase)
    if resumen and resumen['requerida'] and not resumen['capturada']:
        return f"Captura los datos de proceso ({', '.join(resumen['secciones'])}) antes de completar la tarea."
    return None


def _quien(registro):
    return registro.registrado_por_nombre


def serializar_toma(toma, ceros, etapa_id, referencias=None):
    """`referencias` {parametro_id: referencia} se usa si la toma se registró antes de configurar el valor esperado."""
    valores = sorted(toma.valores.all(), key=lambda v: v.id)
    por_parametro = {}
    for v in valores:
        por_parametro.setdefault(v.parametro_id, []).append(v)
    filas = []
    for seccion, p in _parametros_de_plan(toma.plan):
        versiones = por_parametro.get(p['parametro'], [])
        vigente = next((v for v in versiones if v.vigente), None)
        filas.append({
            'parametro': p['parametro'], 'codigo': p['codigo'], 'nombre': p['nombre'], 'unidad': p['unidad'],
            'tipo': p['tipo'], 'decimales': p['decimales'], 'opciones': p['opciones'], 'seccion': seccion,
            'calculado': bool(p['formula']), 'obligatorio': p['obligatorio'], 'limites': p['limites'],
            'referencia': p.get('referencia') or (referencias or {}).get(p['parametro']) or {},
            'valor_id': vigente.id if vigente else None,
            'valor': _texto_valor(vigente.valor_numero, vigente.valor_texto) if vigente else None,
            'fuera_especificacion': bool(vigente and vigente.fuera_especificacion),
            'fuera_alerta': bool(vigente and vigente.fuera_alerta),
            'corregido': bool(vigente and vigente.reemplaza_id),
            'historial': [{
                'valor': _texto_valor(v.valor_numero, v.valor_texto), 'vigente': v.vigente,
                'registrado_por': _quien(v), 'registrado_en': v.registrado_en, 'motivo': v.motivo_correccion,
            } for v in versiones],
        })
    return {
        'id': toma.id, 'momento': toma.momento, 'adicional': toma.adicional, 'motivo': toma.motivo,
        'codigos_muestra': toma.codigos_muestra, 'registrado_por': toma.registrado_por_nombre, 'creado_en': toma.creado_en,
        'edad_etapa_h': edad_horas(toma.momento, ceros.get(etapa_id)),
        'edad_lote_h': edad_horas(toma.momento, ceros.get('lote')),
        'valores': filas,
    }


def _cero_json(info):
    if not info:
        return None
    return {'momento': info['momento'], 'estimada': info['estimada'], 'origen': info['origen']}


def nombre_fase(fase):
    nombre = fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo and fase.nombre_tarea_dinamica else fase.operacion_maestra.nombre
    return f"[{fase.operacion_maestra.identificador_paso}] {nombre}"


def tendencias(fase, planes, ceros):
    """
    Historial de los parámetros numéricos de `planes` en la etapa de la fase (todas sus tareas del lote), para la
    gráfica de tendencia: {parametro_id: [{edad_etapa_h, edad_lote_h, valor, tarea, momento, adicional, toma,
    fuera_especificacion, fuera_alerta}]}, ordenado por momento. Solo valores vigentes.
    """
    ids = {p['parametro'] for plan in planes for _, p in _parametros_de_plan(plan) if p['tipo'] == 'NUMERO'}
    resultado = {str(i): [] for i in ids}
    if not ids:
        return resultado
    etapa_id = fase.operacion_maestra.etapa_id
    valores = (ValorParametro.objects
               .filter(toma__fase__lote_id=fase.lote_id, toma__fase__operacion_maestra__etapa_id=etapa_id,
                       parametro_id__in=ids, vigente=True, valor_numero__isnull=False)
               .select_related('toma__fase__operacion_maestra').order_by('toma__momento', 'id'))
    for v in valores:
        toma = v.toma
        resultado[str(v.parametro_id)].append({
            'edad_etapa_h': edad_horas(toma.momento, ceros.get(etapa_id)),
            'edad_lote_h': edad_horas(toma.momento, ceros.get('lote')),
            'valor': float(v.valor_numero), 'tarea': nombre_fase(toma.fase), 'momento': toma.momento,
            'adicional': toma.adicional, 'toma': toma.id,
            'fuera_especificacion': v.fuera_especificacion, 'fuera_alerta': v.fuera_alerta,
        })
    return resultado


def detalle_captura(fase):
    """Todo lo que necesita el formulario de captura de una fase."""
    lote = fase.lote
    ceros = edades_cero(lote)
    etapa_id = fase.operacion_maestra.etapa_id
    tomas = list(fase.tomas_datos.prefetch_related('valores').all())
    toma = next((t for t in tomas if not t.adicional), None)
    abierto = not (lote.archivado or lote.estado in ('COMPLETADO', 'ABORTADO'))
    plan = fase.plan_captura or {}
    plan_adicional = plan_de_operacion(fase.operacion_maestra, None) if operacion_admite_adicional(fase) else {}
    for seccion in plan_adicional.get('secciones', []):
        seccion['codigo_muestra'] = ''  # la muestra adicional lleva su propio código (opcional)
    referencias = {p['parametro']: p['referencia'] for pl in (plan_adicional, plan)
                   for _, p in _parametros_de_plan(pl) if p.get('referencia')}
    return {
        'fase': fase.id, 'tarea': nombre_fase(fase), 'estado': fase.estado,
        'lote': lote.identificador_lote, 'lote_id': lote.id,
        'etapa': fase.operacion_maestra.etapa.nombre if fase.operacion_maestra.etapa_id else 'Sin etapa',
        'plan': plan, 'hora_programada': plan.get('hora'),
        'edad_cero_etapa': _cero_json(ceros.get(etapa_id)), 'edad_cero_lote': _cero_json(ceros.get('lote')),
        'edad_ahora_etapa_h': edad_horas(timezone.now(), ceros.get(etapa_id)),
        'edad_ahora_lote_h': edad_horas(timezone.now(), ceros.get('lote')),
        'toma': serializar_toma(toma, ceros, etapa_id, referencias) if toma else None,
        'adicionales': [serializar_toma(t, ceros, etapa_id, referencias) for t in tomas if t.adicional],
        'puede_registrar': abierto and bool(plan.get('secciones')) and fase.estado == 'EN_PROGRESO' and toma is None,
        'puede_corregir': abierto,
        'admite_adicional': abierto and fase.estado == 'EN_PROGRESO' and operacion_admite_adicional(fase),
        'plan_adicional': plan_adicional,
        'tendencias': tendencias(fase, [plan, plan_adicional], ceros),
    }


def tabla_lote(lote):
    """
    Datos vigentes del lote, una fila por toma (para tablas y gráficas): etapa, actividad, momento, edades y valores.
    `parametros` lista las columnas en orden de aparición.
    """
    fases = list(lote.fases.select_related('operacion_maestra__etapa'))
    ceros = edades_cero(lote, fases)
    tomas = (TomaDatos.objects.filter(fase__lote=lote).select_related('fase__operacion_maestra__etapa')
             .prefetch_related('valores__parametro').order_by('momento', 'id'))
    columnas, filas = {}, []
    for toma in tomas:
        fase = toma.fase
        etapa = fase.operacion_maestra.etapa
        valores = {}
        for v in toma.valores.all():
            if not v.vigente:
                continue
            p = v.parametro
            columnas.setdefault(p.codigo, {'codigo': p.codigo, 'nombre': p.nombre, 'unidad': p.unidad, 'tipo': p.tipo_dato})
            valores[p.codigo] = {'valor': _texto_valor(v.valor_numero, v.valor_texto), 'calculado': v.calculado,
                                 'fuera_especificacion': v.fuera_especificacion, 'fuera_alerta': v.fuera_alerta,
                                 'corregido': bool(v.reemplaza_id)}
        filas.append({
            'toma': toma.id, 'fase': fase.id, 'tarea': nombre_fase(fase), 'adicional': toma.adicional,
            'etapa_id': etapa.id if etapa else None, 'etapa': etapa.nombre if etapa else 'Sin etapa',
            'momento': toma.momento, 'edad_etapa_h': edad_horas(toma.momento, ceros.get(etapa.id if etapa else None)),
            'edad_lote_h': edad_horas(toma.momento, ceros.get('lote')),
            'codigos_muestra': toma.codigos_muestra, 'valores': valores,
        })
    return {
        'lote': lote.identificador_lote, 'lote_id': lote.id,
        'edades_cero': {('lote' if k == 'lote' else str(k)): _cero_json(v) for k, v in ceros.items()},
        'parametros': list(columnas.values()), 'filas': filas,
    }
