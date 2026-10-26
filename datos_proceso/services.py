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
from django.db.models import Q
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


def clonar_indicadores(proceso_origen, proceso_nuevo, mapa_etapas):
    """Copia los indicadores de una receta a su clon (`mapa_etapas` = {etapa_id original: etapa nueva})."""
    from .models import IndicadorProceso
    copias = []
    for ind in IndicadorProceso.objects.filter(proceso=proceso_origen):
        ind.pk = None
        ind.proceso = proceso_nuevo
        ind.etapa = mapa_etapas.get(ind.etapa_id) if ind.etapa_id else None
        copias.append(ind)
    IndicadorProceso.objects.bulk_create(copias)


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
        resultado[str(v.parametro_id)].append(_punto(v, ceros))
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


# ==============================================================================
# ANÁLISIS: SERIES POR LOTE, CURVA ESPERADA E INDICADORES
# ==============================================================================
# Lo que hacía el "carnet" de Cultivo, configurable por receta: cada parámetro contra la edad y los indicadores
# (área bajo la curva por trapecios, apego a la curva esperada, gramos estimados con una fórmula, etc.).
# Los indicadores no se guardan: se calculan al consultar con los datos vigentes.

MAX_LOTES_ANALISIS = 200   # en la gráfica, hasta 8 lotes destacados llevan color; el resto va en gris


def _punto(v, ceros):
    toma = v.toma
    etapa_id = toma.fase.operacion_maestra.etapa_id
    return {
        'edad_etapa_h': edad_horas(toma.momento, ceros.get(etapa_id)),
        'edad_lote_h': edad_horas(toma.momento, ceros.get('lote')),
        'valor': float(v.valor_numero), 'tarea': nombre_fase(toma.fase), 'momento': toma.momento,
        'adicional': toma.adicional, 'toma': toma.id, 'etapa_id': etapa_id,
        'fuera_especificacion': v.fuera_especificacion, 'fuera_alerta': v.fuera_alerta,
    }


def fases_por_lote(lotes):
    """{lote_id: [fases]} de varios lotes en una sola consulta."""
    resultado = {lote.id: [] for lote in lotes}
    for fase in FaseLote.objects.filter(lote__in=lotes).select_related('operacion_maestra').defer('plan_captura'):
        resultado[fase.lote_id].append(fase)
    return resultado


def series_lotes(lotes, parametro_ids=None, etapa_id=None, fases=None):
    """
    Valores numéricos vigentes de varios lotes: {lote_id: {parametro_id: [punto…]}} en orden de toma, y las edades 0
    de cada lote {lote_id: ceros}. `etapa_id` limita a los datos de esa etapa. `fases` = fases_por_lote(lotes) (opcional).
    Usa .values() para que alcance con cientos de lotes.
    """
    lotes = list(lotes)
    fases = fases if fases is not None else fases_por_lote(lotes)
    ceros = {lote.id: edades_cero(lote, fases[lote.id]) for lote in lotes}
    filtro = Q(toma__fase__lote__in=lotes, vigente=True, valor_numero__isnull=False)
    if parametro_ids is not None:
        filtro &= Q(parametro_id__in=parametro_ids)
    if etapa_id:
        filtro &= Q(toma__fase__operacion_maestra__etapa_id=etapa_id)
    filas = (ValorParametro.objects.filter(filtro).order_by('toma__momento', 'id').values_list(
        'parametro_id', 'valor_numero', 'fuera_especificacion', 'fuera_alerta', 'toma_id', 'toma__momento', 'toma__adicional',
        'toma__fase__lote_id', 'toma__fase__operacion_maestra__etapa_id', 'toma__fase__es_subtarea_muestreo',
        'toma__fase__nombre_tarea_dinamica', 'toma__fase__operacion_maestra__nombre', 'toma__fase__operacion_maestra__identificador_paso'))
    series = {lote.id: {} for lote in lotes}
    for (pid, valor, fuera_esp, fuera_ale, toma_id, momento, adicional, lote_id, etapa, es_muestreo,
         nombre_dinamico, nombre_op, paso) in filas:
        cero = ceros[lote_id]
        series[lote_id].setdefault(pid, []).append({
            'edad_etapa_h': edad_horas(momento, cero.get(etapa)), 'edad_lote_h': edad_horas(momento, cero.get('lote')),
            'valor': float(valor), 'tarea': f"[{paso}] {nombre_dinamico if es_muestreo and nombre_dinamico else nombre_op}",
            'momento': momento, 'adicional': adicional, 'toma': toma_id, 'etapa_id': etapa,
            'fuera_especificacion': fuera_esp, 'fuera_alerta': fuera_ale,
        })
    return series, ceros


