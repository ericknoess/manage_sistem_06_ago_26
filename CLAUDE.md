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
- Entorno: `~/miniforge3/envs/venv` (Django 5.1 + Pillow); el `venv/` del proyecto no tiene Pillow
- Pruebas: `python manage.py test procesos.tests` (las de `roster/tests/` requieren pytest, no instalado)
- Datos de prueba: `python manage.py seed_roster`, `python manage.py poblar_actividades`

## Arquitectura
- `core/`: settings, URLs raíz y la vista de la página de inicio (`/`)
- `templates/inicio.html` + `static/core/`: página central y recursos compartidos (base.css, utils.js)
- `roster/`: cuadrillas, operadores, roles, tipos de turno, turnos diarios, incidencias,
  secuencias de rotación y carga masiva (`roster/services.py`)
- `actividades/`: catálogos de Equipos y Materiales, tablero semanal (legado)
- `procesos/`: ProcesoMaestro → EtapaProceso → OperacionProceso; lotes, fases y asignaciones.
  Lógica CPM, generación de fases, reprogramación en cascada y cruces de operadores en `procesos/services.py`.
  Los horarios de `FaseLote` son fecha-hora completas (`inicio_programado`/`fin_programado`, `inicio_base_cpm`/`fin_base_cpm`);
  la API también expone `fecha_programada`/`hora_*` derivados en hora local, solo lectura.
- Materiales: `MaterialOperacion` (receta: cantidad, anticipación, actividad o cada muestreo) se copia a `MaterialFase`
  al instanciar el lote; los ajustes por lote exigen motivo y los retiros son bajas lógicas. El momento requerido es
  `inicio_programado - anticipacion_horas`, así que sigue a las reprogramaciones. Buscador compartido en `static/core/js/materiales.js`.
- Pantallas: / (inicio), /procesos/ (diseñador de recetas), /planificacion/, /gantt/, /ejecucion/, /mobile/, /roster/,
  /materiales/ (monitor de materiales por día y hora), /materiales/catalogo/ (catálogo de materiales)

## Convenciones
- Código, modelos, comentarios y UI en español.
- Lógica de negocio en `services.py`, no en las vistas.
- Endpoints nuevos como ViewSets de DRF (`@action` para operaciones especiales).
- Frontend sin frameworks: JS puro + Tailwind. CSS y JS en `static/<app>/{css,js}/<pantalla>.*`, nunca inline; lo compartido en `static/core/`.
- Toda pantalla nueva debe incluir el enlace `.btn-inicio` hacia `{% url 'inicio' %}`.

## Reglas
- Trazabilidad GxP: preferir baja lógica (`activo=False`, `archivado`) sobre borrado físico.
- No modificar migraciones existentes; crear nuevas.
- No editar `db.sqlite3` a mano ni hacer commit de `venv/` o `media/`.
- Correr `pytest` después de cambios en modelos o servicios.
- Explicar los cambios en español.
