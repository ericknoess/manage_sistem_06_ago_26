// procesos/static/procesos/js/planificacion.js

let currentDateBase = new Date(); 
let modoVista = 'semanal'; 
let dailyScrollMemory = (7 * 60) - 20; 

let diasSemana = [];
const nombresDias = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const nombresMeses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

let fasesGlobales = [];
let operadoresGlobales = [];
let materialesGlobales = [];
let faseSeleccionadaId = null;
let alertasGlobales = {};  // {fase_id: [mensajes]}: cruces, operadores sin turno, materiales tras un adelanto

function obtenerLunes(date) {
    const d = new Date(date);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    return new Date(d.setDate(diff));
}

function getTodayString() {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
}

function formatToDateString(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function actualizarMecanismoTiempo() {
    if (modoVista === 'semanal') {
        diasSemana = [];
        let currentDay = obtenerLunes(currentDateBase);
        currentDay.setHours(0,0,0,0);

        for (let i = 0; i < 7; i++) {
            diasSemana.push({
                nombre: nombresDias[currentDay.getDay()].substring(0,3),
                fecha: formatToDateString(currentDay),
                diaMes: currentDay.getDate(),
                mesNombre: nombresMeses[currentDay.getMonth()]
            });
            currentDay.setDate(currentDay.getDate() + 1);
        }
        const primer = diasSemana[0];
        const ultimo = diasSemana[6];
        document.getElementById('labelTiempoActual').innerText = `${primer.diaMes} ${primer.mesNombre} -${ultimo.diaMes} ${ultimo.mesNombre}${primer.fecha.split('-')[0]}`;
    } else {
        const dia = currentDateBase.getDate();
        const mes = nombresMeses[currentDateBase.getMonth()];
        const anio = currentDateBase.getFullYear();
        const diaNombre = nombresDias[currentDateBase.getDay()];
        document.getElementById('labelTiempoActual').innerText = `${diaNombre},${dia} de ${mes}${anio}`;
    }
}

function navegarTiempo(direccion) {
    if (modoVista === 'semanal') {
        currentDateBase.setDate(currentDateBase.getDate() + (direccion * 7));
    } else {
        currentDateBase.setDate(currentDateBase.getDate() + direccion);
    }
    actualizarMecanismoTiempo();
    cargarDatosPlanificacion();
}

function irHoy() {
    currentDateBase = new Date();
    actualizarMecanismoTiempo();
    cargarDatosPlanificacion();
}

function cambiarModoVista(modo) {
    modoVista = modo;
    document.getElementById('btnViewWeekly').classList.toggle('active', modo === 'semanal');
    document.getElementById('btnViewDaily').classList.toggle('active', modo === 'diaria');

    document.getElementById('gridSemanal').style.display = modo === 'semanal' ? 'grid' : 'none';
    document.getElementById('gridDiaria').style.display = modo === 'diaria' ? 'flex' : 'none';

    actualizarMecanismoTiempo();
    cargarDatosPlanificacion();
}

// Ventana visible (semana de lunes a domingo, o el día) en hora local, para pedir solo sus tareas
function ventanaVisible() {
    const desde = modoVista === 'semanal' ? obtenerLunes(currentDateBase) : new Date(currentDateBase);
    desde.setHours(0, 0, 0, 0);
    const hasta = new Date(desde);
    hasta.setDate(hasta.getDate() + (modoVista === 'semanal' ? 7 : 1));
    return { desde, hasta };
}

let consultaPlanificacion = 0;  // descarta respuestas viejas si se navega rápido

async function cargarDatosPlanificacion() {
    const consulta = ++consultaPlanificacion;
    const { desde, hasta } = ventanaVisible();
    // Solo las tareas que se cruzan con lo que se ve: con cientos de lotes, pedirlas todas sería lentísimo.
    // Los cruces de operador se revisan con estas mismas tareas (una tarea visible solo choca con otras que también se ven).
    const urlFases = `/api/fases-lote/?desde=${encodeURIComponent(desde.toISOString())}&hasta=${encodeURIComponent(hasta.toISOString())}`;
    try {
        const [resFases, resOp, resMat, resAlertas] = await Promise.all([
            fetch(urlFases), fetch('/api/operadores/?activo=true'),
            fetch('/api/materiales/'), fetch('/api/fases-lote/alertas/')
        ]);

        if (!resFases.ok) throw new Error('Error de red');
        const fases = await resFases.json();
        if (consulta !== consultaPlanificacion) return;

        fasesGlobales = fases;
        operadoresGlobales = await resOp.json();
        materialesGlobales = await resMat.json();
        alertasGlobales = resAlertas.ok ? await resAlertas.json() : {};

        renderGrillaActiva();

        if (faseSeleccionadaId) {
            const fExist = fasesGlobales.find(f => f.id === faseSeleccionadaId && (f.tipo_operacion !== 'INCUBACION' || f.es_subtarea_muestreo));
            if(fExist) renderPanelDetalle(faseSeleccionadaId);
            else document.getElementById('panelDisponibilidad').innerHTML = `<div class="empty-state">Seleccione una tarea.</div>`;
        }
    } catch (error) { console.error("Error:", error); }
}

function renderGrillaActiva() {
    const scrollContainer = document.querySelector('.daily-scroll-container');
    if (modoVista === 'diaria' && scrollContainer && scrollContainer.scrollTop > 0) {
        dailyScrollMemory = scrollContainer.scrollTop;
    }

    if (modoVista === 'semanal') renderGrillaSemanal();
    else renderGrillaDiaria();
}

// ====================================================================
// RENDERIZADO: VISTA DIARIA (CSS GRID NATIVO)
// ====================================================================
const ANCHO_COLUMNA_LOTE = 240;   // px de una columna de lote sin cruces
const ANCHO_MIN_CARRIL = 170;     // px mínimos por carril cuando hay fases cruzadas
const ALTO_MIN_BLOQUE = 44;       // px (= minutos) para que una fase corta muestre hora y nombre

// Ubica una fase en la columna del día: 1 px por minuto, recortada a medianoche si sigue al día siguiente
function medirBloqueDiario(f, fechaStr) {
    const inicioDia = new Date(`${fechaStr}T00:00:00`);
    const finDia = new Date(inicioDia);
    finDia.setDate(finDia.getDate() + 1);
    const inicio = new Date(f.inicio_programado);
    const fin = f.fin_programado ? new Date(Math.min(new Date(f.fin_programado), finDia)) : new Date(inicio.getTime() + 3600000);
    const top = Math.max(0, Math.round((inicio - inicioDia) / 60000));
    const alto = Math.max(ALTO_MIN_BLOQUE, Math.round((fin - inicio) / 60000));
    return { fase: f, top, alto };
}

// Reparte en carriles los bloques que se enciman (por su altura visible) y fija el número de carriles de cada grupo
function distribuirEnCarriles(bloques) {
    bloques.sort((a, b) => a.top - b.top || b.alto - a.alto);
    let grupo = [], finesCarriles = [], finGrupo = -1;
    const cerrarGrupo = () => grupo.forEach(b => { b.totalCarriles = finesCarriles.length; });

    bloques.forEach(b => {
        if (b.top >= finGrupo) {
            cerrarGrupo();
            grupo = [];
            finesCarriles = [];
        }
        let carril = finesCarriles.findIndex(fin => fin <= b.top);
        if (carril === -1) carril = finesCarriles.length;
        finesCarriles[carril] = b.top + b.alto;
        b.carril = carril;
        grupo.push(b);
        finGrupo = Math.max(finGrupo, b.top + b.alto);
    });
    cerrarGrupo();
    return bloques;
}

function renderGrillaDiaria() {
    const grid = document.getElementById('gridDiaria');
    const targetDateStr = formatToDateString(currentDateBase);

    const fasesDia = fasesGlobales.filter(f => f.fecha_programada === targetDateStr && (f.tipo_operacion !== 'INCUBACION' || f.es_subtarea_muestreo === true));

    const lotesIdsMap = new Map();
    fasesDia.forEach(f => lotesIdsMap.set(f.lote, f.lote_codigo));
    const lotesUnicos = Array.from(lotesIdsMap, ([id, codigo]) => ({ id, codigo }));

    if (lotesUnicos.length === 0) {
        grid.innerHTML = `<div class="empty-state" style="margin-top:4rem; font-size:1.2rem;">☕ No hay actividades programadas para este día.</div>`;
        return;
    }

    // Posición vertical (1 px = 1 min) y reparto en carriles de las fases que se cruzan dentro de cada lote
    const layoutPorLote = new Map(lotesUnicos.map(lote => [
        lote.id,
        distribuirEnCarriles(fasesDia.filter(f => f.lote === lote.id && f.inicio_programado).map(f => medirBloqueDiario(f, targetDateStr)))
    ]));
    const anchoPorLote = new Map(lotesUnicos.map(lote => {
        const carriles = Math.max(1, ...layoutPorLote.get(lote.id).map(b => b.totalCarriles));
        return [lote.id, Math.max(ANCHO_COLUMNA_LOTE, carriles * ANCHO_MIN_CARRIL)];
    }));

    const gridTemplateColumnsValue = `60px ${lotesUnicos.map(lote => `${anchoPorLote.get(lote.id)}px`).join(' ')}`;

    let html = `<div class="daily-scroll-container"><div class="gantt-table" style="grid-template-columns: ${gridTemplateColumnsValue};">`;

    html += `<div class="gantt-header-cell time-col"></div>`;
    lotesUnicos.forEach(lote => {
        html += `<div class="gantt-header-cell">LOTE DE PRODUCCIÓN<span style="color:var(--text); font-size:1.08rem;">${lote.codigo}</span></div>`;
    });

    html += `<div class="gantt-time-ruler">`;
    for (let i = 0; i < 24; i++) {
        html += `<div class="daily-hour-marker">${String(i).padStart(2, '0')}:00</div>`;
    }
    html += `</div>`;

    lotesUnicos.forEach(lote => {
        const ancho = anchoPorLote.get(lote.id);
        html += `<div class="gantt-lote-col" style="width: ${ancho}px; min-width: ${ancho}px;">`;

        layoutPorLote.get(lote.id).forEach(bloque => {
            const f = bloque.fase;
            const estaIniciada = ['EN_PROGRESO', 'COMPLETADA'].includes(f.estado);
            let stateClass = '';
            if (f.estado === 'EN_PROGRESO') stateClass = 'state-progreso';
            if (f.estado === 'COMPLETADA') stateClass = 'state-completado';
            if (f.estado === 'OMITIDA') stateClass = 'state-omitida';

            const isSelected = f.id === faseSeleccionadaId ? 'selected' : '';
            const timeStr = formatearRangoFase(f.inicio_programado, f.fin_programado);
            const headcountReq = f.personal_requerido || 1;
            const asignados = (f.operadores_asignados || []).length;
            const alertOps = asignados < headcountReq ? `<span style="color:var(--danger);">⚠️</span>` : ``;
            const anchoCarril = `(100% - 12px) / ${bloque.totalCarriles}`;

            html += `
                <div id="daily-task-${f.id}" class="daily-task-block ${stateClass} ${isSelected} ${estaIniciada?'locked':''}" 
                     style="top: ${bloque.top}px; height: ${bloque.alto}px; left: calc(6px + ${bloque.carril} * ${anchoCarril}); width: calc(${anchoCarril} - 4px); right: auto;"
                     title="[${f.operacion_id_paso}] ${f.operacion_nombre} · ${timeStr}"
                     onclick="seleccionarFase(${f.id})">
                     <div class="daily-task-meta">
                        <span>⏰ ${timeStr}</span>
                        <span>${insigniaAlertas(f.id)}${insigniaEquipos(f)}👥 ${asignados}/${headcountReq} ${alertOps}</span>
                     </div>
                     <div class="daily-task-title">
                        [${f.operacion_id_paso}] ${f.operacion_nombre}
                     </div>
                </div>
            `;
        });
        html += `</div>`;
    });

    html += `</div></div>`; 
    grid.innerHTML = html;

    setTimeout(() => {
        const newScrollContainer = document.querySelector('.daily-scroll-container');
        if(newScrollContainer) {
            newScrollContainer.scrollTop = dailyScrollMemory;
        }
    }, 10);
}

// ====================================================================
// RENDERIZADO: VISTA SEMANAL
// ====================================================================
function renderGrillaSemanal() {
    const grid = document.getElementById('gridSemanal');
    grid.innerHTML = '';
    const fechaHoy = getTodayString();

    diasSemana.forEach(dia => {
        const col = document.createElement('div');
        col.className = 'day-column';
        const headerClass = dia.fecha === fechaHoy ? 'day-header today' : 'day-header';

        col.innerHTML = `<div class="${headerClass}"><div class="day-name">${dia.nombre}</div><div class="day-date">${dia.diaMes} ${dia.mesNombre}</div></div>`;

        const tasksContainer = document.createElement('div');
        tasksContainer.className = 'day-tasks';

        const fasesDia = fasesGlobales.filter(f => f.fecha_programada === dia.fecha && (f.tipo_operacion !== 'INCUBACION' || f.es_subtarea_muestreo === true));
        if (fasesDia.length === 0) tasksContainer.innerHTML = `<div style="text-align:center; color:#475569; font-size:0.8rem; margin-top:1rem;">Sin programación</div>`;

        fasesDia.forEach(f => {
            const estaIniciada = ['EN_PROGRESO', 'COMPLETADA'].includes(f.estado);
            let stateClass = '';
            if (f.estado === 'EN_PROGRESO') stateClass = 'state-progreso';
            if (f.estado === 'COMPLETADA') stateClass = 'state-completado';
            if (f.estado === 'OMITIDA') stateClass = 'state-omitida';

            const card = document.createElement('div');
            card.id = `weekly-task-${f.id}`;
            card.className = `task-card ${f.id === faseSeleccionadaId ? 'selected' : ''} ${estaIniciada ? 'locked' : ''} ${stateClass}`;
            card.onclick = () => seleccionarFase(f.id);

            let delayHtml = '';
            if (f.inicio_base_cpm && f.inicio_programado) {
                const diffHours = (new Date(f.inicio_programado) - new Date(f.inicio_base_cpm)) / 3600000;
                if (diffHours > 0) delayHtml = `<span class="badge-delay">+${diffHours.toFixed(1)}h</span>`;
                else if (diffHours < 0) delayHtml = `<span class="badge-adelanto" title="Adelantada respecto a la línea base">${diffHours.toFixed(1)}h</span>`;
            }

            const opsDetalles = f.operadores_asignados || [];
            const headcountReq = f.personal_requerido || 1;
            let assigneesHTML = opsDetalles.length > 0 
                ? `<div class="task-resources-preview">${opsDetalles.map(a => `<span class="tag-micro op">👤 ${a.operador_nombre.split(' ')[0]}</span>`).join('')}</div>`
                : `<div class="task-assignee-box"><span class="badge-unassigned">⚠️ Sin Asignar</span></div>`;

            card.innerHTML = `
                <div class="task-time"><span>⏰ ${formatearRangoFase(f.inicio_programado, f.fin_programado)}</span> <span style="color:var(--text-muted);">${f.estado}</span></div>
                <div class="task-title">[${f.operacion_id_paso}] ${f.operacion_nombre}</div>
                <div style="font-size:0.8rem; color:#475569; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.2rem;">
                    <span>Lote: ${f.lote_codigo}</span>
                    <div style="display:flex; gap:0.25rem; align-items:center; flex-wrap:wrap;">${insigniaAlertas(f.id)}${delayHtml}${insigniaEquipos(f)}<span class="badge-headcount">👥 ${opsDetalles.length}/${headcountReq}</span></div>
                </div>
                ${assigneesHTML}
            `;
            tasksContainer.appendChild(card);
        });
        col.appendChild(tasksContainer);
        grid.appendChild(col);
    });
}

function seleccionarFase(faseId) {
    faseSeleccionadaId = faseId;
    document.querySelectorAll('.task-card, .daily-task-block').forEach(el => el.classList.remove('selected'));

    const dailyBlock = document.getElementById(`daily-task-${faseId}`);
    if (dailyBlock) dailyBlock.classList.add('selected');

    const weeklyCard = document.getElementById(`weekly-task-${faseId}`);
    if (weeklyCard) weeklyCard.classList.add('selected');

    renderPanelDetalle(faseId);
}

// Horario en que se asigna personal (misma regla que `ventana_asignacion` del servidor): el programado, salvo que la tarea
// siga pendiente y su hora ya pasó; entonces cuenta desde ahora, con la misma duración.
function ventanaAsignacion(fase) {
    const inicio = new Date(fase.inicio_programado);
    const fin = new Date(fase.fin_programado);
    const ahora = new Date();
    if (fase.estado === 'PENDIENTE' && inicio < ahora) {
        ahora.setSeconds(0, 0);
        return { inicio: ahora, fin: new Date(ahora.getTime() + (fin - inicio)), retrasada: true };
    }
    return { inicio, fin, retrasada: false };
}

const fechaLocalISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// Traslape por fecha-hora completas (detecta cruces de medianoche y fases de varios días); misma regla que el servidor
// Personal con turno que cubre la hora de inicio de la actividad y sin otra tarea encimada (lo calcula el servidor,
// con la misma regla que la alerta "no tiene turno a las…"; considera turnos nocturnos, retardos y salidas anticipadas).
async function cargarDisponibles(fase) {
    let lista;
    try {
        const res = await fetch(`/api/fases-lote/${fase.id}/disponibles/`);
        if (!res.ok) throw new Error();
        const datos = await res.json();
        lista = datos.operadores;
        const titulo = document.getElementById('tituloDisponibles');
        if (titulo && faseSeleccionadaId === fase.id) titulo.innerHTML = textoTituloDisponibles(fase, datos);
    } catch (e) {
        lista = null;
    }
    const caja = document.getElementById('listaDisponibles');
    if (!caja || faseSeleccionadaId !== fase.id) return;  // el usuario ya eligió otra fase
    if (lista === null) { caja.innerHTML = '<div class="empty-state">⚠️ No se pudo consultar el personal disponible.</div>'; return; }
    if (!lista.length) { caja.innerHTML = '<div class="empty-state">⚠️ Nadie tiene turno libre a esa hora.</div>'; return; }
    const hora = (iso) => new Date(iso).toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: false });
    caja.innerHTML = lista.map(op => `
        <div class="op-availability-card available">
            <div class="op-header">
                <div>
                    <div class="op-name">${escaparHtml(op.nombre)}</div>
                    <div class="op-status-text">Turno: <strong>${escaparHtml(op.codigo_turno)}</strong> · ${hora(op.turno_inicio)} – ${hora(op.turno_fin)}</div>
                    ${op.cubre_toda ? '' : `<div class="op-aviso-turno">⚠️ Su turno termina a las ${hora(op.turno_fin)}, antes de que acabe la actividad.</div>`}
                </div>
            </div>
            <button class="btn-assign" data-permiso="asignar_personal" onclick="asignarOperadorFase(${fase.id}, ${op.id}, ${op.rol || 1})">Asignar</button>
        </div>`).join('');
}