def _xy(puntos, eje):
    """[(edad, valor)] ordenado por edad, sin puntos sin edad (falta la edad 0)."""
    clave = 'edad_etapa_h' if eje == 'ETAPA' else 'edad_lote_h'
    return sorted((p[clave], p['valor']) for p in puntos if p[clave] is not None)


def area_trapecios(xy):
    """Área bajo la curva por trapecios (como Cultivo: solo tramos con edad creciente)."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(xy, xy[1:]):
        if x1 > x0:
            total += (x1 - x0) * (y0 + y1) / 2
    return total


def interpolar(curva, x):
    """Valor de la curva esperada en la edad x (lineal entre puntos; fuera del rango, el extremo más cercano)."""
    if x <= curva[0][0]:
        return curva[0][1]
    for (x0, y0), (x1, y1) in zip(curva, curva[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return curva[-1][1]


def area_curva_entre(curva, desde, hasta):
    """Área bajo la curva esperada entre dos edades."""
    if hasta <= desde:
        return 0.0
    cortes = [desde] + [x for x, _ in curva if desde < x < hasta] + [hasta]
    return area_trapecios([(x, interpolar(curva, x)) for x in cortes])


def referencias_receta(proceso, etapa_id=None):
    """
    Configuración de cada parámetro numérico de la receta (la primera actividad que lo captura; en la etapa si se indica):
    {parametro_id: {parametro, limites, referencia, etapa_id, orden}}.
    """
    usos = (ParametroSeccion.objects
            .filter(seccion__operacion__proceso=proceso, parametro__tipo_dato='NUMERO')
            .select_related('parametro', 'seccion__operacion')
            .order_by('seccion__operacion__etapa__orden', 'seccion__operacion__orden', 'seccion__operacion_id',
                      'seccion__orden', 'orden'))
    if etapa_id:
        usos = usos.filter(seccion__operacion__etapa_id=etapa_id)
    resultado = {}
    for ps in usos:
        actual = resultado.get(ps.parametro_id)
        if actual is None:
            snapshot = _snapshot_parametro(ps)
            snapshot['orden'] = len(resultado)
            snapshot['etapa_id'] = ps.seccion.operacion.etapa_id
            resultado[ps.parametro_id] = snapshot
        elif not actual['referencia']['curva'] and ps.curva_referencia:
            actual['referencia'] = _snapshot_parametro(ps)['referencia']  # la curva de otra actividad que sí la tiene
    return resultado


def estructura_receta(proceso, etapa_id=None):
    """
    Parámetros numéricos de la receta como en el diseñador: por etapa (en su orden) y, dentro, por actividad y sección.
    Devuelve [{etapa_id, etapa, bloques: [{titulo, parametros: [snapshot…]}]}]. Un parámetro aparece una vez por etapa
    (en la primera actividad que lo captura), con la configuración (límites, curva) de ese uso.
    """
    usos = (ParametroSeccion.objects
            .filter(seccion__operacion__proceso=proceso, parametro__tipo_dato='NUMERO')
            .select_related('parametro', 'seccion__operacion__etapa')
            .order_by('seccion__operacion__etapa__orden', 'seccion__operacion__etapa_id', 'seccion__operacion__orden',
                      'seccion__operacion_id', 'seccion__orden', 'seccion_id', 'orden'))
    if etapa_id:
        usos = usos.filter(seccion__operacion__etapa_id=etapa_id)
    etapas, vistos = [], set()
    for ps in usos:
        op = ps.seccion.operacion
        clave_etapa = op.etapa_id
        if not etapas or etapas[-1]['etapa_id'] != clave_etapa:
            etapas.append({'etapa_id': clave_etapa, 'etapa': op.etapa.nombre if op.etapa_id else 'Sin etapa', 'bloques': []})
        if (clave_etapa, ps.parametro_id) in vistos:
            continue
        vistos.add((clave_etapa, ps.parametro_id))
        titulo = f"[{op.identificador_paso}] {op.nombre} · {ps.seccion.nombre}"
        bloques = etapas[-1]['bloques']
        if not bloques or bloques[-1]['titulo'] != titulo:
            bloques.append({'titulo': titulo, 'parametros': []})
        bloques[-1]['parametros'].append(_snapshot_parametro(ps))
    return etapas


def curva_del_lote(lote, parametro_id, etapa_id=None, fases=None):
    """
    Curva esperada y eje de un parámetro tal como se copiaron al lote; ([], 'LOTE') si no tiene.
    Lee los planes de las fases de a poco y se detiene en el primero que la trae (un lote largo tiene cientos).
    `fases` se acepta por compatibilidad; los planes siempre se leen de la base.
    """
    planes = lote.fases.order_by('inicio_programado', 'id')
    if etapa_id:
        planes = planes.filter(operacion_maestra__etapa_id=etapa_id)
    for plan in planes.values_list('plan_captura', flat=True).iterator(chunk_size=20):
        for _, p in _parametros_de_plan(plan):
            ref = p.get('referencia') or {}
            if p['parametro'] == parametro_id and ref.get('curva'):
                return ref['curva'], ref.get('eje_edad', 'LOTE')
    return [], 'LOTE'


def _redondear_float(valor, decimales):
    return None if valor is None else round(valor, int(decimales or 0))


def calcular_indicadores(lote, indicadores, series=None, fases=None):
    """
    Valor de cada indicador para un lote: {codigo: {'valor': float|None, 'nota': texto}}.
    `series` = {parametro_id: [punto…]} del lote (todas las etapas); si no se pasa, se consulta.
    """
    indicadores = list(indicadores)
    if series is None:
        series = series_lotes([lote])[0][lote.id]
    if fases is None:
        fases = list(lote.fases.select_related('operacion_maestra'))
    resultados = {}
    for ind in indicadores:
        if ind.tipo == 'FORMULA':
            continue
        puntos = [p for p in series.get(ind.parametro_id, []) if not ind.etapa_id or p['etapa_id'] == ind.etapa_id]
        curva, eje = ([], ind.eje_edad)
        if ind.tipo == 'APEGO':
            curva, eje = curva_del_lote(lote, ind.parametro_id, ind.etapa_id, fases)  # se integra contra la edad de la curva
        xy = _xy(puntos, eje)
        valor, nota = None, ''
        if not puntos:
            nota = 'Sin datos'
        elif ind.tipo == 'ULTIMO':
            valor = puntos[-1]['valor']
        elif ind.tipo == 'MAXIMO':
            valor = max(p['valor'] for p in puntos)
        elif len(xy) < 2:
            nota = 'Se necesitan al menos dos datos con edad'
        elif ind.tipo == 'AREA':
            valor = area_trapecios(xy)
        elif ind.tipo == 'APEGO':
            if not curva:
                nota = 'El parámetro no tiene curva esperada en la receta'
            else:
                esperada = area_curva_entre(curva, xy[0][0], xy[-1][0])
                if esperada:
                    valor = area_trapecios(xy) / esperada * 100
                    nota = f"Hasta {xy[-1][0]:.0f} h"
                else:
                    nota = 'La curva esperada da área cero en ese rango'
        resultados[ind.codigo] = {'valor': _redondear_float(valor, ind.decimales), 'nota': nota}

    # Fórmulas: pueden usar a otras fórmulas (se resuelven en orden de dependencia)
    conocidos = {c: r['valor'] for c, r in resultados.items() if r['valor'] is not None}
    pendientes = [ind for ind in indicadores if ind.tipo == 'FORMULA']
    for _ in range(len(pendientes)):
        avance = False
        for ind in pendientes:
            if ind.codigo in resultados:
                continue
            try:
                valor = evaluar(ind.formula, conocidos)
            except ErrorFormula:
                valor = None
            if valor is None:
                continue
            resultados[ind.codigo] = {'valor': _redondear_float(valor, ind.decimales), 'nota': ''}
            conocidos[ind.codigo] = resultados[ind.codigo]['valor']
            avance = True
        if not avance:
            break
    for ind in pendientes:
        resultados.setdefault(ind.codigo, {'valor': None, 'nota': 'Faltan los indicadores que usa'})
    return resultados


def validar_formula_indicador(formula, codigo_propio, otros):
    """
    Revisa la fórmula de un indicador: que use códigos de otros indicadores de la receta y sin referencias circulares.
    `otros` = {codigo: formula ('' si no es fórmula)}. Lanza ErrorFormula.
    """
    usadas = variables(formula)
    faltan = [c for c in usadas if c not in otros or c == codigo_propio]
    if codigo_propio in usadas:
        raise ErrorFormula("La fórmula no puede usar su propio indicador.")
    if faltan:
        raise ErrorFormula(f"No existen en esta receta los indicadores: {', '.join(faltan)}.")
    pendientes, vistos = list(usadas), set()
    while pendientes:
        codigo = pendientes.pop()
        if codigo in vistos:
            continue
        vistos.add(codigo)
        if otros.get(codigo):
            try:
                internas = variables(otros[codigo])
            except ErrorFormula:
                continue
            if codigo_propio in internas:
                raise ErrorFormula(f"Referencia circular: «{codigo}» ya se calcula a partir de este indicador.")
            pendientes.extend(internas)
    return usadas


def _compactar(puntos, tareas):
    """Puntos para el navegador en forma corta: [edad_lote, edad_etapa, valor, estado (0 ok, 1 alerta, 2 fuera),
    adicional (0/1), momento (segundos epoch), índice de la tarea en `tareas`]."""
    salida = []
    for p in puntos:
        tarea = tareas.setdefault(p['tarea'], len(tareas))
        estado = 2 if p['fuera_especificacion'] else 1 if p['fuera_alerta'] else 0
        salida.append([p['edad_lote_h'], p['edad_etapa_h'], p['valor'], estado, int(p['adicional']),
                       int(p['momento'].timestamp()), tarea])
    return salida


def analisis_lotes(proceso, lotes, etapa_id=None):
    """
    Datos de la pantalla de gráficas: por cada parámetro numérico de la receta (en la etapa), una serie por lote
    (puntos compactos, ver `_compactar`), con sus límites y curva esperada, y los indicadores de cada lote.
    """
    from .models import IndicadorProceso
    lotes = list(lotes)[:MAX_LOTES_ANALISIS]
    estructura = estructura_receta(proceso, etapa_id)
    fases = fases_por_lote(lotes)
    series, ceros = series_lotes(lotes, fases=fases)   # todas las etapas: los indicadores pueden ser de otra etapa
    indicadores = list(IndicadorProceso.objects.filter(proceso=proceso, activo=True).select_related('parametro', 'etapa'))

    tareas = {}
    parametros = []
    for grupo in estructura:
        for bloque in grupo['bloques']:
            for ref in bloque['parametros']:
                pid = ref['parametro']
                por_lote = {}
                for lote in lotes:
                    puntos = [p for p in series[lote.id].get(pid, []) if p['etapa_id'] == grupo['etapa_id']]
                    if puntos:
                        por_lote[str(lote.id)] = _compactar(puntos, tareas)
                parametros.append({
                    'clave': f"{grupo['etapa_id'] or 0}-{pid}", 'etapa_id': grupo['etapa_id'], 'etapa': grupo['etapa'],
                    'bloque': bloque['titulo'],
                    'parametro': pid, 'codigo': ref['codigo'], 'nombre': ref['nombre'], 'unidad': ref['unidad'],
                    'decimales': ref['decimales'], 'calculado': bool(ref['formula']), 'limites': ref['limites'],
                    'referencia': ref['referencia'], 'series': por_lote,
                })

    lotes_json, valores = [], {}
    ahora = timezone.now()
    for lote in lotes:
        valores[str(lote.id)] = calcular_indicadores(lote, indicadores, series[lote.id], fases[lote.id])
        abierto = lote.estado not in ('COMPLETADO', 'ABORTADO')
        lotes_json.append({
            'id': lote.id, 'identificador': lote.identificador_lote, 'estado': lote.estado,
            'estado_display': lote.get_estado_display(),
            'edad_actual_h': edad_horas(ahora, ceros[lote.id].get('lote')) if abierto else None,
        })
    return {
        'proceso': proceso.id, 'etapa': etapa_id, 'lotes': lotes_json, 'parametros': parametros,
        'etapas': [{'id': g['etapa_id'], 'nombre': g['etapa']} for g in estructura],
        'tareas': list(tareas),   # en orden de índice
        'indicadores': [{
            'codigo': i.codigo, 'nombre': i.nombre, 'unidad': i.unidad, 'tipo': i.tipo, 'tipo_display': i.get_tipo_display(),
            'decimales': i.decimales, 'meta_min': texto_decimal(i.meta_min), 'meta_max': texto_decimal(i.meta_max),
        } for i in indicadores],
        'valores_indicadores': valores,
    }


# ==============================================================================
# INFORMES (fase 3): datos de un lote o de varios, listos para PDF y Excel (datos_proceso/informes.py)
# ==============================================================================

def _huella(contenido):
    """SHA-256 de los datos del informe: dos impresiones con la misma huella traen exactamente los mismos datos."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(contenido, sort_keys=True, default=str, ensure_ascii=False).encode('utf-8')).hexdigest()


