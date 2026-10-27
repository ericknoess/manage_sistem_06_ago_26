# Sistema de Control de Actividades – Bioprocesos (MES)

## Contexto
Aplicación tipo MES para una planta de bioprocesos Upstream (entorno GxP).
Gestiona turnos del personal, recetas maestras (ISA-88), lotes de producción,
planificación con CPM/Gantt y ejecución en piso de planta (eBR en tablet).

## Stack
- Python 3.11.9 (el servidor tiene 3.12), Django 5.1, Django REST Framework 3.17 (versiones en `requirements.txt`)
- SQLite en desarrollo; PostgreSQL en producción (variables `DB_*`, ver Comandos)
- Frontend: plantillas Django + JavaScript puro (fetch a la API), Tailwind CSS (CDN), GSAP
- Pruebas: pytest + pytest-django

## Comandos
- Servidor: `python manage.py runserver`
- Migraciones: `python manage.py makemigrations && python manage.py migrate`
- Entorno: `~/miniforge3/envs/venv` (Django 5.1 + Pillow + openpyxl + reportlab + psycopg2); el `venv/` del proyecto no tiene Pillow
- Base de datos: SQLite por defecto; PostgreSQL si se define `DB_NAME` (+ `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`).
  Producción: además `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS` y `collectstatic` (a `staticfiles/` o `DJANGO_STATIC_ROOT`, no se versiona). Las pruebas pasan en ambas.
- Pruebas: `python manage.py test datos_proceso.tests auditoria usuarios procesos.tests` (las de `roster/tests/` requieren pytest, no instalado)
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
- Escala (cientos de lotes de ~1000 tareas): ninguna pantalla pide todas las tareas. `/api/fases-lote/` se filtra con `?lote=`
  (Piso de planta) o `?desde=&hasta=` (Planificación: la semana o el día visibles; tareas que se cruzan con esa ventana).
  `/api/lotes/` es una lista ligera sin tareas (avance contado en la base); el detalle `/api/lotes/<id>/` sí las trae.
  El Gantt usa `/api/lotes/gantt/` (barras por etapa con Min/Max en la base; abiertos y terminados en los últimos 30 días,
  `?todos=1` para todos). Una pantalla o endpoint nuevo que liste tareas debe filtrar igual.
  Planes de captura compactos (`datos_proceso/planes.py`): cada lista de parámetros de una sección se guarda una vez en
  `PlanParametros` (huella SHA-256, inmutable) y fases/tomas guardan `parametros_ref`; leer siempre con
  `_parametros_de_plan`/`parametros_de_seccion` o `expandir_plan`, y guardar con `compactar_plan(es)`.
  Medido en PostgreSQL con 300 lotes de ~1000 tareas (303 mil tareas, 1.4 M valores, 588 MB): Planificación semana 0.5 s,
  lote en Piso de planta 0.2 s, lista de lotes 0.6 s, Gantt 0.3 s, gráficas de 50 lotes 1.2 s y de 200 lotes 6.9 s (21 MB).
  Gráficas con más de 20 lotes (`UMBRAL_REDUCIR`): los no destacados llegan reducidos (`reducir_puntos`: hasta 120 puntos por
  serie, con mínimos, máximos y valores fuera de límites); `&completos=` = destacados; al destacar uno reducido, el front pide
  solo ese lote (`completarLote`). Los indicadores siempre usan todos los datos.
  Series preparadas (`SeriesLote`, `series_preparadas`): de cada lote TERMINADO se guardan sus series reducidas y sus
  indicadores (con la huella de la definición de los indicadores) y se usan al graficar muchos lotes, sin releer sus valores.
  Es una copia derivada (no GxP): las señales de `datos_proceso/signals.py` la borran al guardar el lote, una fase, una toma o
  un valor, y se regenera al graficar; tras escrituras en bloque (bulk_create) llamar `invalidar_series(lote_ids)`.
  `python manage.py preparar_series [--receta id]` las deja listas de antemano. 200 lotes simulados: 2 s (antes 6.9 s).
- Inicio en planta (`evaluar_inicio` en `procesos/services.py`): la dependencia con la predecesora debe cumplirse (FS completada,
  SS iniciada; el muestreo espera a su incubación) y la ventana `OperacionProceso.tolerancia_antes_horas`/`tolerancia_despues_horas`
  (diseñador de procesos) decide si hay desviación: la tablet no adelanta fuera de ventana, y todo inicio fuera de ella exige
  `motivo_desviacion` en la bitácora. Iniciar o completar recalcula sucesoras y muestreos desde la hora real;
  `/api/fases-lote/alertas/` marca en Planificación cruces de operador, operadores sin turno y materiales afectados por un adelanto.