// Título de la lista de disponibles: la hora programada o, si la tarea va retrasada, desde ahora
function textoTituloDisponibles(fase, ventana) {
    const desde = ventana.desde || ventana.inicio, hasta = ventana.hasta || ventana.fin;
    const rango = formatearRangoFase(desde, hasta);
    if (!ventana.retrasada) return `Disponibles a las ${rango} (${fase.fecha_programada}):`;
    return `Disponibles ahora, ${rango} (${fechaLocalISO(new Date(desde))}):
            <span class="disponibles-retraso">⏰ La tarea va retrasada (programada a las ${formatearRangoFase(fase.inicio_programado, fase.fin_programado)}
            del ${fase.fecha_programada}); se muestra el personal en turno ahora.</span>`;
}

function checkConflictosOperador(operadorId, fase) {
    if (!fase.inicio_programado || !fase.fin_programado) return null;
    const { inicio, fin } = ventanaAsignacion(fase);

    for (const f of fasesGlobales) {
        if (f.id === fase.id || f.estado === 'OMITIDA' || !f.inicio_programado || !f.fin_programado) continue;
        if (!(f.operadores_asignados || []).some(a => a.operador === operadorId)) continue;
        // Una fase completada solo ocupa su horario real: terminarla libera al operador (igual que el servidor)
        const desde = new Date(f.estado === 'COMPLETADA' ? (f.fecha_inicio_real || f.inicio_programado) : f.inicio_programado);
        const hasta = f.estado === 'COMPLETADA' ? (f.fecha_fin_real ? new Date(f.fecha_fin_real) : null) : new Date(f.fin_programado);
        if (!hasta) continue;
        if (inicio < hasta && fin > desde) {
            return `Cruce con: [${f.operacion_id_paso}] ${f.lote_codigo}`;
        }
    }
    return null;
}

