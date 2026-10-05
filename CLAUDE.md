# Sistema de Control de Actividades – Bioprocesos (MES)

## Contexto
Aplicación tipo MES para una planta de bioprocesos Upstream (entorno GxP).
Gestiona turnos del personal, recetas maestras (ISA-88), lotes de producción,
planificación con CPM/Gantt y ejecución en piso de planta (eBR en tablet).

## Stack
- Python 3.11.9, Django 4.2, Django REST Framework
- SQLite en desarrollo (PostgreSQL previsto vía psycopg2)
- Frontend: plantillas Django + JavaScript puro (fetch a la API), Tailwind CSS (CDN), GSAP
- Pruebas: pytest + pytest-django

## Comandos
- Servidor: `python manage.py runserver`
- Migraciones: `python manage.py makemigrations && python manage.py migrate`
- Pruebas: `pytest`
- Datos de prueba: `python manage.py seed_roster`, `python manage.py poblar_actividades`

## Arquitectura
- `core/`: settings y URLs raíz
- `roster/`: cuadrillas, operadores, roles, tipos de turno, turnos diarios, incidencias,
  secuencias de rotación y carga masiva (`roster/services.py`)
- `actividades/`: catálogos de Equipos y Materiales, tablero semanal (legado)
- `procesos/`: ProcesoMaestro → EtapaProceso → OperacionProceso; lotes, fases y asignaciones.
  Lógica CPM en `procesos/services.py`.
- Pantallas: /procesos/ (diseñador de recetas), /planificacion/, /gantt/, /ejecucion/, /mobile/, /roster/

## Convenciones
- Código, modelos, comentarios y UI en español.
- Lógica de negocio en `services.py`, no en las vistas.
- Endpoints nuevos como ViewSets de DRF (`@action` para operaciones especiales).
- Frontend sin frameworks: JS puro + Tailwind, en el template o en `static/<app>/js/`.

## Reglas
- Trazabilidad GxP: preferir baja lógica (`activo=False`, `archivado`) sobre borrado físico.
- No modificar migraciones existentes; crear nuevas.
- No editar `db.sqlite3` a mano ni hacer commit de `venv/` o `media/`.
- Correr `pytest` después de cambios en modelos o servicios.
- Explicar los cambios en español.