def correcciones_lote(lote, etapa_id=None):
    """Correcciones de datos de proceso del lote según la bitácora, con su firma electrónica."""
    from auditoria.models import RegistroAuditoria
    registros = (RegistroAuditoria.objects.filter(lote=lote, categoria='DATOS_PROCESO', accion='CORREGIR_DATO')
                 .select_related('fase__operacion_maestra', 'firma').order_by('fecha', 'id'))
    if etapa_id:
        registros = registros.filter(fase__operacion_maestra__etapa_id=etapa_id)
    salida = []
    for r in registros:
        firma = getattr(r, 'firma', None)
        salida.append({
            'fecha': r.fecha, 'tarea': nombre_fase(r.fase) if r.fase else '', 'actor': r.actor, 'motivo': r.motivo,
            'cambios': [{'codigo': c, 'antes': v[0], 'despues': v[1]} for c, v in (r.cambios or {}).items()
                        if isinstance(v, (list, tuple)) and len(v) == 2],
            'firma': {'nombre': firma.nombre_firmante, 'significado': firma.significado, 'fecha': firma.fecha,
                      'metodo': firma.get_metodo_display()} if firma else None,
        })
    return salida


MAX_COMBINADAS = 6
VISTAS_COMBINADAS = ('apiladas', 'superpuestas')