// ====================================================================
// [RESTAURADO] PANEL DE DETALLE COMPLETO (OPERADORES, EQUIPOS, MATERIALES)
// ====================================================================
function renderPanelDetalle(faseId) {
    const panel = document.getElementById('panelDisponibilidad');
    const fase = fasesGlobales.find(f => f.id === faseId);
    if (!fase) return;

    const estaIniciada = ['EN_PROGRESO', 'COMPLETADA'].includes(fase.estado);
    const lockClass = estaIniciada ? 'locked' : '';
    const bannerLock = estaIniciada ? `<div class="gxp-lock-banner"><span>🔒</span> <div><strong>Bloqueo eBR:</strong> Tarea iniciada en planta.</div></div>` : '';

    // 1. Operadores Asignados
    const operadoresAsignados = fase.operadores_asignados || [];
    const operadoresAsignadosIds = operadoresAsignados.map(a => a.operador);
    const headcountReq = fase.personal_requerido || 1;

    const operadoresChips = operadoresAsignados.map(a => {
        const btnRemover = estaIniciada ? '' : `<span class="btn-remove-tag" data-permiso="asignar_personal" onclick="removerAsignacionOperador(${a.id})">✕</span>`;
        const opData = operadoresGlobales.find(o => o.id === a.operador);
        let advertenciaUI = '';
        let extraClass = '';

        if (opData) {
            // Una tarea retrasada se revisa contra el turno de hoy, no el de su fecha planeada
            const vent = ventanaAsignacion(fase);
            const fechaTurno = vent.retrasada ? fechaLocalISO(vent.inicio) : fase.fecha_programada;
            const tDia = opData.turnos.find(t => t.fecha === fechaTurno);
            // Si no se cargó el turno de hoy, el aviso "sin turno" lo da el servidor en las alertas de la fase
            if ((!tDia && !vent.retrasada) || (tDia && tDia.codigo_turno === 'OFF')) {
                advertenciaUI = `<span style="font-size:0.84rem; font-weight:bold; margin-left:4px;">[⚠️ DÍA OFF]</span>`;
                extraClass = 'danger-chip';
            } else {
                const conf = checkConflictosOperador(a.operador, fase);
                if (conf) {
                    advertenciaUI = `<span style="font-size:0.84rem; font-weight:bold; margin-left:4px;" title="${conf}">[⚠️ CRUCE]</span>`;
                    extraClass = 'warning-chip';
                }
            }
        }
        return `<span class="resource-chip op ${extraClass}">👤 ${a.operador_nombre.split(' ')[0]} ${advertenciaUI} ${btnRemover}</span>`;
    }).join('');

    // 2. Equipos: requerimiento por tipo (de la receta) y reservas de equipos concretos
    const equiposEditables = fase.estado === 'PENDIENTE';
    const equiposHtml = htmlEquiposFase(fase, { editable: equiposEditables });

    // 3. Materiales del lote (copiados de la receta; ajustes y retiros con motivo GxP)
    const materialesEditables = !['EN_PROGRESO', 'COMPLETADA', 'OMITIDA'].includes(fase.estado);
    const materialesHtml = renderMaterialesFase(fase, materialesEditables);

    let horaInicioTxt = fase.hora_inicio_programada ? fase.hora_inicio_programada.substring(0,5) : '00:00';
    const botonAjustarHtml = estaIniciada 
        ? `<button class="btn-icon" title="Bloqueado" disabled>🔒</button>` 
        : `<button class="btn-icon" data-permiso="reprogramar_fase" title="Reprogramar" onclick="abrirModalReprogramar(${fase.id}, '${fase.fecha_programada}', '${horaInicioTxt}')">✏️ Ajustar</button>`;

    const alertas = alertasGlobales[fase.id] || [];
    const alertasHtml = alertas.length ? `
        <div class="alertas-programacion">
            <div class="alertas-programacion__titulo">⚠️ Revisar tras el ajuste de programación</div>
            <ul>${alertas.map(a => `<li>${escaparHtml(a)}</li>`).join('')}</ul>
        </div>` : '';

    let html = `
        ${bannerLock}
        ${alertasHtml}
        <div class="info-card ${lockClass}">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <h4>[${fase.operacion_id_paso}] ${fase.operacion_nombre}</h4>
                    <div>Lote: <strong>${fase.lote_codigo}</strong></div>
                </div>
                ${botonAjustarHtml}
            </div>
            <div>📅 Fecha: <strong>${fase.fecha_programada}</strong> | ⏰ ${formatearRangoFase(fase.inicio_programado, fase.fin_programado)}</div>
            <div style="color:var(--text-muted);">👥 Personal: <strong>${operadoresAsignados.length} / ${headcountReq}</strong></div>

            <div class="resource-section">
                <div class="resource-title">OPERADORES ASIGNADOS:</div>
                <div class="resource-tags-container">${operadoresChips || '<span style="color:#64748b; font-size:0.8rem;">Sin operador</span>'}</div>
            </div>

            <div class="resource-section">
                <div class="resource-title">EQUIPOS:</div>
                ${equiposHtml}
            </div>

            <div class="resource-section">
                <div class="resource-title">MATERIALES E INSUMOS:</div>
                ${materialesHtml}
                ${materialesEditables ? '<div id="buscadorMaterialFase" class="buscador-material-fase" data-permiso="ajustar_material_lote"></div>' : ''}
            </div>

            <details class="resource-section historial-fase" ontoggle="if (this.open) cargarHistorialFase(${fase.id})">
                <summary class="resource-title">📜 HISTORIAL DE LA FASE</summary>
                <div id="historialFase" class="historial-fase__contenido"><div class="aud-vacio">Cargando…</div></div>
            </details>
        </div>
    `;

    if (!estaIniciada) {
        html += `<div class="disponibles-titulo" id="tituloDisponibles">${textoTituloDisponibles(fase, ventanaAsignacion(fase))}</div>
                 <div id="listaDisponibles"><div class="empty-state">Buscando personal con turno a esa hora…</div></div>`;
        cargarDisponibles(fase);
    }
    panel.innerHTML = html;
    if (equiposEditables) cargarCandidatosEquipos(panel);

    if (materialesEditables) {
        crearSelectorMateriales(document.getElementById('buscadorMaterialFase'), {
            enLinea: true,
            placeholder: '➕ Agregar material extra a esta fase…',
            obtenerMateriales: () => materialesGlobales,
            excluir: () => new Set((fase.materiales || []).filter(m => m.activo).map(m => m.material)),
            alSeleccionar: (material) => abrirModalMaterialFase('agregar', fase.id, { material }),
        });
    }
}

