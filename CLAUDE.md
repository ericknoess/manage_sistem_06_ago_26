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
- Pruebas: `python manage.py test auditoria usuarios procesos.tests` (las de `roster/tests/` requieren pytest, no instalado)
- Datos de prueba: `python manage.py seed_roster`, `python manage.py poblar_actividades`

## Arquitectura
- `core/`: settings, URLs raíz y la vista de la página de inicio (`/`). `core/estaticos.py` agrega `?v=<hash>` a cada `{% static %}`
  (evita que el navegador use JS/CSS viejos tras una actualización); no escribir rutas `/static/...` a mano.
- `templates/inicio.html` + `static/core/`: página central y recursos compartidos (base.css, utils.js)
- `roster/`: cuadrillas, operadores, roles, tipos de turno, turnos diarios, incidencias,
  secuencias de rotación y carga masiva (`roster/services.py`)
- `actividades/`: catálogos de Equipos (con `TipoEquipo`, estado operativo y vencimiento de calificación) y Materiales. `ActividadSemanal` es el histórico del
  tablero semanal retirado (solo lectura; `/tablero/` redirige a Planificación, único lugar para asignar personal)
- `procesos/`: ProcesoMaestro → EtapaProceso → OperacionProceso; lotes, fases y asignaciones.
  Lógica CPM, generación de fases, reprogramación en cascada y cruces de operadores en `procesos/services.py`.
  Los horarios de `FaseLote` son fecha-hora completas (`inicio_programado`/`fin_programado`, `inicio_base_cpm`/`fin_base_cpm`);
  la API también expone `fecha_programada`/`hora_*` derivados en hora local, solo lectura.
- Inicio en planta (`evaluar_inicio` en `procesos/services.py`): la dependencia con la predecesora debe cumplirse (FS completada,
  SS iniciada; el muestreo espera a su incubación) y la ventana `OperacionProceso.tolerancia_antes_horas`/`tolerancia_despues_horas`
  (diseñador de procesos) decide si hay desviación: la tablet no adelanta fuera de ventana, y todo inicio fuera de ella exige
  `motivo_desviacion` en la bitácora. Iniciar o completar recalcula sucesoras y muestreos desde la hora real;
  `/api/fases-lote/alertas/` marca en Planificación cruces de operador, operadores sin turno y materiales afectados por un adelanto.
- Materiales: `MaterialOperacion` (receta: cantidad, anticipación, actividad o cada muestreo) se copia a `MaterialFase`
  al instanciar el lote; los ajustes por lote exigen motivo y los retiros son bajas lógicas. El momento requerido es
  `inicio_programado - anticipacion_horas`, así que sigue a las reprogramaciones. Buscador compartido en `static/core/js/materiales.js`.
- Equipos: la receta pide equipos por tipo (`EquipoOperacion`: cantidad, horas de preparación y limpieza, actividad o cada muestreo);
  se copia a `EquipoFase` al instanciar el lote (ajustes con motivo, retiros como baja lógica) y en Planificación se reservan equipos
  concretos (`ReservaEquipo`). La ocupación es `inicio - preparación` a `fin + limpieza` y sigue al forecast. No se reserva un equipo
  ocupado, de otro tipo, no disponible o con calificación vencida, y una fase no inicia sin su equipo. Con la fase en ejecución el equipo
  se cambia con motivo y firma (`CAMBIAR_EQUIPO`): la reserva anterior se cierra en `hasta` y la nueva abre en `desde`.
  Lógica en `procesos/services.py`; API `/api/equipos-fase/`; front compartido en `static/core/js/equipos.js`.
