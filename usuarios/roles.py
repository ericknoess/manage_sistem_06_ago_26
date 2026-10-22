# usuarios/roles.py — Roles del sistema (grupos de Django) y los permisos de cada uno.
# La migración 0002 crea los grupos con esta matriz; después se ajusta desde el admin sin tocar código.

TODOS = [
    'instanciar_lote', 'abortar_lote', 'reprogramar_fase', 'asignar_personal', 'ejecutar_fase',
    'ajustar_material_lote', 'surtir_material', 'editar_receta', 'archivar_receta', 'gestionar_catalogos',
    'gestionar_roster', 'gestionar_usuarios',
]

ROLES = {
    'Administrador': TODOS,
    'Jefatura': [
        'instanciar_lote', 'abortar_lote', 'reprogramar_fase', 'asignar_personal', 'ejecutar_fase',
        'ajustar_material_lote', 'surtir_material', 'archivar_receta', 'gestionar_roster',
    ],
    'Planeador': ['instanciar_lote', 'reprogramar_fase', 'asignar_personal', 'ajustar_material_lote', 'surtir_material'],
    'Supervisor de turno': ['asignar_personal', 'ejecutar_fase', 'gestionar_roster'],
    # Entrega materiales a las fases y recibe los sobrantes (web o terminal con PIN)
    'Almacén': ['surtir_material'],
    'Ingeniería de procesos': ['editar_receta', 'archivar_receta', 'gestionar_catalogos'],
    # Los operadores trabajan desde /mobile/ con su PIN; como usuario web solo consultan.
    'Operador': [],
    'Consulta': [],
}