function renderMaterialesFase(fase, editable) {
    const materiales = fase.materiales || [];
    const vigentes = materiales.filter(m => m.activo);
    const retirados = materiales.filter(m => !m.activo);
    if (!materiales.length) return '<div class="materiales-fase-vacio">Esta actividad no requiere materiales.</div>';

    const filas = vigentes.map(m => {
        const momento = m.momento_requerido ? new Date(m.momento_requerido) : null;
        const cuando = momento
            ? `${momento.toLocaleDateString('es-MX', { day: '2-digit', month: 'short' })} ${momento.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: false })}`
            : 'sin fecha';
        const anticipacion = m.anticipacion_horas ? ` · ${m.anticipacion_horas} h antes` : '';
        const ajuste = m.ajustado
            ? `<span class="material-fase-ajuste" title="${escaparHtml(m.motivo_ajuste)}">${m.cantidad_receta === null ? 'agregado en el lote' : `receta: ${formatearCantidad(m.cantidad_receta, m.unidad_medida)}`}</span>`
            : '';
        const acciones = editable ? `
            <button class="btn-icon" data-permiso="ajustar_material_lote" title="Ajustar cantidad o anticipación" onclick="abrirModalMaterialFase('ajustar', ${fase.id}, { id: ${m.id} })">✏️</button>
            <button class="btn-icon" data-permiso="ajustar_material_lote" title="Retirar de esta fase" onclick="abrirModalMaterialFase('retirar', ${fase.id}, { id: ${m.id} })">✕</button>` : '';
        return `
            <div class="material-fase">
                <div class="material-fase__info">
                    <div><strong>${formatearCantidad(m.cantidad, m.unidad_medida)}</strong> ${escaparHtml(m.material_nombre)} ${iconoAlmacenamiento(m.condicion_almacenamiento)}</div>
                    <div class="material-fase__meta">⏰ ${cuando}${anticipacion} ${ajuste}</div>
                </div>
                <div class="material-fase__acciones">${acciones}</div>
            </div>`;
    }).join('');

    const chipsRetirados = retirados.map(m =>
        `<span class="chip-material chip-material--retirado" title="Retirado: ${escaparHtml(m.motivo_ajuste)}">${escaparHtml(m.material_nombre)}</span>`
    ).join('');

    return `${filas || '<div class="materiales-fase-vacio">Todos los materiales fueron retirados.</div>'}
        ${chipsRetirados ? `<div class="materiales-fase-retirados">Retirados: ${chipsRetirados}</div>` : ''}`;
}