- `usuarios/`: login (`/login/`, `/logout/`), roles y permisos. Los roles son grupos de Django (Administrador, Jefatura,
  Planeador, Supervisor de turno, Ingeniería de procesos, Operador, Consulta) creados por la migración 0002; los permisos
  de negocio (`instanciar_lote`, `asignar_personal`, …) están en `Perfil.Meta.permissions`. Usuarios y roles se dan de alta en `/admin/`.
  Toda pantalla pide sesión (`LoginRequeridoMiddleware`), salvo `/mobile/` (PIN del operador, guardado en la sesión del servidor).
  API: `PermisoPorAccion` deja leer a cualquier usuario con sesión y para escribir exige el permiso que declara cada ViewSet en
  `permiso_escritura` o `permisos_por_accion`; un ViewSet nuevo sin esa declaración queda de solo lectura.
  `/api/sesion/` da usuario, roles y permisos; `static/core/js/sesion.js` (incluido en el `<head>` de cada pantalla) pinta el usuario,
  agrega el CSRF a `fetch` y oculta todo elemento con `data-permiso="codigo"` que el rol no tenga.
- `auditoria/`: bitácora GxP (`RegistroAuditoria`): quién (usuario u operador con PIN), qué, cuándo, IP, motivo y
  `cambios` {campo: [antes, después]}. Solo se agrega: el modelo impide editar/borrar y la API es de solo lectura.
  Se escribe con `auditoria.services.registrar(request, categoria, accion, descripcion, ...)` en cada acción especial y,
  para altas/cambios/bajas de ViewSets, con `AuditoriaMixin` (`auditoria_categoria`, `auditoria_nombre`). Nunca guarda PIN ni contraseñas.
  Pantalla /auditoria/; historial por lote (Piso de planta) y por fase (Planificación) con `static/core/js/auditoria.js`.
- Firma electrónica (21 CFR Part 11), `usuarios/firmas.py`: abortar/eliminar/archivar lote y todo cambio de estado de fase
  exigen volver a escribir la contraseña (`firma_password`) o, en /mobile/, el PIN (`firma_pin`); `verificar_firma(request, ACCION)`
  antes de modificar y `auditoria.services.firmar(registro, firmante)` después liga la `FirmaElectronica` (nombre, fecha, significado)
  al registro de la bitácora. Significados en `SIGNIFICADOS`. Front: `static/core/js/firma.js` (`ejecutarConFirma`).
  5 intentos fallidos (login o firma) bloquean la cuenta (`Perfil.bloqueado`, `is_active=False`) o el PIN (`Operador.pin_bloqueado`);
  se desbloquean con la acción del admin o `python manage.py desbloquear_usuario <usuario>`.
- Pantallas: /login/, /auditoria/ (bitácora), / (inicio), /procesos/ (diseñador de recetas), /planificacion/, /gantt/, /ejecucion/, /mobile/, /roster/,
  /materiales/ (monitor de materiales por día y hora), /materiales/catalogo/ (catálogo de materiales),
  /equipos/ (monitor de ocupación de equipos), /equipos/catalogo/ (catálogo de equipos y tipos)

## Convenciones
- Código, modelos, comentarios y UI en español.
- Lógica de negocio en `services.py`, no en las vistas.
- Endpoints nuevos como ViewSets de DRF (`@action` para operaciones especiales).
- Frontend sin frameworks: JS puro + Tailwind. CSS y JS en `static/<app>/{css,js}/<pantalla>.*`, nunca inline; lo compartido en `static/core/`.
- Toda pantalla nueva debe incluir el enlace `.btn-inicio` hacia `{% url 'inicio' %}` y `core/css/sesion.css` + `core/js/sesion.js` en el `<head>`.
- Todo botón que modifique datos lleva `data-permiso="<permiso>"`, y su endpoint declara ese mismo permiso.
- Toda acción que modifique datos queda en la bitácora: ViewSet con `AuditoriaMixin` o `registrar(...)` en el `@action`.
- Una acción crítica nueva (que cierre, anule o firme un registro de lote) se agrega a `SIGNIFICADOS` y se firma.

## Reglas
- Trazabilidad GxP: preferir baja lógica (`activo=False`, `archivado`) sobre borrado físico.
- No modificar migraciones existentes; crear nuevas.
- No editar `db.sqlite3` a mano ni hacer commit de `venv/` o `media/`.
- Correr `pytest` después de cambios en modelos o servicios.
- Explicar los cambios en español.
