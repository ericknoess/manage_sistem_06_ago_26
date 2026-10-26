# datos_proceso/formulas.py — Fórmulas de parámetros calculados, escritas por el usuario.
#
# Ejemplos: "flujo_total * mezcla_o2 / 100", "celulas_salida * 10000 / 1000000", "round(abc / 1000 - 5.5, 1)".
# Solo se aceptan números, códigos de parámetros, + - * / % **, paréntesis y las funciones de FUNCIONES.
# Nunca se usa eval(): la expresión se recorre como árbol y cualquier otra cosa se rechaza.

import ast
import math

FUNCIONES = {
    'abs': abs, 'min': min, 'max': max, 'round': round,
    'sqrt': math.sqrt, 'log': math.log, 'log10': math.log10, 'exp': math.exp,
}
_OPERADORES = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b, ast.Mod: lambda a, b: a % b, ast.Pow: lambda a, b: a ** b,
}
_UNARIOS = {ast.USub: lambda a: -a, ast.UAdd: lambda a: a}
LONGITUD_MAXIMA = 500


class ErrorFormula(ValueError):
    """La fórmula no es válida; el mensaje se muestra tal cual al usuario."""


def _arbol(formula):
    texto = (formula or '').strip()
    if not texto:
        raise ErrorFormula("La fórmula está vacía.")
    if len(texto) > LONGITUD_MAXIMA:
        raise ErrorFormula(f"La fórmula no puede pasar de {LONGITUD_MAXIMA} caracteres.")
    try:
        arbol = ast.parse(texto, mode='eval')
    except SyntaxError:
        raise ErrorFormula("La fórmula tiene un error de escritura (revisa paréntesis y operadores).")
    _validar_nodo(arbol.body)
    return arbol


def _validar_nodo(nodo):
    if isinstance(nodo, ast.BinOp):
        if type(nodo.op) not in _OPERADORES:
            raise ErrorFormula("Operador no permitido. Usa + - * / % o **.")
        _validar_nodo(nodo.left)
        _validar_nodo(nodo.right)
    elif isinstance(nodo, ast.UnaryOp):
        if type(nodo.op) not in _UNARIOS:
            raise ErrorFormula("Operador no permitido.")
        _validar_nodo(nodo.operand)
    elif isinstance(nodo, ast.Constant):
        if isinstance(nodo.value, bool) or not isinstance(nodo.value, (int, float)):
            raise ErrorFormula("Solo se permiten números y códigos de parámetros.")
    elif isinstance(nodo, ast.Name):
        pass
    elif isinstance(nodo, ast.Call):
        if not isinstance(nodo.func, ast.Name) or nodo.func.id not in FUNCIONES:
            raise ErrorFormula(f"Función no permitida. Disponibles: {', '.join(FUNCIONES)}.")
        if nodo.keywords or not nodo.args:
            raise ErrorFormula(f"Uso no válido de {nodo.func.id}().")
        for argumento in nodo.args:
            _validar_nodo(argumento)
    else:
        raise ErrorFormula("La fórmula contiene algo que no es un cálculo (solo números, parámetros, operadores y funciones).")


def variables(formula):
    """Códigos de parámetros que usa la fórmula (sin las funciones)."""
    arbol = _arbol(formula)
    return sorted({n.id for n in ast.walk(arbol) if isinstance(n, ast.Name) and n.id not in FUNCIONES})


def _evaluar(nodo, valores):
    if isinstance(nodo, ast.BinOp):
        return _OPERADORES[type(nodo.op)](_evaluar(nodo.left, valores), _evaluar(nodo.right, valores))
    if isinstance(nodo, ast.UnaryOp):
        return _UNARIOS[type(nodo.op)](_evaluar(nodo.operand, valores))
    if isinstance(nodo, ast.Constant):
        return nodo.value
    if isinstance(nodo, ast.Name):
        valor = valores.get(nodo.id)
        if valor is None:
            raise KeyError(nodo.id)
        return float(valor)
    if isinstance(nodo, ast.Call):
        argumentos = [_evaluar(a, valores) for a in nodo.args]
        if nodo.func.id == 'round' and len(argumentos) == 2:
            argumentos[1] = int(argumentos[1])
        return FUNCIONES[nodo.func.id](*argumentos)
    raise ErrorFormula("Expresión no válida.")


def evaluar(formula, valores):
    """
    Resultado (float) de la fórmula con `valores` {codigo: número}. Devuelve None si falta algún
    valor o el cálculo no es posible (división entre cero, logaritmo de un negativo, resultado no finito).
    """
    arbol = _arbol(formula)
    try:
        resultado = float(_evaluar(arbol.body, valores))
    except (KeyError, ZeroDivisionError, ValueError, OverflowError, TypeError):
        return None
    return resultado if math.isfinite(resultado) else None