// --- MODAL DE MATERIAL DEL LOTE (agregar / ajustar / retirar) --------------
let materialFaseEnEdicion = null;

function abrirModalMaterialFase(modo, faseId, { id = null, material = null }) {
    const fase = fasesGlobales.find(f => f.id === faseId);
    const actual = id ? (fase.materiales || []).find(m => m.id === id) : null;
    const nombre = actual ? actual.material_nombre : material.nombre;
    const unidad = actual ? actual.unidad_medida : material.unidad_medida;
    materialFaseEnEdicion = { modo, faseId, id, material: material ? material.id : actual.material };

    const titulos = { agregar: '➕ Agregar material a la fase', ajustar: '✏️ Ajustar material del lote', retirar: '✕ Retirar material de la fase' };
    document.getElementById('materialFaseTitulo').innerText = titulos[modo];
    document.getElementById('materialFaseResumen').innerHTML = `
        <strong>${escaparHtml(nombre)}</strong><br>
        <span>[${escaparHtml(fase.operacion_id_paso)}] ${escaparHtml(fase.operacion_nombre)} · Lote ${escaparHtml(fase.lote_codigo)}</span>
        ${actual && actual.cantidad_receta !== null ? `<br><span>Cantidad de receta: ${formatearCantidad(actual.cantidad_receta, unidad)}</span>` : ''}`;
    document.getElementById('materialFaseCampos').style.display = modo === 'retirar' ? 'none' : 'flex';
    document.getElementById('materialFaseUnidad').innerText = unidad || '';
    document.getElementById('inputMaterialFaseCantidad').value = actual ? Number(actual.cantidad) : 1;
    document.getElementById('inputMaterialFaseAnticipacion').value = actual ? actual.anticipacion_horas : 0;
    document.getElementById('inputMaterialFaseMotivo').value = '';
    document.getElementById('btnConfirmarMaterialFase').innerText = modo === 'retirar' ? 'Retirar' : 'Guardar';
    document.getElementById('modalMaterialFase').style.display = 'flex';
    document.getElementById(modo === 'retirar' ? 'inputMaterialFaseMotivo' : 'inputMaterialFaseCantidad').focus();
}