- Materiales: `MaterialOperacion` (receta: cantidad, anticipación, actividad o cada muestreo) se copia a `MaterialFase`
  al instanciar el lote; los ajustes por lote exigen motivo y los retiros son bajas lógicas. El momento requerido es
  `inicio_programado - anticipacion_horas`, así que sigue a las reprogramaciones. Buscador compartido en `static/core/js/materiales.js`.
- Surtido de materiales (`EntregaMaterial`, API `/api/surtido/`): entrega con lote y caducidad (`surtir_material`: rol Almacén,
  Planeador, Jefatura) → queda EN_TRANSITO → la recibe o rechaza (con motivo) un operador en turno, el asignado a la fase o un
  rol con `ejecutar_fase` (`puede_recibir_material`); el sobrante se devuelve y lo recibe el almacén. Cada paso se firma (ENTREGAR/RECIBIR/RECHAZAR/DEVOLVER_MATERIAL) y quien entrega no puede recibir
  (regla de cuatro ojos; un usuario web y su `Perfil.operador` son la misma persona). En la terminal, los permisos son los del
  usuario web ligado al operador. No se entrega material caducado ni que vence antes del uso programado. Iniciar una fase con
  material incompleto solo advierte (queda en la bitácora); Planificación alerta el material sin surtir a su hora.
  Lógica en `procesos/services.py` (sección SURTIDO); front web en `static/core/js/surtido.js` (monitor /materiales/),
  tablet en `procesos/static/procesos/js/mobile_surtido.js` (materiales por tarea, sobrantes, pestañas "Recibir" y "Surtir").
- Equipos: la receta pide equipos por tipo (`EquipoOperacion`: cantidad, horas de preparación y limpieza, actividad o cada muestreo);
  se copia a `EquipoFase` al instanciar el lote (ajustes con motivo, retiros como baja lógica) y en Planificación se reservan equipos
  concretos (`ReservaEquipo`). La ocupación es `inicio - preparación` a `fin + limpieza` y sigue al forecast. No se reserva un equipo
  ocupado, de otro tipo, no disponible o con calificación vencida, y una fase no inicia sin su equipo. Con la fase en ejecución el equipo
  se cambia con motivo y firma (`CAMBIAR_EQUIPO`): la reserva anterior se cierra en `hasta` y la nueva abre en `desde`.
  Lógica en `procesos/services.py`; API `/api/equipos-fase/`; front compartido en `static/core/js/equipos.js`.