def _columna(snapshot):
    return {'parametro': snapshot['parametro'], 'codigo': snapshot['codigo'], 'nombre': snapshot['nombre'],
            'unidad': snapshot['unidad'], 'tipo': snapshot.get('tipo', 'NUMERO'), 'decimales': snapshot['decimales'],
            'calculado': bool(snapshot.get('formula')), 'limites': snapshot['limites'], 'referencia': snapshot['referencia']}


def _serie_informe(columna, tomas, eje):
    """Puntos (edad, valor, fuera de especificación) de una columna en unas tomas, contra la edad indicada."""
    clave = 'edad_etapa_h' if eje == 'ETAPA' else 'edad_lote_h'
    pid = columna['parametro']
    return sorted((t[clave], float(t['valores'][pid]['numero']), t['valores'][pid]['fuera_especificacion'])
                  for t in tomas if pid in t['valores'] and t['valores'][pid]['numero'] is not None and t[clave] is not None)


def datos_informe(lote, etapa_id=None, combinar=None, vista='apiladas'):
    """
    Todo lo que lleva el informe de un lote (o de una etapa), organizado como en el diseñador:
    `etapas` = [{etapa, columnas, tomas, bloques: [{titulo, series}]}] (cada etapa con sus columnas y sus gráficas por
    actividad · sección), más indicadores, fuera de límites, adicionales, correcciones firmadas y la huella SHA-256.
    `combinar` = claves "etapa-parámetro" (como en la pestaña Comparar) para la sección de gráficas combinadas, que se
    dibujan `vista` = 'apiladas' (mismo eje de edad del lote) o 'superpuestas' (cada una escalada a 0–100 %).
    """
    from .models import IndicadorProceso
    fases = list(lote.fases.select_related('operacion_maestra__etapa'))
    ceros = edades_cero(lote, fases)
    etapa = next((f.operacion_maestra.etapa for f in fases if f.operacion_maestra.etapa_id == etapa_id), None) if etapa_id else None
    estructura = estructura_receta(lote.proceso_maestro, etapa_id)

    tomas_qs = (TomaDatos.objects.filter(fase__lote=lote).select_related('fase__operacion_maestra__etapa')
                .prefetch_related('valores__parametro').order_by('momento', 'id'))
    if etapa_id:
        tomas_qs = tomas_qs.filter(fase__operacion_maestra__etapa_id=etapa_id)

    tomas, fuera, adicionales, extras = [], [], [], {}
    for toma in tomas_qs:
        fase = toma.fase
        etapa_toma = fase.operacion_maestra.etapa
        valores = {}
        for v in toma.valores.all():
            if not v.vigente:
                continue
            p = v.parametro
            valores[p.id] = {'texto': _texto_valor(v.valor_numero, v.valor_texto), 'numero': v.valor_numero,
                             'fuera_especificacion': v.fuera_especificacion, 'fuera_alerta': v.fuera_alerta,
                             'corregido': bool(v.reemplaza_id), 'calculado': v.calculado, 'limites': v.limites or {}}
            # Por si se capturó algo que ya no está en la receta (o no es numérico): también se informa
            extras.setdefault((etapa_toma.id if etapa_toma else None, p.id), {
                'parametro': p.id, 'codigo': p.codigo, 'nombre': p.nombre, 'unidad': p.unidad, 'tipo': p.tipo_dato,
                'decimales': p.decimales, 'calculado': v.calculado, 'limites': v.limites or {}, 'referencia': {}})
        fila = {
            'toma': toma.id, 'tarea': nombre_fase(fase), 'etapa': etapa_toma.nombre if etapa_toma else 'Sin etapa',
            'etapa_id': etapa_toma.id if etapa_toma else None, 'momento': toma.momento,
            'edad_lote_h': edad_horas(toma.momento, ceros.get('lote')),
            'edad_etapa_h': edad_horas(toma.momento, ceros.get(etapa_toma.id if etapa_toma else None)),
            'adicional': toma.adicional, 'motivo': toma.motivo,
            'muestras': ', '.join(f"{c}" for c in (toma.codigos_muestra or {}).values() if c),
            'registrado_por': toma.registrado_por_nombre, 'valores': valores,
        }
        tomas.append(fila)
        if toma.adicional:
            adicionales.append(fila)

    # Etapas como en el diseñador: columnas configuradas (en su orden) + lo capturado fuera de la receta
    etapas, nombres = [], {g['etapa_id']: g['etapa'] for g in estructura}
    ids_con_tomas = list(dict.fromkeys(t['etapa_id'] for t in tomas))
    orden_etapas = [g['etapa_id'] for g in estructura] + [e for e in ids_con_tomas if e not in nombres]
    for eid in orden_etapas:
        grupo = next((g for g in estructura if g['etapa_id'] == eid), {'bloques': []})
        tomas_etapa = [t for t in tomas if t['etapa_id'] == eid]
        columnas, vistos = [], set()
        for bloque in grupo['bloques']:
            for snap in bloque['parametros']:
                columnas.append(_columna(snap))
                vistos.add(snap['parametro'])
        for (e, pid), c in extras.items():
            if e == eid and pid not in vistos:
                columnas.append(c)
                vistos.add(pid)
        bloques = []
        for bloque in grupo['bloques']:
            series = []
            for snap in bloque['parametros']:
                col = next(c for c in columnas if c['parametro'] == snap['parametro'])
                eje = (col['referencia'] or {}).get('eje_edad', 'LOTE')
                puntos = _serie_informe(col, tomas_etapa, eje)
                if puntos:
                    series.append({'columna': col, 'eje': eje, 'puntos': puntos, 'etapa': nombres.get(eid, 'Sin etapa')})
            if series:
                bloques.append({'titulo': bloque['titulo'], 'series': series})
        if tomas_etapa or bloques:
            nombre = nombres.get(eid) or (tomas_etapa[0]['etapa'] if tomas_etapa else 'Sin etapa')
            etapas.append({'etapa_id': eid, 'etapa': nombre, 'columnas': columnas, 'tomas': tomas_etapa, 'bloques': bloques,
                           'edad_cero': ceros.get(eid)})

    # Fuera de límites (con el nombre de la columna de su etapa)
    for e in etapas:
        for t in e['tomas']:
            for pid, v in t['valores'].items():
                if not (v['fuera_especificacion'] or v['fuera_alerta']):
                    continue
                c = next((c for c in e['columnas'] if c['parametro'] == pid), None)
                lim = v['limites']
                rango = (lambda a, b: f"{lim.get(a) or '−∞'} a {lim.get(b) or '∞'}")
                fuera.append({'etapa': e['etapa'], 'tarea': t['tarea'], 'momento': t['momento'], 'edad_lote_h': t['edad_lote_h'],
                              'parametro': c['nombre'] if c else str(pid), 'unidad': c['unidad'] if c else '', 'valor': v['texto'],
                              'tipo': 'Especificación' if v['fuera_especificacion'] else 'Alerta',
                              'rango': rango('especificacion_min', 'especificacion_max') if v['fuera_especificacion']
                              else rango('alerta_min', 'alerta_max')})
    fuera.sort(key=lambda f: f['momento'])

    # Gráficas combinadas: varias columnas contra la edad del lote (como la pestaña Comparar)
    combinadas = []
    for clave in list(dict.fromkeys(combinar or []))[:MAX_COMBINADAS]:
        try:
            eid_txt, pid_txt = str(clave).split('-', 1)
            eid, pid = (int(eid_txt) or None), int(pid_txt)
        except ValueError:
            continue
        e = next((x for x in etapas if x['etapa_id'] == eid), None)
        col = next((c for c in (e['columnas'] if e else []) if c['parametro'] == pid and c['tipo'] == 'NUMERO'), None)
        if col:
            puntos = _serie_informe(col, e['tomas'], 'LOTE')
            if puntos:
                combinadas.append({'columna': col, 'etapa': e['etapa'], 'puntos': puntos})

    indicadores = [i for i in IndicadorProceso.objects.filter(proceso=lote.proceso_maestro, activo=True).select_related('parametro', 'etapa')
                   if not etapa_id or i.etapa_id in (None, etapa_id)]
    valores_ind = calcular_indicadores(lote, indicadores, fases=fases) if indicadores else {}
    lista_ind = []
    for i in indicadores:
        r = valores_ind.get(i.codigo, {'valor': None, 'nota': ''})
        meta_min = float(i.meta_min) if i.meta_min is not None else None
        meta_max = float(i.meta_max) if i.meta_max is not None else None
        estado = ''
        if r['valor'] is not None and (meta_min is not None or meta_max is not None):
            estado = ('Bajo meta' if meta_min is not None and r['valor'] < meta_min
                      else 'Sobre meta' if meta_max is not None and r['valor'] > meta_max else 'En meta')
        lista_ind.append({'codigo': i.codigo, 'nombre': i.nombre, 'unidad': i.unidad, 'tipo': i.get_tipo_display(),
                          'etapa': i.etapa.nombre if i.etapa_id else 'Todo el lote',
                          'valor': r['valor'], 'nota': r['nota'], 'meta_min': meta_min, 'meta_max': meta_max, 'estado': estado})

    correcciones = correcciones_lote(lote, etapa_id)
    contenido = {
        'lote': lote.identificador_lote, 'etapa': etapa_id,
        'tomas': [{**t, 'valores': {str(k): [v['texto'], v['corregido']] for k, v in t['valores'].items()}} for t in tomas],
        'correcciones': correcciones,
    }
    fechas_reales = [f.fecha_inicio_real for f in fases if f.fecha_inicio_real]
    fines = [f.fecha_fin_real for f in fases if f.fecha_fin_real]
    return {
        'lote': lote, 'receta': lote.proceso_maestro.nombre, 'etapa': etapa.nombre if etapa else None, 'etapa_id': etapa_id,
        'inicio_real': min(fechas_reales) if fechas_reales else None,
        'fin_real': max(fines) if lote.estado == 'COMPLETADO' and fines else None,
        'edad_cero_lote': ceros.get('lote'), 'edad_cero_etapa': ceros.get(etapa_id) if etapa_id else None,
        'etapas': etapas, 'tomas': tomas, 'fuera': fuera, 'adicionales': adicionales,
        'correcciones': correcciones, 'indicadores': lista_ind,
        'combinadas': combinadas, 'vista_combinadas': vista if vista in VISTAS_COMBINADAS else 'apiladas',
        'huella': _huella(contenido), 'generado': timezone.now(),
    }


