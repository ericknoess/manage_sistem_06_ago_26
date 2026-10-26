# datos_proceso/serializers.py

import math
import re

from rest_framework import serializers

from .formulas import ErrorFormula
from .models import ParametroProceso, SeccionCaptura, ParametroSeccion
from .services import LIMITES, validar_formula_parametro

MAX_PUNTOS_CURVA = 500
PATRON_CODIGO = re.compile(r'^[a-z][a-z0-9_]{0,39}$')


class ParametroProcesoSerializer(serializers.ModelSerializer):
    tipo_dato_display = serializers.CharField(source='get_tipo_dato_display', read_only=True)
    es_calculado = serializers.BooleanField(read_only=True)
    variables = serializers.SerializerMethodField()
    usos_en_recetas = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ParametroProceso
        fields = ['id', 'codigo', 'nombre', 'unidad', 'tipo_dato', 'tipo_dato_display', 'decimales', 'opciones',
                  'formula', 'descripcion', 'activo', 'es_calculado', 'variables', 'usos_en_recetas']

    def get_variables(self, obj):
        if not obj.es_calculado:
            return []
        from .formulas import variables
        try:
            return variables(obj.formula)
        except ErrorFormula:
            return []

    def validate_codigo(self, valor):
        valor = (valor or '').strip()
        if self.instance and valor != self.instance.codigo:
            raise serializers.ValidationError("El código no se puede cambiar: lo usan fórmulas, recetas y datos capturados.")
        if not PATRON_CODIGO.match(valor):
            raise serializers.ValidationError(
                "Usa minúsculas, números y guion bajo, empezando con letra (ej. ph, glucosa, flujo_o2).")
        from .formulas import FUNCIONES
        if valor in FUNCIONES:
            raise serializers.ValidationError(f"«{valor}» es el nombre de una función de las fórmulas; elige otro código.")
        return valor

    def validate_decimales(self, valor):
        if valor > 6:
            raise serializers.ValidationError("Máximo 6 decimales.")
        return valor

    def validate(self, data):
        actual = lambda campo, defecto=None: data.get(campo, getattr(self.instance, campo, defecto))
        tipo = actual('tipo_dato', 'NUMERO')
        formula = (actual('formula', '') or '').strip()
        opciones = actual('opciones', []) or []

        if tipo == 'OPCION':
            opciones = [str(o).strip() for o in opciones if str(o).strip()]
            if len(opciones) < 2:
                raise serializers.ValidationError({'opciones': "Una lista de opciones necesita al menos dos opciones."})
            if len(set(opciones)) != len(opciones):
                raise serializers.ValidationError({'opciones': "Hay opciones repetidas."})
            data['opciones'] = opciones
        elif 'opciones' in data or (self.instance and self.instance.opciones):
            data['opciones'] = []

        if formula:
            if tipo != 'NUMERO':
                raise serializers.ValidationError({'formula': "Solo un parámetro numérico puede calcularse con fórmula."})
            try:
                validar_formula_parametro(formula, actual('codigo'))
            except ErrorFormula as e:
                raise serializers.ValidationError({'formula': str(e)})
            data['formula'] = formula

        if self.instance and self.instance.tipo_dato != tipo and self.instance.valores.exists():
            raise serializers.ValidationError({'tipo_dato': "Ya hay datos capturados con este parámetro: su tipo no se puede cambiar."})
        if self.instance and tipo != 'NUMERO' and self.instance.tipo_dato == 'NUMERO':
            usado_en = [p.codigo for p in ParametroProceso.objects.exclude(pk=self.instance.pk).exclude(formula='')
                        if self.instance.codigo in _variables_seguras(p.formula)]
            if usado_en:
                raise serializers.ValidationError({'tipo_dato': f"Lo usan las fórmulas de: {', '.join(usado_en)}; debe seguir siendo numérico."})
        return data


def _variables_seguras(formula):
    from .formulas import variables
    try:
        return variables(formula)
    except ErrorFormula:
        return []


class ParametroSeccionSerializer(serializers.ModelSerializer):
    parametro_codigo = serializers.CharField(source='parametro.codigo', read_only=True)
    parametro_nombre = serializers.CharField(source='parametro.nombre', read_only=True)
    unidad = serializers.CharField(source='parametro.unidad', read_only=True)
    tipo_dato = serializers.CharField(source='parametro.tipo_dato', read_only=True)
    es_calculado = serializers.BooleanField(source='parametro.es_calculado', read_only=True)
    parametro_activo = serializers.BooleanField(source='parametro.activo', read_only=True)

    class Meta:
        model = ParametroSeccion
        fields = ['id', 'parametro', 'parametro_codigo', 'parametro_nombre', 'unidad', 'tipo_dato', 'es_calculado',
                  'parametro_activo', 'orden', 'obligatorio', *LIMITES, 'objetivo', 'curva_referencia', 'eje_edad']

    def validate_curva_referencia(self, valor):
        """[[edad_h, valor], …]: números, edades ≥ 0 sin repetir; se guarda ordenada por edad."""
        if valor in (None, ''):
            return []
        if not isinstance(valor, list):
            raise serializers.ValidationError("La curva debe ser una lista de pares [edad, valor].")
        if len(valor) > MAX_PUNTOS_CURVA:
            raise serializers.ValidationError(f"La curva admite hasta {MAX_PUNTOS_CURVA} puntos.")
        puntos = []
        for par in valor:
            try:
                edad, numero = (float(x) for x in par)
            except (TypeError, ValueError):
                raise serializers.ValidationError("Cada punto de la curva lleva dos números: edad (h) y valor.")
            if not (math.isfinite(edad) and math.isfinite(numero)):
                raise serializers.ValidationError("La curva solo admite números.")
            if edad < 0:
                raise serializers.ValidationError("Las edades de la curva no pueden ser negativas.")
            puntos.append([edad, numero])
        puntos.sort(key=lambda par: par[0])
        edades = [par[0] for par in puntos]
        if len(set(edades)) != len(edades):
            raise serializers.ValidationError("La curva tiene edades repetidas.")
        return puntos

    def validate(self, data):
        for minimo, maximo, nombre in (('especificacion_min', 'especificacion_max', 'especificación'),
                                       ('alerta_min', 'alerta_max', 'alerta')):
            if data.get(minimo) is not None and data.get(maximo) is not None and data[minimo] > data[maximo]:
                raise serializers.ValidationError(f"{data['parametro'].nombre}: el mínimo de {nombre} es mayor que el máximo.")
        if data['parametro'].tipo_dato != 'NUMERO' and (any(data.get(c) is not None for c in LIMITES)
                                                       or data.get('objetivo') is not None or data.get('curva_referencia')):
            raise serializers.ValidationError(f"{data['parametro'].nombre} no es numérico: no lleva límites ni valor esperado.")
        return data


