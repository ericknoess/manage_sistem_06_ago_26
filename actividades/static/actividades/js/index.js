// actividades/static/actividades/js/index.js

const diasSemana = [
    { nombre: "Mié", fecha: "2026-07-01" },
    { nombre: "Jue", fecha: "2026-07-02" },
    { nombre: "Vie", fecha: "2026-07-03" },
    { nombre: "Sáb", fecha: "2026-07-04" },
    { nombre: "Dom", fecha: "2026-07-05" },
    { nombre: "Lun", fecha: "2026-07-06" },
    { nombre: "Mar", fecha: "2026-07-07" }
];

let actividadesGlobales = [];
let operadoresGlobales = [];
let equiposGlobales = [];
let materialesGlobales = [];
let tiposTurnoGlobales = [];
let tareaSeleccionadaId = null;

async function cargarDatos() {
    try {
        const [resAct, resOp, resEq, resMat, resTurnos] = await Promise.all([
            fetch('/api/actividades-semanales/'),
            fetch('/api/operadores/?activo=true'),
            fetch('/api/equipos/'),
            fetch('/api/materiales/'),
            fetch('/api/tipos-turno/')
        ]);

        if (!resAct.ok || !resOp.ok || !resEq.ok || !resMat.ok || !resTurnos.ok) throw new Error('Error al sincronizar datos');

        actividadesGlobales = await resAct.json();
        operadoresGlobales = await resOp.json();
        equiposGlobales = await resEq.json();
        materialesGlobales = await resMat.json();
        tiposTurnoGlobales = await resTurnos.json();

        renderGrillaSemanal();
        if (tareaSeleccionadaId) {
            renderPanelDetalle(tareaSeleccionadaId);
        }
    } catch (error) {
        console.error("Error:", error);
    }
}

function renderGrillaSemanal() {
    const grid = document.getElementById('gridSemanal');
    grid.innerHTML = '';

    diasSemana.forEach(dia => {
        const col = document.createElement('div');
        col.className = 'day-column';

        const partesFecha = dia.fecha.split('-');
        col.innerHTML = `
            <div class="day-header">
                <div class="day-name">${dia.nombre}</div>
                <div class="day-date">${partesFecha[2]} Jul</div>
            </div>
        `;

        const tasksContainer = document.createElement('div');
        tasksContainer.className = 'day-tasks';

        const tareasDia = actividadesGlobales.filter(t => t.fecha === dia.fecha);

        if (tareasDia.length === 0) {
            tasksContainer.innerHTML = `<div style="text-align:center; color:#475569; font-size:0.65rem; margin-top:1rem;">Sin tareas</div>`;
        }

        tareasDia.forEach(t => {
            const card = document.createElement('div');
            card.className = `task-card ${t.id === tareaSeleccionadaId ? 'selected' : ''}`;
            card.onclick = () => seleccionarTarea(t.id);

            // Renderizar avatares o badges de operadores asignados (Multi-operador)
            let assigneesHTML = '';
            const opsDetalles = t.operadores_asignados_detalles || [];
            const headcountReq = t.personal_requerido || 1;

            if (opsDetalles.length > 0) {
                assigneesHTML = `<div class="task-resources-preview">`;
                opsDetalles.forEach(op => {
                    assigneesHTML += `<span class="tag-micro op" title="${op.nombre}">👤 ${op.nombre.split(' ')[0]}</span>`;
                });
                assigneesHTML += `</div>`;
            } else {
                assigneesHTML = `
                    <div class="task-assignee-box">
                        <span class="badge-unassigned">⚠️ Sin Asignar</span>
                    </div>
                `;
            }

            let recursosHTML = '';
            if ((t.equipos_detalles && t.equipos_detalles.length) || (t.materiales_detalles && t.materiales_detalles.length)) {
                recursosHTML = '<div class="task-resources-preview">';
                (t.equipos_detalles || []).forEach(eq => {
                    recursosHTML += `<span class="tag-micro eq" title="${eq.nombre}">⚙️ ${eq.id}</span>`;
                });
                (t.materiales_detalles || []).forEach(mat => {
                    recursosHTML += `<span class="tag-micro mat" title="${mat.nombre}">🧪 ${mat.id}</span>`;
                });
                recursosHTML += '</div>';
            }

            card.innerHTML = `
                <div class="task-time">⏰ ${t.hora_inicio.substring(0,5)} - ${t.hora_fin.substring(0,5)}</div>
                <div class="task-title">${t.titulo}</div>
                <div style="font-size:0.6rem; color:#94a3b8; display:flex; justify-content:space-between;">
                    <span>Lote: ${t.lote_codigo}</span>
                    <span class="badge-headcount">👥 ${opsDetalles.length}/${headcountReq}</span>
                </div>
                {recursosHTML}
                {assigneesHTML}
            `;
            // Nota: reemplazamos la línea anterior para interpolación correcta de variables en JS
            card.innerHTML = `
                <div class="task-time">⏰ ${t.hora_inicio.substring(0,5)} - ${t.hora_fin.substring(0,5)}</div>
                <div class="task-title">${t.titulo}</div>
                <div style="font-size:0.6rem; color:#94a3b8; display:flex; justify-content:space-between;">
                    <span>Lote: ${t.lote_codigo}</span>
                    <span class="badge-headcount">👥 ${opsDetalles.length}/${headcountReq}</span>
                </div>
                ${recursosHTML}
                ${assigneesHTML}
            `;

            tasksContainer.appendChild(card);
        });

        col.appendChild(tasksContainer);
        grid.appendChild(col);
    });
}