- `datos_proceso/`: datos de proceso (lo que hacía la app Cultivo, configurable sin código). Catálogo `ParametroProceso`
  (/parametros/; número, texto, opción o sí/no; los calculados llevan fórmula, evaluada sin `eval` en `formulas.py`).
  En el diseñador cada actividad dice si captura datos (`OperacionProceso.captura_datos`: al completar o en cada muestreo),
  si su incubación muestrea a las 0 h (`muestreo_inicial`) y si define la edad 0 de su etapa/lote (`edad_cero`, `edad_cero_lote`);
  sus `SeccionCaptura` (todos los muestreos, cada N h o horas específicas; muestra física con código `{n}`) llevan `ParametroSeccion`
  con límites de especificación y alerta y un valor esperado opcional (`objetivo` fijo y/o `curva_referencia` [[edad, valor]],
  graficada contra la edad del lote o de la etapa, `eje_edad`). Al instanciar, `generar_plan_captura` copia a `FaseLote.plan_captura` lo que pide cada fase.
  En planta (`/api/captura/<fase>/`): una `TomaDatos` por fase en curso, `ValorParametro` por parámetro; no se completa la fase sin
  sus obligatorios (`DATOS_PENDIENTES`); corregir crea un valor nuevo (motivo + firma `CORREGIR_DATO`); muestras adicionales en la
  incubación con motivo. Edad = hora real de la toma − edad 0 (`edades_cero`). Al capturar, cada parámetro numérico muestra su
  gráfica de tendencia (SVG propio, sin librerías): datos anteriores de la etapa (`tendencias`), valor que se escribe, límites y esperado. Front: `static/core/js/captura.js` (web y tablet),
  `datos_proceso/static/datos_proceso/js/disenador_captura.js` (diseñador). Pruebas: `python manage.py test datos_proceso.tests`.
  Gráficas de proceso (/graficas/, API `/api/analisis-proceso/`, puntos compactos y 4 consultas para 200 lotes): barra de
  plantillas (recetas) como en el diseñador (`/api/analisis-proceso/recetas/`); gráficas por etapa y, dentro, por actividad ·
  sección (`estructura_receta`: un parámetro por etapa, con los límites y la curva de ese uso; chips para ver una etapa); pestañas Lotes
  (elegir hasta 200; se recuerda por receta en el navegador), Gráficas (cada parámetro contra la edad: lotes en gris, hasta 8
  destacados con color fijo de `COLORES_SERIES`, banda P10–P90 y mediana, curva esperada, límites; zoom por arrastre sincronizado
  por eje de edad), Comparar (varios parámetros de cualquier etapa: apilados con el mismo eje X —edad del lote o fecha— y guía
  sincronizada `grupoGuia`, o superpuestos escalando cada uno a 0–100 %; nunca dos ejes Y) e Indicadores (tabla ordenable con
  promedio, mín–máx y % en meta). `IndicadorProceso` (por receta, configurable en esa
  pantalla, `/api/indicadores-proceso/`): área bajo la curva por trapecios, apego % contra la curva esperada (en la edad de la curva),
  último, máximo o fórmula con otros indicadores (ej. gramos = abc_cel / 1000 - 5.5); se calculan al consultar, no se guardan.
  Gráfica compartida (SVG propio, sin librerías): `static/core/js/graficas.js` + `static/core/css/graficas.css`.
  Informes (fase 3, `/api/informes-proceso/`): PDF (reportlab) y Excel (openpyxl) de un lote o de una etapa
  (`<lote>/pdf|excel/?etapa=`) y Excel de varios lotes (`lotes/?proceso=&lotes=`). Los datos salen de `datos_informe` /
  `filas_lotes_excel` en services.py y el formato de `datos_proceso/informes.py`. Organizados como el diseñador: una sección
  (y en Excel una hoja) por etapa con sus columnas y sus gráficas por actividad · sección; opcionalmente gráficas combinadas
  (`&combinar=<etapa>-<parámetro>,…&vista=apiladas|superpuestas`; en Excel, gráficas nativas apiladas). Llevan indicadores, tomas,
  fuera de límites, adicionales, correcciones con su firma (de la bitácora) y huella SHA-256 de los datos; cada emisión se
  registra (`GENERAR_INFORME`). Front: `static/core/js/informes.js` (`abrirInformeLote`, `descargarArchivo`).
  Histórico de Cultivo (fase 4): `python manage.py importar_cultivo --bd "<dsn libpq>" --curva ../cultivo_local/app/datos_modelo.csv
  [--lote X] [--simular] [--detalle]` (lógica en `datos_proceso/importacion_cultivo.py`; contraseña en PGPASSWORD; Cultivo solo se lee).
  Crea la receta «EPO – Cultivo (histórico)» (PO4 y PR1, muestreo cada 6 h, secciones P / GyL cada 12 h / C cada 24 h, curva
  Modelo_2024 e indicadores del carnet) y un lote por lote de Cultivo con un muestreo completado y su toma por registro; la hora es
  `fecha_obj` (Cultivo no guarda la real), así que las edades coinciden. Repetirlo solo agrega muestreos nuevos; los duplicados
  de Cultivo (misma etapa y edad) se resuelven por el registro con más secciones y luego el más reciente. Bitácora `IMPORTAR_HISTORICO`.
- `usuarios/`: login (`/login/`, `/logout/`), roles y permisos. Los roles son grupos de Django (Administrador, Jefatura,
  Planeador, Supervisor de turno, Ingeniería de procesos, Operador, Consulta; Almacén desde la 0004) creados por la migración 0002; los permisos
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
  /equipos/ (monitor de ocupación de equipos), /equipos/catalogo/ (catálogo de equipos y tipos), /parametros/ (catálogo de parámetros de proceso),
  /graficas/ (gráficas de proceso e indicadores; acepta ?proceso=&lotes=)

## Integración con Cultivo (objetivo en curso, desde 2026-10-23)
- Cultivo es la app en producción de control en proceso del cultivo celular (`controlcultivo.probiomed.com.mx`,
  servidor Ubuntu 172.20.6.99; Django 5.2 + PostgreSQL `base_proceso`, Gunicorn + Nginx). Maneja lotes de EPO y
  Rituximab con muestreos programados cada 6/12/24 h (±2 h), captura de parámetros del reactor, glucosa/lactato y
  cuenta celular, carnet del lote contra la curva Modelo_2024, desviaciones, CAPAs, expedientes y tablero de tareas.
- Objetivo (cambiado el 2026-10-23): llevar la lógica de Cultivo al MES, en su propia base y configurable desde pantallas
  (app `datos_proceso`). Fases: 1) catálogo, captura en tablet/web, edad 0 ✅; 2) gráficas por etapa, curvas de referencia
  e indicadores (área bajo la curva, gramos estimados) ✅; 3) informes por etapa (PDF/Excel) ✅; 4) importar el histórico de Cultivo ✅ (comando listo; probado en una copia).
  Desviaciones, CAPAs y expedientes quedan para después.
- Se trabaja primero en la copia local `../cultivo_local` (ver su CLAUDE.md); a producción solo se lleva lo
  probado y con autorización explícita del usuario. En el servidor, solo lectura salvo que el usuario lo pida.
- Problemas conocidos en producción: `DEBUG = True`, API `/api/EPO/` sin permisos (responde sin sesión),
  sin bitácora de auditoría ni firma, algunas vistas sin `login_required`, `/desempeño/` falla.

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