class SeccionCapturaSerializer(serializers.ModelSerializer):
    parametros = ParametroSeccionSerializer(many=True)

    class Meta:
        model = SeccionCaptura
        fields = ['id', 'nombre', 'orden', 'frecuencia', 'cada_horas', 'horas', 'muestra_fisica',
                  'patron_codigo_muestra', 'parametros']

    def validate_nombre(self, valor):
        valor = (valor or '').strip()
        if not valor:
            raise serializers.ValidationError("Ponle nombre a la sección.")
        return valor

    def validate_horas(self, valor):
        try:
            horas = sorted({int(h) for h in (valor or [])})
        except (TypeError, ValueError):
            raise serializers.ValidationError("Las horas deben ser números enteros.")
        if any(h < 0 for h in horas):
            raise serializers.ValidationError("Las horas no pueden ser negativas.")
        return horas

    def validate(self, data):
        if not data.get('parametros'):
            raise serializers.ValidationError(f"La sección «{data.get('nombre', '')}» no tiene parámetros.")
        if data.get('muestra_fisica') and not (data.get('patron_codigo_muestra') or '').strip():
            raise serializers.ValidationError(f"Sección «{data['nombre']}»: indica el código de la muestra (ej. PO41-M{{n}}).")
        if not data.get('muestra_fisica'):
            data['patron_codigo_muestra'] = ''
        return data


def guardar_secciones(operacion, secciones_data):
    """Reemplaza las secciones de captura de una actividad de la receta (los lotes ya instanciados no cambian)."""
    operacion.secciones_captura.all().delete()
    for orden, seccion_data in enumerate(secciones_data):
        parametros = seccion_data.pop('parametros', [])
        seccion_data.pop('orden', None)
        seccion = SeccionCaptura.objects.create(operacion=operacion, orden=orden, **seccion_data)
        ParametroSeccion.objects.bulk_create([
            ParametroSeccion(seccion=seccion, **{**p, 'orden': i}) for i, p in enumerate(parametros)
        ])


def validar_secciones_de_operacion(secciones, captura, es_incubacion, frecuencia, duracion, muestreo_inicial):
    """Reglas de las secciones según cómo captura la actividad. Devuelve el mensaje de error o None."""
    if captura == 'NINGUNA':
        return None
    if not secciones:
        return "Agrega al menos una sección con parámetros, o elige que la actividad no capture datos."
    if captura == 'MUESTREOS' and not (es_incubacion and frecuencia > 0):
        return "Solo una incubación con frecuencia de muestreo puede capturar datos en cada muestreo."

    vistos = {}
    for s in secciones:
        for p in s['parametros']:
            codigo = p['parametro'].codigo
            if codigo in vistos:
                return f"«{p['parametro'].nombre}» está en las secciones «{vistos[codigo]}» y «{s['nombre']}»: déjalo solo en una."
            vistos[codigo] = s['nombre']

    if captura != 'MUESTREOS':
        for s in secciones:
            s['frecuencia'], s['cada_horas'], s['horas'] = 'TODOS', 0, []
        return None

    horas_validas = set(range(0 if muestreo_inicial else frecuencia, int(duracion // frecuencia) * frecuencia + 1, frecuencia))
    for s in secciones:
        if s.get('frecuencia') == 'CADA_N':
            n = s.get('cada_horas') or 0
            if n <= 0 or n % frecuencia:
                return f"Sección «{s['nombre']}»: «cada N horas» debe ser múltiplo de la frecuencia de muestreo ({frecuencia} h)."
            s['horas'] = []
        elif s.get('frecuencia') == 'HORAS':
            horas = s.get('horas') or []
            if not horas:
                return f"Sección «{s['nombre']}»: indica en qué horas se captura."
            invalidas = [h for h in horas if h not in horas_validas]
            if invalidas:
                return (f"Sección «{s['nombre']}»: no hay muestreo a las {', '.join(map(str, invalidas))} h. "
                        f"Los muestreos son a las {', '.join(map(str, sorted(horas_validas))) or 'ninguna hora'} h.")
            s['cada_horas'] = 0
        else:
            s['frecuencia'], s['cada_horas'], s['horas'] = 'TODOS', 0, []
    return None