function seleccionarTarea(tareaId) {
    tareaSeleccionadaId = tareaId;
    renderGrillaSemanal();
    renderPanelDetalle(tareaId);
}

function renderPanelDetalle(tareaId) {
    const panel = document.getElementById('panelDisponibilidad');
    const tarea = actividadesGlobales.find(t => t.id === tareaId);
    if (!tarea) return;

    // Equipos y Materiales
    const equiposAsociadosIds = tarea.equipos || [];
    const equiposChips = equiposAsociadosIds.map(eqId => {
        const eq = equiposGlobales.find(e => e.id === eqId);
        return `<span class="resource-chip eq">⚙️ ${eq ? eq.nombre : eqId} <span class="btn-remove-tag" onclick="actualizarRecursos(${tarea.id}, 'equipo', '${eqId}', 'remover')">✕</span></span>`;
    }).join('');

    const equiposDisponiblesOpts = equiposGlobales
        .filter(eq => !equiposAsociadosIds.includes(eq.id))
        .map(eq => `<option value="${eq.id}">${eq.nombre}</option>`)
        .join('');

    const materialesAsociadosIds = tarea.materiales || [];
    const materialesChips = materialesAsociadosIds.map(matId => {
        const mat = materialesGlobales.find(m => m.id === matId);
        return `<span class="resource-chip mat">🧪 ${mat ? mat.nombre : matId} <span class="btn-remove-tag" onclick="actualizarRecursos(${tarea.id}, 'material', '${matId}', 'remover')">✕</span></span>`;
    }).join('');

    const materialesDisponiblesOpts = materialesGlobales
        .filter(mat => !materialesAsociadosIds.includes(mat.id))
        .map(mat => `<option value="${mat.id}">${mat.nombre}</option>`)
        .join('');

    // Operadores Asignados Actualmente (Multi-operador)
    const operadoresAsignadosIds = tarea.operadores_asignados || [];
    const headcountReq = tarea.personal_requerido || 1;

    const operadoresChips = operadoresAsignadosIds.map(opId => {
        const op = operadoresGlobales.find(o => o.id === opId);
        return `<span class="resource-chip op">👤 ${op ? op.nombre : opId} <span class="btn-remove-tag" onclick="gestionarOperador(${tarea.id}, ${opId}, 'remover')">✕</span></span>`;
    }).join('');

    let html = `
        <div class="info-card">
            <h4>${tarea.titulo}</h4>
            <div>Lote: <strong>${tarea.lote_codigo}</strong></div>
            <div>📅 Fecha: <strong>${tarea.fecha}</strong></div>
            <div>⏰ Horario: <strong>${tarea.hora_inicio.substring(0,5)} - ${tarea.hora_fin.substring(0,5)} hrs</strong></div>
            <div>👥 Personal Asignado / Requerido: <strong>${operadoresAsignadosIds.length} / ${headcountReq}</strong></div>

            <!-- SECCIÓN OPERADORES ASIGNADOS -->
            <div class="resource-section" style="margin-top: 0.5rem;">
                <div class="resource-title">OPERADORES EN TAREA:</div>
                <div class="resource-tags-container">
                    ${operadoresChips || '<span style="color:#64748b; font-size:0.65rem;">Ningún operador asignado</span>'}
                </div>
            </div>

            <!-- SECCIÓN EQUIPOS -->
            <div class="resource-section" style="margin-top: 0.5rem;">
                <div class="resource-title">EQUIPOS REQUERIDOS:</div>
                <div class="resource-tags-container">
                    ${equiposChips || '<span style="color:#64748b; font-size:0.65rem;">Ninguno asignado</span>'}
                </div>
                <select class="select-resource" onchange="actualizarRecursos(${tarea.id}, 'equipo', this.value, 'agregar')">
                    <option value="" disabled selected>+ Agregar Equipo...</option>
                    ${equiposDisponiblesOpts}
                </select>
            </div>

            <!-- SECCIÓN MATERIALES -->
            <div class="resource-section" style="margin-top: 0.5rem;">
                <div class="resource-title">MATERIALES Y INSUMOS:</div>
                <div class="resource-tags-container">
                    ${materialesChips || '<span style="color:#64748b; font-size:0.65rem;">Ninguno asignado</span>'}
                </div>
                <select class="select-resource" onchange="actualizarRecursos(${tarea.id}, 'material', this.value, 'agregar')">
                    <option value="" disabled selected>+ Agregar Material...</option>
                    ${materialesDisponiblesOpts}
                </select>
            </div>
        </div>

        <div style="font-size: 0.75rem; font-weight: bold; color: var(--accent); margin-top: 0.25rem;">
            Personal Disponible en Horario:
        </div>
    `;

    // Intervalo de tiempo absoluto de la tarea
    const tareaInicioDT = new Date(`${tarea.fecha}T${tarea.hora_inicio}`);
    let tareaFinDT = new Date(`${tarea.fecha}T${tarea.hora_fin}`);
    if (tarea.hora_fin < tarea.hora_inicio) {
        tareaFinDT.setDate(tareaFinDT.getDate() + 1);
    }

    // Filtrar operadores disponibles que NO estén ya asignados
    const operadoresDisponibles = operadoresGlobales.filter(op => {
        if (operadoresAsignadosIds.includes(op.id)) return false; // Ya asignado

        const turnoAsignadoDia = (op.turnos || []).find(tu => tu.fecha === tarea.fecha);
        if (!turnoAsignadoDia || !turnoAsignadoDia.codigo_turno) return false;

        const tipoTurnoMaster = tiposTurnoGlobales.find(tt => tt.codigo === turnoAsignadoDia.codigo_turno);
        if (!tipoTurnoMaster || tipoTurnoMaster.es_descanso) return false;

        if (tipoTurnoMaster.hora_inicio && tipoTurnoMaster.hora_fin) {
            const turnoInicioDT = new Date(`${turnoAsignadoDia.fecha}T${tipoTurnoMaster.hora_inicio}`);
            let turnoFinDT = new Date(`${turnoAsignadoDia.fecha}T${tipoTurnoMaster.hora_fin}`);
            if (tipoTurnoMaster.hora_fin < tipoTurnoMaster.hora_inicio) {
                turnoFinDT.setDate(turnoFinDT.getDate() + 1);
            }
            return (tareaInicioDT >= turnoInicioDT && tareaFinDT <= turnoFinDT);
        }
        return true;
    });

    if (operadoresDisponibles.length === 0) {
        html += `<div class="empty-state">No hay más operadores disponibles en este horario.</div>`;
    }

    operadoresDisponibles.forEach(op => {
        const turnoAsignadoDia = (op.turnos || []).find(tu => tu.fecha === tarea.fecha);
        let estadoHorarioTxt = "Disponible en Turno";
        if (turnoAsignadoDia && turnoAsignadoDia.codigo_turno) {
            const tipoTurnoMaster = tiposTurnoGlobales.find(tt => tt.codigo === turnoAsignadoDia.codigo_turno);
            if (tipoTurnoMaster && tipoTurnoMaster.hora_inicio && tipoTurnoMaster.hora_fin) {
                estadoHorarioTxt = `Turno ${tipoTurnoMaster.codigo} (${tipoTurnoMaster.hora_inicio.substring(0, 5)} - ${tipoTurnoMaster.hora_fin.substring(0, 5)})`;
            } else {
                estadoHorarioTxt = `Turno: ${turnoAsignadoDia.codigo_turno}`;
            }
        }

        html += `
            <div class="op-availability-card available">
                <div class="op-header">
                    ${op.foto ? `<img src="${op.foto}" class="avatar-lg">` : `<div class="avatar-lg" style="background:#334155;"></div>`}
                    <div>
                        <div class="op-name">${op.nombre}</div>
                        <div class="op-status-text">${estadoHorarioTxt}</div>
                    </div>
                </div>
                <button class="btn-assign" onclick="gestionarOperador(${tarea.id}, ${op.id}, 'agregar')">Asignar</button>
            </div>
        `;
    });

    panel.innerHTML = html;
}