function cerrarModalMaterialFase() {
    document.getElementById('modalMaterialFase').style.display = 'none';
    materialFaseEnEdicion = null;
}

async function confirmarMaterialFase() {
    if (!materialFaseEnEdicion) return;
    const { modo, faseId, id, material } = materialFaseEnEdicion;
    const motivo = document.getElementById('inputMaterialFaseMotivo').value.trim();
    const datos = {
        motivo,
        cantidad: document.getElementById('inputMaterialFaseCantidad').value,
        anticipacion_horas: document.getElementById('inputMaterialFaseAnticipacion').value,
    };
    if (motivo.length < 5) return alert("Indique el motivo del cambio (mínimo 5 caracteres).");

    const url = modo === 'agregar' ? '/api/materiales-fase/agregar/' : `/api/materiales-fase/${id}/${modo}/`;
    if (modo === 'agregar') Object.assign(datos, { fase: faseId, material });

    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify(datos),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || JSON.stringify(err));
        }
        cerrarModalMaterialFase();
        await cargarDatosPlanificacion();
    } catch (e) {
        alert("Error: " + e.message);
    }
}

// --- FUNCIONES DE REPROGRAMACIÓN Y RECURSOS ---
function abrirModalReprogramar(faseId, fechaActual, horaActual) {
    document.getElementById('reprogramarFaseId').value = faseId;
    document.getElementById('inputReprogramarFecha').value = fechaActual;
    document.getElementById('inputReprogramarHora').value = horaActual;
    document.getElementById('selectMotivoReprogramacion').value = '';
    document.getElementById('inputNotasReprogramacion').value = '';
    document.getElementById('modalReprogramar').style.display = 'flex';
}