def filas_lotes_excel(lotes, etapa_id=None):
    """
    Datos vigentes de varios lotes en formato largo (una fila por valor), para el Excel de los lotes elegidos.
    Devuelve (filas, indicadores_por_lote, definiciones de indicadores).
    """
    from .models import IndicadorProceso
    lotes = list(lotes)
    if not lotes:
        return [], {}, []
    fases = fases_por_lote(lotes)
    ceros = {l.id: edades_cero(l, fases[l.id]) for l in lotes}
    por_id = {l.id: l for l in lotes}
    filtro = Q(toma__fase__lote__in=lotes, vigente=True)
    if etapa_id:
        filtro &= Q(toma__fase__operacion_maestra__etapa_id=etapa_id)
    valores = (ValorParametro.objects.filter(filtro)
               .select_related('parametro', 'toma__fase__operacion_maestra__etapa')
               .order_by('toma__fase__lote_id', 'toma__momento', 'id'))
    filas = []
    for v in valores:
        toma, fase = v.toma, v.toma.fase
        etapa = fase.operacion_maestra.etapa
        lote = por_id[fase.lote_id]
        filas.append({
            'lote': lote.identificador_lote, 'estado': lote.get_estado_display(), 'etapa': etapa.nombre if etapa else '',
            'tarea': nombre_fase(fase), 'momento': toma.momento,
            'edad_lote_h': edad_horas(toma.momento, ceros[lote.id].get('lote')),
            'edad_etapa_h': edad_horas(toma.momento, ceros[lote.id].get(etapa.id if etapa else None)),
            'adicional': toma.adicional, 'muestras': ', '.join(c for c in (toma.codigos_muestra or {}).values() if c),
            'codigo': v.parametro.codigo, 'parametro': v.parametro.nombre, 'unidad': v.parametro.unidad,
            'numero': v.valor_numero, 'texto': v.valor_texto, 'calculado': v.calculado,
            'fuera_especificacion': v.fuera_especificacion, 'fuera_alerta': v.fuera_alerta,
            'corregido': bool(v.reemplaza_id), 'registrado_por': v.registrado_por_nombre,
        })
    proceso = lotes[0].proceso_maestro
    indicadores = [i for i in IndicadorProceso.objects.filter(proceso=proceso, activo=True).select_related('parametro', 'etapa')
                   if not etapa_id or i.etapa_id in (None, etapa_id)]
    series, _ = series_lotes(lotes, fases=fases)
    por_lote = {l.id: calcular_indicadores(l, indicadores, series[l.id], fases[l.id]) for l in lotes} if indicadores else {}
    return filas, por_lote, indicadores