async function gestionarOperador(tareaId, operadorId, accion) {
    const tarea = actividadesGlobales.find(t => t.id === tareaId);
    if (!tarea) return;

    let operadoresActuales = [...(tarea.operadores_asignados || [])];

    if (accion === 'agregar') {
        if (!operadoresActuales.includes(operadorId)) {
            operadoresActuales.push(operadorId);
        }
    } else if (accion === 'remover') {
        operadoresActuales = operadoresActuales.filter(id => id !== operadorId);
    }

    try {
        const response = await fetch(`/api/actividades-semanales/${tareaId}/`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ operadores_asignados: operadoresActuales })
        });

        if (!response.ok) throw new Error('Error al actualizar operadores asignados');
        await cargarDatos();
    } catch (error) {
        alert("Error: " + error.message);
    }
}

async function actualizarRecursos(tareaId, tipo, recursoId, accion) {
    if (!recursoId) return;
    const tarea = actividadesGlobales.find(t => t.id === tareaId);
    if (!tarea) return;

    let nuevosEquipos = [...(tarea.equipos || [])];
    let nuevosMateriales = [...(tarea.materiales || [])];

    if (tipo === 'equipo') {
        if (accion === 'agregar' && !nuevosEquipos.includes(recursoId)) nuevosEquipos.push(recursoId);
        if (accion === 'remover') nuevosEquipos = nuevosEquipos.filter(id => id !== recursoId);
    } else if (tipo === 'material') {
        if (accion === 'agregar' && !nuevosMateriales.includes(recursoId)) nuevosMateriales.push(recursoId);
        if (accion === 'remover') nuevosMateriales = nuevosMateriales.filter(id => id !== recursoId);
    }

    try {
        const response = await fetch(`/api/actividades-semanales/${tareaId}/`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                equipos: nuevosEquipos,
                materiales: nuevosMateriales
            })
        });

        if (!response.ok) throw new Error('Error al actualizar recursos');
        await cargarDatos();
    } catch (error) {
        alert("Error: " + error.message);
    }
}


cargarDatos();