function cerrarModalReprogramar() {
    document.getElementById('modalReprogramar').style.display = 'none';
}

async function ejecutarReprogramacionAPI() {
    const faseId = document.getElementById('reprogramarFaseId').value;
    const nuevaFecha = document.getElementById('inputReprogramarFecha').value;
    const nuevaHora = document.getElementById('inputReprogramarHora').value;
    const motivo = document.getElementById('selectMotivoReprogramacion').value;
    const notas = document.getElementById('inputNotasReprogramacion').value;

    if (!nuevaFecha || !nuevaHora || !motivo) {
        return alert("Por favor complete los campos obligatorios.");
    }

    try {
        const response = await fetch(`/api/fases-lote/${faseId}/reprogramar/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({
                fecha_programada: nuevaFecha,
                hora_inicio_programada: nuevaHora,
                motivo_reprogramacion: motivo,
                notas_reprogramacion: notas
            })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || "Error al reprogramar.");
        }

        const data = await response.json();
        cerrarModalReprogramar();
        await cargarDatosPlanificacion();
        if (data.mensaje) alert(data.mensaje);
    } catch (error) {
        alert(error.message);
    }
}

async function asignarOperadorFase(faseId, opId, rolId) {
    try {
        const res = await fetch('/api/asignaciones-operador/', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') }, body: JSON.stringify({ fase_lote: faseId, operador: opId, rol_ejercido: rolId, horas_invertidas: 0 }) });
        if (!res.ok) { const err = await res.json(); throw new Error(JSON.stringify(err)); }
        await cargarDatosPlanificacion();
    } catch (e) { alert("Error: " + e.message); }
}

async function removerAsignacionOperador(asigId) {
    try {
        const res = await fetch(`/api/asignaciones-operador/${asigId}/`, { method: 'DELETE', headers: { 'X-CSRFToken': getCookie('csrftoken') } });
        if (!res.ok) throw new Error('Error de red');
        await cargarDatosPlanificacion();
    } catch (e) { alert("Error: " + e.message); }
}

actualizarMecanismoTiempo();
cargarDatosPlanificacion();


// --- Historial de la fase (bitácora de auditoría): se carga al abrir la sección ---
async function cargarHistorialFase(faseId) {
    const contenedor = document.getElementById('historialFase');
    if (!contenedor) return;
    try {
        const datos = await cargarHistorialAuditoria({ fase: faseId, limite: 50 });
        renderizarHistorialAuditoria(contenedor, datos.resultados, { vacio: 'Sin cambios registrados en esta fase.' });
    } catch (e) {
        contenedor.innerHTML = `<div class="aud-vacio">${e.message}</div>`;
    }
}


// Insignia ⚠️ con el número de alertas de programación de la fase (vacía si no tiene)
function insigniaAlertas(faseId) {
    const alertas = alertasGlobales[faseId] || [];
    if (!alertas.length) return '';
    return `<span class="badge-alerta" data-tooltip="${escaparHtml(alertas.join('\n'))}">⚠️ ${alertas.length}</span>`;
}

// Insignia 🏗️ reservados/requeridos (vacía si la fase no pide equipo)
function insigniaEquipos(fase) {
    const resumen = resumenEquiposFase(fase);
    if (!resumen) return '';
    const clase = resumen.completo ? 'badge-equipos' : 'badge-equipos badge-equipos--falta';
    const titulo = resumen.completo ? 'Equipos reservados' : 'Falta reservar equipo';
    return `<span class="${clase}" data-tooltip="${titulo}">🏗️ ${resumen.reservados}/${resumen.requeridos}</span>`;
}

// Usado por core/js/equipos.js para encontrar la fase de los modales
function buscarFaseParaEquipos(faseId) {
    return fasesGlobales.find(f => f.id === faseId);
}

configurarEquipos({ alActualizar: () => cargarDatosPlanificacion() });
