// procesos/static/procesos/js/index.js

let procesosGlobales = [];
let materialesGlobales = [];
let rolesGlobales = []; 
let procesoSeleccionado = null;
let mostrandoArchivados = false;
let ultimoDataCPM = null; 

// Materiales que se están editando en cada modal: [{ material, cantidad, anticipacion_horas, aplica_a }]
const materialesBuilder = { crear: [], editar: [] };
let buscadoresMaterialesListos = false;

// GESTIÓN DEL NIVEL DE ZOOM (px por hora) - CONFIGURACIÓN CON 6px/h
let zoomActual = 'normal';
const ZOOM_CONFIG = {
    'semanas': { pxPorHora: 6, texto: 'Escala: Vista Semanal (6 px/hora)', intervaloLabels: 48 },
    'dias': { pxPorHora: 12, texto: 'Escala: Vista Días (12 px/hora)', intervaloLabels: 24 },
    'normal': { pxPorHora: 35, texto: 'Escala: Vista Normal (35 px/hora)', intervaloLabels: 4 },
    'horas': { pxPorHora: 65, texto: 'Escala: Vista Detalle (65 px/hora)', intervaloLabels: 1 }
};

async function cargarCatalogosGlobales() {
    try {
        const [resProc, resMat, resRoles] = await Promise.all([
            fetch('/api/procesos-maestros/'),
            fetch('/api/materiales/'),
            fetch('/api/roles-operador/')
        ]);
        procesosGlobales = await resProc.json();
        materialesGlobales = await resMat.json();
        rolesGlobales = await resRoles.json();

        inicializarBuscadoresMateriales();
        renderizarListaProcesos();

        if (document.getElementById('rolesBuilderCrear').children.length === 0) {
            agregarFilaRolBuilder('crear');
        }

        if (procesoSeleccionado) {
            const actualizado = procesosGlobales.find(p => p.id === procesoSeleccionado.id);
            if (actualizado && actualizado.activo !== false && !mostrandoArchivados) {
                seleccionarProceso(actualizado.id);
            } else {
                procesoSeleccionado = null;
                document.getElementById('editorTareas').style.display = 'none';
                document.getElementById('emptyState').style.display = 'block';
                document.getElementById('nombreProcesoSelec').innerText = 'Selecciona un proceso';
                document.getElementById('btnEditarNombreProc').style.display = 'none';
            }
        }
    } catch (err) {
        console.error("Error sincronizando catálogos:", err);
    }
}

// --- MATERIALES DE LA ACTIVIDAD ---------------------------------------------

function inicializarBuscadoresMateriales() {
    if (buscadoresMaterialesListos) return;
    buscadoresMaterialesListos = true;
    ['crear', 'editar'].forEach(modo => {
        const sufijo = modo === 'crear' ? 'Crear' : 'Editar';
        crearSelectorMateriales(document.getElementById(`buscadorMateriales${sufijo}`), {
            enLinea: true,
            obtenerMateriales: () => materialesGlobales,
            excluir: () => new Set(materialesBuilder[modo].map(m => m.material)),
            alSeleccionar: (material) => {
                materialesBuilder[modo].push({ material: material.id, cantidad: 1, anticipacion_horas: 0, aplica_a: 'ACTIVIDAD' });
                renderizarMaterialesBuilder(modo);
                // Lleva el foco a la cantidad recién agregada para capturarla de inmediato
                const filas = document.querySelectorAll(`#materialesBuilder${sufijo} .input-material-cantidad`);
                filas[filas.length - 1]?.select();
            },
        });
    });
}

async function recargarCatalogoMateriales() {
    try {
        const res = await fetch('/api/materiales/');
        materialesGlobales = await res.json();
        renderizarMaterialesBuilder('crear');
        renderizarMaterialesBuilder('editar');
    } catch (err) {
        alert("No se pudo recargar el catálogo de materiales.");
    }
}

function esIncubacionConMuestreo(modo) {
    const tipo = document.getElementById(modo === 'crear' ? 'selectTipoTarea' : 'editOpTipo').value;
    const frec = parseInt(document.getElementById(modo === 'crear' ? 'inputFrecMuestreo' : 'editOpFrecMuestreo').value) || 0;
    return tipo === 'INCUBACION' && frec > 0;
}

function renderizarMaterialesBuilder(modo) {
    const contenedor = document.getElementById(modo === 'crear' ? 'materialesBuilderCrear' : 'materialesBuilderEditar');
    const filas = materialesBuilder[modo];
    const conMuestreo = esIncubacionConMuestreo(modo);
    if (!conMuestreo) filas.forEach(f => f.aplica_a = 'ACTIVIDAD');

    if (!filas.length) {
        contenedor.innerHTML = `<div class="tabla-materiales__vacio">Sin materiales. Búscalos arriba para agregarlos.</div>`;
        return;
    }

    contenedor.innerHTML = `
        <table class="tabla-materiales">
            <thead><tr>
                <th>Material</th>
                <th style="width: 120px;">Cantidad</th>
                <th style="width: 95px;" title="Horas antes del inicio de la actividad en que debe estar disponible">Anticipación (h)</th>
                ${conMuestreo ? '<th style="width: 120px;">Se usa en</th>' : ''}
                <th style="width: 32px;"></th>
            </tr></thead>
            <tbody>
                ${filas.map((f, i) => {
                    const mat = materialesGlobales.find(m => m.id === f.material) || { id: f.material, nombre: f.material };
                    const aviso = mat.activo === false ? '<div class="material-inactivo">⚠️ Inactivo en el catálogo</div>' : '';
                    return `<tr>
                        <td><strong>${escaparHtml(mat.nombre)}</strong><br><span style="color: var(--text-muted);">${escaparHtml(mat.id)} · ${iconoAlmacenamiento(mat.condicion_almacenamiento)} ${escaparHtml(mat.categoria_display || '')}</span>${aviso}</td>
                        <td><div class="celda-cantidad">
                            <input type="number" class="input-material-cantidad" min="0.001" step="any" value="${f.cantidad}"
                                   oninput="materialesBuilder['${modo}'][${i}].cantidad = this.value">
                            <span>${escaparHtml(mat.unidad_medida || '')}</span>
                        </div></td>
                        <td><input type="number" min="0" step="0.5" value="${f.anticipacion_horas}"
                                   oninput="materialesBuilder['${modo}'][${i}].anticipacion_horas = this.value"></td>
                        ${conMuestreo ? `<td><select onchange="materialesBuilder['${modo}'][${i}].aplica_a = this.value">
                            <option value="ACTIVIDAD" ${f.aplica_a === 'ACTIVIDAD' ? 'selected' : ''}>Actividad</option>
                            <option value="MUESTREO" ${f.aplica_a === 'MUESTREO' ? 'selected' : ''}>Cada muestreo</option>
                        </select></td>` : ''}
                        <td><button type="button" class="btn-icon delete" title="Quitar material" onclick="quitarMaterialBuilder('${modo}', ${i})">🗑️</button></td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>
    `;
}

function quitarMaterialBuilder(modo, indice) {
    materialesBuilder[modo].splice(indice, 1);
    renderizarMaterialesBuilder(modo);
}

// Devuelve los materiales listos para la API, o null (con aviso) si alguna cantidad no es válida.
function obtenerMaterialesDesdeBuilder(modo) {
    const materiales = [];
    for (const f of materialesBuilder[modo]) {
        const cantidad = parseFloat(f.cantidad);
        const anticipacion = parseFloat(f.anticipacion_horas) || 0;
        if (!(cantidad > 0)) {
            alert(`La cantidad de [${f.material}] debe ser mayor que cero.`);
            return null;
        }
        if (anticipacion < 0) {
            alert(`La anticipación de [${f.material}] no puede ser negativa.`);
            return null;
        }
        materiales.push({ material: f.material, cantidad: cantidad.toString(), anticipacion_horas: anticipacion, aplica_a: f.aplica_a });
    }
    return materiales;
}

function abrirModalNuevaOperacion() {
    if (!procesoSeleccionado) return alert("Debe seleccionar un proceso maestro primero.");
    document.getElementById('inputPasoId').value = '';
    document.getElementById('inputTareaNombre').value = '';
    document.getElementById('inputTareaDuracion').value = '';
    document.getElementById('inputFrecMuestreo').value = '0';
    document.getElementById('inputDuracionMuestreo').value = '0';
    document.getElementById('inputOpsMuestreo').value = '0';
    document.getElementById('inputDesfase').value = '0';
    document.getElementById('selectPredecesora').value = '';
    document.getElementById('rolesBuilderCrear').innerHTML = '';
    agregarFilaRolBuilder('crear');
    materialesBuilder.crear = [];

    toggleIncubacionFields(false);
    document.getElementById('modalNuevaOperacion').style.display = 'flex';
}

function cerrarModalNuevaOperacion() {
    document.getElementById('modalNuevaOperacion').style.display = 'none';
}

function actualizarSelectEtapas(proc) {
    const selects = [document.getElementById('selectEtapaTarea'), document.getElementById('editOpEtapa')];
    selects.forEach(select => {
        if(!select) return;
        select.innerHTML = '<option value="">-- Actividad Suelta (Sin Etapa) --</option>';
        if (proc && proc.etapas) {
            let sortedEtapas = [...proc.etapas].sort((a,b) => a.orden - b.orden);
            sortedEtapas.forEach(e => {
                select.innerHTML += `<option value="${e.id}">${e.orden} -${e.nombre}</option>`;
            });
        }
    });
}

function abrirModalNuevaEtapa() {
    if (!procesoSeleccionado) return alert("Debe seleccionar un proceso maestro primero.");
    document.getElementById('nuevaEtapaNombre').value = '';
    document.getElementById('nuevaEtapaOrden').value = (procesoSeleccionado.etapas.length + 1) * 10;
    document.getElementById('modalNuevaEtapa').style.display = 'flex';
}

function cerrarModalNuevaEtapa() {
    document.getElementById('modalNuevaEtapa').style.display = 'none';
}

async function crearEtapaAPI() {
    const nombre = document.getElementById('nuevaEtapaNombre').value.trim();
    const orden = parseInt(document.getElementById('nuevaEtapaOrden').value, 10);

    if (!nombre || isNaN(orden)) return alert("Completa el nombre y el orden de la etapa.");

    const res = await fetch('/api/etapas-proceso/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({
            proceso: procesoSeleccionado.id,
            nombre: nombre,
            orden: orden
        })
    });

    if (res.ok) {
        cerrarModalNuevaEtapa();
        cargarCatalogosGlobales();
    } else {
        alert("Error al registrar la etapa en la base de datos.");
    }
}

function agregarFilaRolBuilder(modo, rolId = '', cantidad = 1) {
    const containerId = modo === 'crear' ? 'rolesBuilderCrear' : 'rolesBuilderEditar';
    const container = document.getElementById(containerId);

    const row = document.createElement('div');
    row.className = 'role-row-builder';

    let selectHtml = `<select class="select-rol-item" style="flex: 2; height: 26px; font-size: 0.7rem; padding: 2px;">`;
    selectHtml += `<option value="">-- Seleccionar Rol / Competencia --</option>`;
    rolesGlobales.forEach(r => {
        const selected = (r.id == rolId) ? 'selected' : '';
        selectHtml += `<option value="${r.id}" ${selected}>${r.nombre}</option>`;
    });
    selectHtml += `</select>`;

    row.innerHTML = `
        ${selectHtml}
        <input type="number" class="input-rol-cantidad" value="${cantidad}" min="1" step="1" style="width: 50px; height: 26px; font-size: 0.7rem; padding: 2px;" placeholder="Cant">
        <button type="button" class="btn-icon delete" title="Eliminar fila" style="height: 26px; line-height: 1;" onclick="this.parentElement.remove()">🗑️</button>
    `;
    container.appendChild(row);
}

function obtenerRolesDesdeBuilder(modo) {
    const containerId = modo === 'crear' ? 'rolesBuilderCrear' : 'rolesBuilderEditar';
    const container = document.getElementById(containerId);
    const filas = container.querySelectorAll('.role-row-builder');
    let requerimientos = [];

    filas.forEach(fila => {
        const rolId = fila.querySelector('.select-rol-item').value;
        const cantidad = parseInt(fila.querySelector('.input-rol-cantidad').value, 10);
        if (rolId && !isNaN(cantidad) && cantidad > 0) {
            requerimientos.push({ rol: parseInt(rolId, 10), cantidad: cantidad });
        }
    });
    return requerimientos;
}

function toggleIncubacionFields(isEdit = false) {
    const tipoId = isEdit ? 'editOpTipo' : 'selectTipoTarea';
    const frecId = isEdit ? 'editOpFrecMuestreo' : 'inputFrecMuestreo';
    const durMuestreoId = isEdit ? 'editOpDuracionMuestreo' : 'inputDuracionMuestreo';
    const opsMuestreoId = isEdit ? 'editOpOpsMuestreo' : 'inputOpsMuestreo';

    const tipo = document.getElementById(tipoId).value;
    const frecInput = document.getElementById(frecId);
    const durMuestreoInput = document.getElementById(durMuestreoId);
    const opsMuestreoInput = document.getElementById(opsMuestreoId);

    if (tipo === 'INCUBACION') {
        frecInput.removeAttribute('readonly');
        durMuestreoInput.removeAttribute('readonly');
        opsMuestreoInput.removeAttribute('readonly');
        if (durMuestreoInput.value == 0) durMuestreoInput.value = 0.5;
        if (opsMuestreoInput.value == 0) opsMuestreoInput.value = 1;
    } else {
        frecInput.value = 0;
        frecInput.setAttribute('readonly', 'readonly');
        durMuestreoInput.value = 0;
        durMuestreoInput.setAttribute('readonly', 'readonly');
        opsMuestreoInput.value = 0;
        opsMuestreoInput.setAttribute('readonly', 'readonly');
    }
    renderizarMaterialesBuilder(isEdit ? 'editar' : 'crear');
}

function toggleVistaArchivados() {
    mostrandoArchivados = !mostrandoArchivados;
    const btn = document.getElementById('btnToggleArchivados');
    if (mostrandoArchivados) {
        btn.style.backgroundColor = 'var(--warning)';
        btn.style.color = '#0f172a';
        btn.innerText = '📂 Activos';
    } else {
        btn.style.backgroundColor = '';
        btn.style.color = '';
        btn.innerText = '📦 Archivados';
    }
    procesoSeleccionado = null;
    document.getElementById('editorTareas').style.display = 'none';
    document.getElementById('emptyState').style.display = 'block';
    document.getElementById('nombreProcesoSelec').innerText = 'Selecciona un proceso';
    document.getElementById('btnEditarNombreProc').style.display = 'none';
    renderizarListaProcesos();
}

function renderizarListaProcesos() {
    const container = document.getElementById('listaProcesos');
    container.innerHTML = '';

    const listaFiltrada = procesosGlobales.filter(p => mostrandoArchivados ? p.activo === false : p.activo !== false);

    if (listaFiltrada.length === 0) {
        container.innerHTML = `<div class="empty-state" style="padding:1.5rem; text-align:center; font-size:0.75rem; color:var(--text-muted);">No hay plantillas ${mostrandoArchivados ? 'archivadas' : 'activas'}.</div>`;
        return;
    }

    listaFiltrada.forEach(p => {
        const card = document.createElement('div');
        card.className = `process-item ${procesoSeleccionado && procesoSeleccionado.id === p.id ? 'active' : ''}`;

        const infoDiv = document.createElement('div');
        infoDiv.className = 'process-info';
        infoDiv.style.flex = '1';

        if (!mostrandoArchivados) {
            infoDiv.onclick = () => seleccionarProceso(p.id);
        }

        infoDiv.innerHTML = `
            <h4>${p.nombre}</h4>
            <span>${p.operaciones.length} actividades registradas</span>
        `;

        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.gap = '2px';

        if (!mostrandoArchivados) {
            const cloneBtn = document.createElement('button');
            cloneBtn.className = 'btn-icon clone';
            cloneBtn.title = 'Clonar / Duplicar Receta Maestra';
            cloneBtn.innerHTML = '📑';
            cloneBtn.dataset.permiso = 'editar_receta';
            cloneBtn.onclick = (e) => {
                e.stopPropagation();
                abrirModalClonarProceso(p.id, p.nombre);
            };
            actionsDiv.appendChild(cloneBtn);

            const archiveBtn = document.createElement('button');
            archiveBtn.className = 'btn-icon archive';
            archiveBtn.title = 'Archivar / Retirar Plantilla Maestra';
            archiveBtn.innerHTML = '📦';
            archiveBtn.dataset.permiso = 'archivar_receta';
            archiveBtn.onclick = (e) => {
                e.stopPropagation();
                archivarProcesoAPI(p.id, p.nombre);
            };
            actionsDiv.appendChild(archiveBtn);
        } else {
            const restoreBtn = document.createElement('button');
            restoreBtn.className = 'btn-icon restore';
            restoreBtn.title = 'Restaurar Plantilla Maestra a Activa';
            restoreBtn.innerHTML = '🔄';
            restoreBtn.dataset.permiso = 'archivar_receta';
            restoreBtn.onclick = (e) => {
                e.stopPropagation();
                desarchivarProcesoAPI(p.id, p.nombre);
            };
            actionsDiv.appendChild(restoreBtn);
        }

        card.appendChild(infoDiv);
        card.appendChild(actionsDiv);
        container.appendChild(card);
    });
}

async function seleccionarProceso(id) {
    procesoSeleccionado = procesosGlobales.find(p => p.id === id);
    renderizarListaProcesos();
    if (!procesoSeleccionado) return;

    document.getElementById('nombreProcesoSelec').innerText = procesoSeleccionado.nombre;
    document.getElementById('editorTareas').style.display = 'flex';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('btnEditarNombreProc').style.display = 'inline-block';

    actualizarSelectPredecesoras(procesoSeleccionado);
    actualizarSelectEtapas(procesoSeleccionado);

    try {
        const resCpm = await fetch(`/api/procesos-maestros/${id}/cpm-analisis/`);
        if (resCpm.ok) {
            const cpmData = await resCpm.json();
            ultimoDataCPM = cpmData; 
            renderizarCPMConHolguras(cpmData);
        } else {
            ultimoDataCPM = null;
            renderizarCPMConHolguras({ tiempo_total_proceso: 0, operaciones_cpm: [] });
        }
    } catch (e) {
        console.error("Error obteniendo análisis CPM:", e);
        ultimoDataCPM = null;
        renderizarCPMConHolguras({ tiempo_total_proceso: 0, operaciones_cpm: [] });
    }
}

let filaArrastrada = null;

function handleDragStart(e) {
    // Reordenar cambia la receta: solo para quien puede editarla
    if (!tienePermiso('editar_receta')) { e.preventDefault(); return; }
    filaArrastrada = this;
    e.dataTransfer.effectAllowed = 'move';
    this.classList.add('dragging');
    gsap.to(this, { opacity: 0.5, scale: 0.98, duration: 0.2 });
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const targetRow = e.target.closest('tr.fila-operacion');
    if (targetRow && targetRow !== filaArrastrada) {
        const rect = targetRow.getBoundingClientRect();
        const middle = rect.top + rect.height / 2;
        if (e.clientY < middle) {
            targetRow.parentNode.insertBefore(filaArrastrada, targetRow);
        } else {
            targetRow.parentNode.insertBefore(filaArrastrada, targetRow.nextSibling);
        }
    }
}

function handleDrop(e) {
    e.stopPropagation();
    if (filaArrastrada) {
        sincronizarNuevoOrdenServidor();
    }
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    gsap.to(this, { opacity: 1, scale: 1, duration: 0.2 });
    filaArrastrada = null;
}

async function sincronizarNuevoOrdenServidor() {
    const filas = document.querySelectorAll('#tablaCPMBody tr.fila-operacion');
    let idsOrdenados = [];
    filas.forEach(f => {
        if(f.dataset.opId) {
            idsOrdenados.push(parseInt(f.dataset.opId, 10));
        }
    });

    if(idsOrdenados.length === 0) return;

    try {
        const res = await fetch('/api/operaciones-proceso/bulk-reorder/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ operaciones_ordenadas: idsOrdenados })
        });

        if (res.ok) {
            await cargarCatalogosGlobales(); 
        } else {
            const data = await res.json();
            alert("Error al sincronizar el reordenamiento: " + (data.error || JSON.stringify(data)));
            cargarCatalogosGlobales(); 
        }
    } catch (err) {
        alert("Error de red al intentar reordenar las actividades.");
        cargarCatalogosGlobales();
    }
}

function renderizarCPMConHolguras(cpmData) {
    let tiempoTotal = cpmData.tiempo_total_proceso || 0;
    let tareas = cpmData.operaciones_cpm || [];

    let totalInc = 0;
    let totalCriticas = 0;
    let totalHorasHombre = 0;

    tareas.forEach(t => {
        let opOrig = procesoSeleccionado.operaciones.find(op => op.id === t.id) || {};

        if (t.tipo_operacion === 'INCUBACION') {
            totalInc += t.duracion_horas;
            if (opOrig.frecuencia_muestreo_horas > 0) {
                let cantidadMuestreos = Math.floor(t.duracion_horas / opOrig.frecuencia_muestreo_horas);
                totalHorasHombre += (cantidadMuestreos * (opOrig.duracion_muestreo_horas || 0) * (opOrig.ops_muestreo || 0));
            }
        } else {
            let sumaOpsFase = 0;
            if (opOrig.requerimientos_rol_detalles && opOrig.requerimientos_rol_detalles.length > 0) {
                opOrig.requerimientos_rol_detalles.forEach(req => sumaOpsFase += req.cantidad);
            } else {
                sumaOpsFase = t.personal_requerido || 1;
            }
            totalHorasHombre += (t.duracion_horas * sumaOpsFase);
        }
        if (t.es_critica) totalCriticas += 1;
    });

    document.getElementById('totalTiempo').innerText = `${tiempoTotal}h`;
    document.getElementById('totalIncubacion').innerText = `${totalInc}h`;
    document.getElementById('totalHorasHombre').innerText = `${totalHorasHombre.toFixed(1)}h`;
    document.getElementById('totalCriticas').innerText = `${totalCriticas} /${tareas.length}`;

    const tbody = document.getElementById('tablaCPMBody');
    tbody.innerHTML = '';

    let etapas = procesoSeleccionado.etapas || [];
    etapas.sort((a, b) => a.orden - b.orden);

    let agrupador = { 'orphan': [] };
    etapas.forEach(e => agrupador[e.id] = []);

    tareas.forEach((t, globalIndex) => {
        let opOrig = procesoSeleccionado.operaciones.find(op => op.id === t.id) || {};
        let etapaId = opOrig.etapa || 'orphan';

        if (!agrupador[etapaId]) agrupador[etapaId] = [];

        agrupador[etapaId].push({
            t: t,
            opOrig: opOrig,
            globalIndex: globalIndex + 1
        });
    });

    const pintarFilasActividad = (listaActividades) => {
        listaActividades.forEach(item => {
            let t = item.t;
            let opOriginal = item.opOrig;
            let frecMuestreo = opOriginal.frecuencia_muestreo_horas || 0;
            let durMuestreo = opOriginal.duracion_muestreo_horas || 0;
            let opsMuestreo = opOriginal.ops_muestreo || 0;

            const tr = document.createElement('tr');

            tr.className = 'fila-operacion';
            tr.setAttribute('draggable', 'true');
            tr.dataset.opId = t.id;

            tr.addEventListener('dragstart', handleDragStart);
            tr.addEventListener('dragover', handleDragOver);
            tr.addEventListener('drop', handleDrop);
            tr.addEventListener('dragend', handleDragEnd);

            if (t.tipo_operacion === 'INCUBACION') tr.className += ' incubation-row';
            if (t.es_critica) tr.style.backgroundColor = 'rgba(244, 63, 94, 0.05)';

            const leftPct = (Math.max(0, t.es) / (tiempoTotal || 1)) * 100;
            const widthPct = (t.duracion_horas / (tiempoTotal || 1)) * 100;

            let holguraBadge = t.es_critica 
                ? `<span class="tag-resource" style="border-color:var(--critical); color:var(--critical);">🚨 Crítica (0h)</span>` 
                : `<span class="tag-resource" style="border-color:var(--success); color:var(--success);">✅ Holgura: ${t.holgura}h</span>`;

            let subTxtFrecuencia = (t.tipo_operacion === 'INCUBACION' && frecMuestreo > 0) 
                ? `<br><span style="font-size:0.65rem; color:var(--incubation);">Muestreos: c/${frecMuestreo}h (${durMuestreo}h,${opsMuestreo}Op)</span>` 
                : '';

            let badgesRolesHtml = '';
            if (opOriginal.requerimientos_rol_detalles && opOriginal.requerimientos_rol_detalles.length > 0) {
                opOriginal.requerimientos_rol_detalles.forEach(req => {
                    badgesRolesHtml += `<span class="tag-resource" style="color:var(--accent);">👤 ${req.cantidad}x${req.rol_nombre}</span> `;
                });
            } else {
                badgesRolesHtml = `<span class="tag-resource">👥 Ops: ${t.personal_requerido}</span>`;
            }

            const chipsMateriales = (opOriginal.materiales || []).map(m => {
                const sufijo = m.aplica_a === 'MUESTREO' ? ' /muestreo' : '';
                const titulo = `${m.material_nombre}${m.anticipacion_horas ? ` · ${m.anticipacion_horas} h antes` : ''}`;
                return `<span class="chip-material" title="${escaparHtml(titulo)}">🧪 ${formatearCantidad(m.cantidad, m.unidad_medida)} ${escaparHtml(m.material_nombre)}${sufijo}</span>`;
            }).join('');

            const safeName = t.nombre.replace(/'/g, "\\'");

            tr.innerHTML = `
                <td style="cursor: grab;" title="Arrastrar para reordenar">⠿ <strong>#${item.globalIndex}</strong><br><span style="color:var(--accent);">${t.identificador_paso}</span></td>
                <td><strong>${t.nombre}</strong></td>
                <td>⏱️ ${t.duracion_horas}h${subTxtFrecuencia}</td>
                <td><span style="font-size:0.65rem; color:var(--text-muted);">ES:${t.es}h | LS:${t.ls}h</span><br>${holguraBadge}</td>
                <td>
                    ${badgesRolesHtml}
                    <span class="tag-resource">🏗️ ${t.tipo_equipo_requerido}</span>
                    ${chipsMateriales ? `<div>${chipsMateriales}</div>` : ''}
                </td>
                <td>${t.es}h ➔ ${t.ef}h</td>
                <td>
                    <span class="badge-cpm ${t.tipo_operacion === 'INCUBACION' ? 'badge-incubation' : 'badge-active'}">
                        ${t.tipo_operacion === 'INCUBACION' ? '🧫 PASIVA' : '⚙️ ACTIVA'}
                    </span>
                </td>
                <td class="gantt-preview-cell">
                    <div class="gantt-track">
                        <div class="gantt-bar ${t.es_critica ? 'critical' : 'regular'}" 
                             style="left: ${leftPct}%; width: ${widthPct}\%;${t.es_critica ? 'background-color: var(--critical);' : ''}"></div>
                    </div>
                </td>
                <td style="text-align: center; white-space: nowrap;">
                    <button class="btn-icon validate" title="Auditoría GxP de Personal" onclick="abrirModalValidacion(${t.id}, '${safeName}')">🔍</button>
                    <button class="btn-icon edit" data-permiso="editar_receta" title="Editar Operación" onclick="abrirModalEditarOperacion(${t.id})">✏️</button>
                    <button class="btn-icon delete" data-permiso="editar_receta" title="Eliminar Operación" onclick="eliminarOperacionAPI(${t.id}, '${safeName}')">🗑️</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    };

    if (agrupador['orphan'].length > 0) {
        pintarFilasActividad(agrupador['orphan']);
    }

    etapas.forEach(etapa => {
        const trEtapa = document.createElement('tr');
        trEtapa.className = 'etapa-header-row';
        trEtapa.innerHTML = `<td colspan="9">📁 ETAPA: ${etapa.nombre}</td>`;
        tbody.appendChild(trEtapa);

        if (agrupador[etapa.id].length > 0) {
            pintarFilasActividad(agrupador[etapa.id]);
        } else {
            const trEmpty = document.createElement('tr');
            trEmpty.innerHTML = `<td colspan="9" style="text-align:center; color: var(--text-muted); font-style: italic; padding: 1rem;">No hay actividades registradas en esta etapa. Haga clic en "+ Añadir Actividad".</td>`;
            tbody.appendChild(trEmpty);
        }
    });
}

// --- LÓGICA GANTT PANTALLA COMPLETA CON ZOOM REACTIVO (SOPORTE 6px/h) ---
function abrirGanttPantallaCompleta() {
    if(!procesoSeleccionado || !ultimoDataCPM) return alert("Seleccione un proceso y espere el cálculo CPM.");

    document.getElementById('ganttTituloProceso').innerText = procesoSeleccionado.nombre;
    renderizarGanttAvanzado(ultimoDataCPM);

    const modal = document.getElementById('modalGanttFullScreen');
    modal.style.display = 'flex';
    gsap.fromTo(modal.querySelector('.modal-content'), {scale: 0.94, opacity: 0}, {scale: 1, opacity: 1, duration: 0.25, ease: "power2.out"});
}

function cerrarGanttPantallaCompleta() {
    document.getElementById('modalGanttFullScreen').style.display = 'none';
}

function cambiarNivelZoom(nuevoNivel) {
    if(!ZOOM_CONFIG[nuevoNivel]) return;
    zoomActual = nuevoNivel;

    document.querySelectorAll('.btn-toggle-zoom').forEach(b => b.classList.remove('active'));
    if(nuevoNivel === 'semanas') document.getElementById('btnZoomSemanas').classList.add('active');
    if(nuevoNivel === 'dias') document.getElementById('btnZoomDias').classList.add('active');
    if(nuevoNivel === 'normal') document.getElementById('btnZoomNormal').classList.add('active');
    if(nuevoNivel === 'horas') document.getElementById('btnZoomHoras').classList.add('active');

    document.getElementById('ganttEscalaActualTexto').innerText = ZOOM_CONFIG[nuevoNivel].texto;

    if(ultimoDataCPM) {
        renderizarGanttAvanzado(ultimoDataCPM);
    }
}

function renderizarGanttAvanzado(cpmData) {
    const sidebar = document.getElementById('ganttFSSidebar');
    const timelineHeader = document.getElementById('ganttFSTimelineHeader');
    const timelineBody = document.getElementById('ganttFSTimelineBody');
    const wrapper = document.getElementById('ganttFSTimelineWrapper');

    sidebar.innerHTML = '';
    timelineHeader.innerHTML = '';
    timelineBody.innerHTML = '';

    const cfg = ZOOM_CONFIG[zoomActual];
    const PIXELES_POR_HORA = cfg.pxPorHora;
    const intervalo = cfg.intervaloLabels;

    const tiempoTotal = Math.max(cpmData.tiempo_total_proceso || 1, 24); 
    const anchoTotal = (tiempoTotal + 2) * PIXELES_POR_HORA;

    timelineHeader.style.width = `${anchoTotal}px`;
    timelineBody.style.width = `${anchoTotal}px`;
    timelineBody.style.backgroundImage = `linear-gradient(to right, rgba(255,255,255,0.04) 1px, transparent 1px)`;
    timelineBody.style.backgroundSize = `${PIXELES_POR_HORA}px 100%`;

    // Construir encabezado de marcas de tiempo
    for(let h = 0; h <= tiempoTotal; h++) {
        const esMultiplo = (h % intervalo === 0);
        const esDia = (h > 0 && h % 24 === 0);
        const esSemana = (h > 0 && h % 168 === 0);

        if (esMultiplo || esDia || esSemana) {
            const tick = document.createElement('div');
            let claseMarker = '';
            if (esSemana) claseMarker = 'week-marker';
            else if (esDia) claseMarker = 'day-marker';

            tick.className = `gantt-fs-tick ${claseMarker}`;
            tick.style.left = `${h * PIXELES_POR_HORA}px`;
            tick.style.width = `${intervalo * PIXELES_POR_HORA}px`;

            if (esSemana && zoomActual === 'semanas') {
                const numSemana = h / 168;
                tick.innerHTML = `<strong>Sem ${numSemana}</strong> (${h}h)`;
            } else if (esDia && (zoomActual === 'dias' || zoomActual === 'semanas')) {
                const numDia = h / 24;
                tick.innerHTML = `<strong>D${numDia}</strong> (${h}h)`;
            } else {
                tick.innerText = `${h}h`;
            }
            timelineHeader.appendChild(tick);
        }
    }

    // Agrupación de actividades
    let tareas = cpmData.operaciones_cpm || [];
    let etapas = procesoSeleccionado.etapas || [];
    etapas.sort((a, b) => a.orden - b.orden);

    let agrupador = { 'orphan': [] };
    etapas.forEach(e => agrupador[e.id] = []);

    tareas.forEach((t) => {
        let opOrig = procesoSeleccionado.operaciones.find(op => op.id === t.id) || {};
        let etapaId = opOrig.etapa || 'orphan';
        if (!agrupador[etapaId]) agrupador[etapaId] = [];
        agrupador[etapaId].push({ t: t, opOrig: opOrig });
    });

    const pintarBloqueGantt = (lista, esEtapa = false, nombreEtapa = "") => {
        if (esEtapa) {
            const rowLabel = document.createElement('div');
            rowLabel.className = 'gantt-fs-row-label etapa';
            rowLabel.innerText = `📁 ${nombreEtapa}`;
            sidebar.appendChild(rowLabel);

            const rowTrack = document.createElement('div');
            rowTrack.className = 'gantt-fs-row-track etapa';
            timelineBody.appendChild(rowTrack);
        }

        lista.forEach(item => {
            const t = item.t;

            const rowLabel = document.createElement('div');
            rowLabel.className = 'gantt-fs-row-label';
            rowLabel.innerHTML = `<strong style="color:var(--accent); margin-right:5px;">[${t.identificador_paso}]</strong>${t.nombre}`;
            rowLabel.title = t.nombre;
            sidebar.appendChild(rowLabel);

            const rowTrack = document.createElement('div');
            rowTrack.className = 'gantt-fs-row-track';

            const bar = document.createElement('div');
            bar.className = `gantt-fs-bar ${t.es_critica ? 'critical' : (t.tipo_operacion === 'INCUBACION' ? 'incubation' : 'regular')}`;
            bar.style.left = `${t.es * PIXELES_POR_HORA}px`;
            bar.style.width = `${Math.max(t.duracion_horas * PIXELES_POR_HORA, 4)}px`; // Mínimo 4px para escala semanal

            // Ajustar texto dentro de la barra según el ancho resultante
            if (t.duracion_horas * PIXELES_POR_HORA > 50) {
                bar.innerText = `${t.identificador_paso} (${t.duracion_horas}h)`;
            } else if (t.duracion_horas * PIXELES_POR_HORA > 22) {
                bar.innerText = `${t.duracion_horas}h`;
            } else {
                bar.innerText = ``;
            }

            bar.title = `[${t.identificador_paso}] ${t.nombre}\nTipo: ${t.tipo_operacion}\nInicio (ES): ${t.es}h | Fin (EF): ${t.ef}h\nDuración: ${t.duracion_horas}h | Holgura: ${t.holgura}h`;

            rowTrack.appendChild(bar);
            timelineBody.appendChild(rowTrack);
        });
    };

    if (agrupador['orphan'].length > 0) pintarBloqueGantt(agrupador['orphan']);
    etapas.forEach(etapa => {
        pintarBloqueGantt(agrupador[etapa.id], true, etapa.nombre);
    });

    wrapper.onscroll = () => {
        sidebar.querySelector('.gantt-fs-sidebar-body').scrollTop = wrapper.scrollTop;
    };
}

function actualizarSelectPredecesoras(proc) {
    const selects = [document.getElementById('selectPredecesora'), document.getElementById('editOpPredecesora')];
    selects.forEach(select => {
        if(!select) return;
        select.innerHTML = '<option value="">-- Ninguna --</option>';
        proc.operaciones.forEach(op => {
            select.innerHTML += `<option value="${op.id}">${op.identificador_paso}: ${op.nombre}</option>`;
        });
    });
}

function abrirModalNuevoProceso() {
    document.getElementById('nuevoProcesoNombre').value = '';
    document.getElementById('modalNuevoProceso').style.display = 'flex';
}

function cerrarModalNuevoProceso() {
    document.getElementById('modalNuevoProceso').style.display = 'none';
}

function abrirModalEditarProceso() {
    if (!procesoSeleccionado) return;
    document.getElementById('editProcesoNombreInput').value = procesoSeleccionado.nombre;
    document.getElementById('modalEditarProceso').style.display = 'flex';
}

function cerrarModalEditarProceso() {
    document.getElementById('modalEditarProceso').style.display = 'none';
}

async function guardarNuevoNombreProcesoAPI() {
    if (!procesoSeleccionado) return;
    const nuevoNombre = document.getElementById('editProcesoNombreInput').value.trim();

    if (!nuevoNombre) {
        alert("El nombre del proceso no puede estar vacío.");
        return;
    }

    try {
        const res = await fetch(`/api/procesos-maestros/${procesoSeleccionado.id}/`, {
            method: 'PATCH',
            headers: { 
                'Content-Type': 'application/json', 
                'X-CSRFToken': getCookie('csrftoken') 
            },
            body: JSON.stringify({ nombre: nuevoNombre })
        });

        if (res.ok) {
            const actualizado = await res.json();
            cerrarModalEditarProceso();
            procesoSeleccionado.nombre = actualizado.nombre;
            document.getElementById('nombreProcesoSelec').innerText = actualizado.nombre;
            await cargarCatalogosGlobales();
        } else {
            const data = await res.json();
            alert("Error al actualizar el nombre:\n\n" + (data.error || JSON.stringify(data)));
        }
    } catch (err) {
        alert("Error de red al intentar actualizar el nombre.");
    }
}

async function crearProcesoMaestroAPI() {
    const nombre = document.getElementById('nuevoProcesoNombre').value.trim();
    if (!nombre) return alert("Ingresa un nombre.");

    const res = await fetch('/api/procesos-maestros/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ nombre, descripcion: "Generado desde interfaz web", activo: true })
    });

    if (res.ok) {
        cerrarModalNuevoProceso();
        cargarCatalogosGlobales();
    } else {
        alert("Error al crear proceso maestro.");
    }
}

async function archivarProcesoAPI(id, nombre) {
    if (!confirm(`📦 ¿Estás seguro de archivar la plantilla "${nombre}"?\n\nSe conservará para mantener la integridad de los lotes históricos, pero desaparecerá de esta lista y no se podrán crear nuevos lotes con ella.`)) return;

    try {
        const res = await fetch(`/api/procesos-maestros/${id}/archivar/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });

        if (res.ok) {
            cargarCatalogosGlobales();
        } else {
            const data = await res.json();
            alert("Error al archivar la plantilla: " + (data.error || JSON.stringify(data)));
        }
    } catch (err) { alert("Error de red."); }
}

async function desarchivarProcesoAPI(id, nombre) {
    if (!confirm(`🔄 ¿Deseas restaurar la plantilla "${nombre}" a estado activo?`)) return;

    try {
        const res = await fetch(`/api/procesos-maestros/${id}/desarchivar/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });

        if (res.ok) {
            cargarCatalogosGlobales();
        } else {
            const data = await res.json();
            alert("Error al restaurar la plantilla: " + (data.error || JSON.stringify(data)));
        }
    } catch (err) { alert("Error de red."); }
}

function abrirModalClonarProceso(id, nombre_actual) {
    document.getElementById('clonarProcId').value = id;
    document.getElementById('clonarProcNombreNuevo').value = nombre_actual + ' (Copia)';
    document.getElementById('modalClonarProceso').style.display = 'flex';
}

function cerrarModalClonarProceso() {
    document.getElementById('modalClonarProceso').style.display = 'none';
}

async function ejecutarClonarProcesoAPI() {
    const id = document.getElementById('clonarProcId').value;
    const nuevoNombre = document.getElementById('clonarProcNombreNuevo').value.trim();

    if (!nuevoNombre) {
        alert("Debe ingresar un nombre válido para la nueva plantilla.");
        return;
    }

    try {
        const res = await fetch(`/api/procesos-maestros/${id}/clonar/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ nuevo_nombre: nuevoNombre })
        });

        if (res.ok) {
            const data = await res.json();
            cerrarModalClonarProceso();
            procesoSeleccionado = { id: data.nuevo_id };
            await cargarCatalogosGlobales();
        } else {
            const data = await res.json();
            alert("Error al clonar la plantilla:\n\n" + (data.error || JSON.stringify(data)));
        }
    } catch (err) { alert("Error de red."); }
}

async function crearOperacionAPI() {
    if (!procesoSeleccionado) return;
    const etapa = document.getElementById('selectEtapaTarea').value || null; 
    const identificador_paso = document.getElementById('inputPasoId').value.trim();
    const nombre = document.getElementById('inputTareaNombre').value.trim();
    const tipo_operacion = document.getElementById('selectTipoTarea').value;
    const duracion_horas = parseFloat(document.getElementById('inputTareaDuracion').value);

    if (identificador_paso) {
        const existePaso = procesoSeleccionado.operaciones.find(op => op.identificador_paso.toLowerCase() === identificador_paso.toLowerCase());
        if (existePaso) {
            alert(`⚠️ Validación GxP (Fail-Fast):\nEl ID de Paso "${identificador_paso}" ya existe en esta receta. Por favor, utiliza un identificador único para mantener la trazabilidad.`);
            return;
        }
    }

    const frecuencia_muestreo_horas = parseInt(document.getElementById('inputFrecMuestreo').value) || 0;
    const duracion_muestreo_horas = parseFloat(document.getElementById('inputDuracionMuestreo').value) || 0.0;
    const ops_muestreo = parseInt(document.getElementById('inputOpsMuestreo').value) || 0;

    const predecesora = document.getElementById('selectPredecesora').value || null;
    const tipo_dependencia = document.getElementById('selectTipoDep').value;
    const desfase_horas = parseFloat(document.getElementById('inputDesfase').value) || 0;
    const tipo_equipo_requerido = document.getElementById('selectTipoEquipoReq').value;

    const requerimientos_rol = obtenerRolesDesdeBuilder('crear');

    if (!identificador_paso || !nombre || isNaN(duracion_horas)) return alert("Completa los campos obligatorios.");
    const materiales = obtenerMaterialesDesdeBuilder('crear');
    if (!materiales) return;

    const res = await fetch('/api/operaciones-proceso/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({
            proceso: procesoSeleccionado.id,
            etapa: etapa, 
            identificador_paso,
            nombre,
            tipo_operacion,
            duracion_horas,
            frecuencia_muestreo_horas,
            duracion_muestreo_horas,
            ops_muestreo,
            predecesora,
            tipo_dependencia,
            desfase_horas,
            personal_requerido: requerimientos_rol.reduce((acc, r) => acc + r.cantidad, 0) || 1,
            tipo_equipo_requerido,
            materiales,
            requerimientos_rol
        })
    });

    if (res.ok) {
        cerrarModalNuevaOperacion();
        cargarCatalogosGlobales();
    } else {
        const data = await res.json();
        let msg = "Error al registrar la operación.";
        if (data.non_field_errors) msg = data.non_field_errors.join("\n");
        else if (data.identificador_paso) msg = "ID de Paso: " + data.identificador_paso.join("\n");
        else msg = JSON.stringify(data);

        alert(`⚠️ Solicitud rechazada por el servidor:\n${msg}`);
    }
}

function abrirModalEditarOperacion(id) {
    const op = procesoSeleccionado.operaciones.find(o => o.id === id);
    if (!op) return;

    document.getElementById('editOpId').value = op.id;
    document.getElementById('editOpEtapa').value = op.etapa || ''; 
    document.getElementById('editOpPasoId').value = op.identificador_paso;
    document.getElementById('editOpNombre').value = op.nombre;
    document.getElementById('editOpTipo').value = op.tipo_operacion;
    document.getElementById('editOpDuracion').value = op.duracion_horas;

    document.getElementById('editOpFrecMuestreo').value = op.frecuencia_muestreo_horas || 0;
    document.getElementById('editOpDuracionMuestreo').value = op.duracion_muestreo_horas || 0;
    document.getElementById('editOpOpsMuestreo').value = op.ops_muestreo || 0;

    document.getElementById('editOpTipoDep').value = op.tipo_dependencia || 'FS';
    document.getElementById('editOpDesfase').value = op.desfase_horas || 0;
    document.getElementById('editOpEquipo').value = op.tipo_equipo_requerido || 'N/A';

    const predSelect = document.getElementById('editOpPredecesora');
    Array.from(predSelect.options).forEach(opt => {
        if (opt.value == op.id) {
            opt.style.display = 'none'; 
        } else {
            opt.style.display = 'block';
        }
    });
    predSelect.value = op.predecesora || '';

    const container = document.getElementById('rolesBuilderEditar');
    container.innerHTML = '';
    if (op.requerimientos_rol_detalles && op.requerimientos_rol_detalles.length > 0) {
        op.requerimientos_rol_detalles.forEach(req => {
            agregarFilaRolBuilder('editar', req.rol, req.cantidad);
        });
    } else {
        agregarFilaRolBuilder('editar');
    }

    materialesBuilder.editar = (op.materiales || []).map(m => ({
        material: m.material, cantidad: Number(m.cantidad), anticipacion_horas: m.anticipacion_horas, aplica_a: m.aplica_a,
    }));

    toggleIncubacionFields(true);
    document.getElementById('modalEditarOperacion').style.display = 'flex';
}

function cerrarModalEditarOperacion() {
    document.getElementById('modalEditarOperacion').style.display = 'none';
}

async function guardarEdicionOperacionAPI() {
    const id = document.getElementById('editOpId').value;
    const identificador_paso = document.getElementById('editOpPasoId').value.trim();

    if (identificador_paso) {
        const existePaso = procesoSeleccionado.operaciones.find(op => op.identificador_paso.toLowerCase() === identificador_paso.toLowerCase() && op.id != id);
        if (existePaso) {
            alert(`⚠️ Validación GxP (Fail-Fast):\nEl ID de Paso "${identificador_paso}" ya está siendo utilizado por otra actividad en esta receta. Por favor, utiliza un identificador único.`);
            return;
        }
    }

    const etapa = document.getElementById('editOpEtapa').value || null; 
    const nombre = document.getElementById('editOpNombre').value.trim();
    const tipo_operacion = document.getElementById('editOpTipo').value;
    const duracion_horas = parseFloat(document.getElementById('editOpDuracion').value);

    const frecuencia_muestreo_horas = parseInt(document.getElementById('editOpFrecMuestreo').value) || 0;
    const duracion_muestreo_horas = parseFloat(document.getElementById('editOpDuracionMuestreo').value) || 0.0;
    const ops_muestreo = parseInt(document.getElementById('editOpOpsMuestreo').value) || 0;

    const tipo_dependencia = document.getElementById('editOpTipoDep').value;
    const desfase_horas = parseFloat(document.getElementById('editOpDesfase').value) || 0;
    const predecesora = document.getElementById('editOpPredecesora').value || null;
    const tipo_equipo_requerido = document.getElementById('editOpEquipo').value;
    const requerimientos_rol = obtenerRolesDesdeBuilder('editar');

    if (!identificador_paso || !nombre || isNaN(duracion_horas)) return alert("Completa los campos obligatorios.");
    const materiales = obtenerMaterialesDesdeBuilder('editar');
    if (!materiales) return;

    const res = await fetch(`/api/operaciones-proceso/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({
            etapa: etapa, 
            identificador_paso,
            nombre,
            tipo_operacion,
            duracion_horas,
            frecuencia_muestreo_horas,
            duracion_muestreo_horas,
            ops_muestreo,
            predecesora, 
            tipo_dependencia,
            desfase_horas,
            tipo_equipo_requerido,
            personal_requerido: requerimientos_rol.reduce((acc, r) => acc + r.cantidad, 0) || 1,
            requerimientos_rol,
            materiales
        })
    });

    if (res.ok) {
        cerrarModalEditarOperacion();
        cargarCatalogosGlobales();
    } else {
        const data = await res.json();
        let msg = "Error al actualizar la operación.";
        if (data.non_field_errors) msg = data.non_field_errors.join("\n");
        else if (data.identificador_paso) msg = "ID de Paso: " + data.identificador_paso.join("\n");
        else msg = JSON.stringify(data);

        alert(`⚠️ Solicitud rechazada por el servidor:\n${msg}`);
    }
}

async function eliminarOperacionAPI(id, nombre) {
    if (!confirm(`¿Estás seguro de eliminar la operación "${nombre}"?`)) return;

    try {
        const res = await fetch(`/api/operaciones-proceso/${id}/`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });

        if (res.ok || res.status === 204) {
            cargarCatalogosGlobales();
        } else {
            const data = await res.json();
            alert("⚠️ Acción Restringida:\n\n" + (data.error || "Error interno del servidor."));
        }
    } catch(err) {
        alert("Error de red al intentar comunicarse con el servidor.");
    }
}

function abrirModalValidacion(id, nombre) {
    document.getElementById('valOpId').value = id;
    document.getElementById('valOpNombre').innerText = nombre;

    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    document.getElementById('valFecha').value = `${yyyy}-${mm}-${dd}`;

    document.getElementById('validationResults').style.display = 'none';
    document.getElementById('modalValidacionGxp').style.display = 'flex';
}

function cerrarModalValidacion() {
    document.getElementById('modalValidacionGxp').style.display = 'none';
    document.getElementById('validationResults').innerHTML = '';
}

async function ejecutarValidacionGxpAPI() {
    const opId = document.getElementById('valOpId').value;
    const fecha = document.getElementById('valFecha').value;
    const btn = document.getElementById('btnEjecutarValidacion');
    const resContainer = document.getElementById('validationResults');

    if (!fecha) {
        alert("Seleccione una fecha proyectada para la evaluación.");
        return;
    }

    btn.disabled = true;
    btn.innerText = "Calculando...";

    try {
        const response = await fetch(`/api/operaciones-proceso/${opId}/validar-disponibilidad/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ fecha: fecha })
        });

        const data = await response.json();

        if (!response.ok) throw new Error(data.error || "Error al validar competencias en el servidor.");

        resContainer.style.display = 'block';

        if (!data.detalles || data.detalles.length === 0) {
            resContainer.innerHTML = `<div style="text-align:center; padding: 1rem; color: var(--success); font-weight:bold;">${data.mensaje || 'Fase sin requerimientos específicos de roles. 100% Cubierto.'}</div>`;
            return;
        }

        let globalBadge = data.cumple_requerimientos_global 
            ? `<span class="status-badge status-ok">✅ COBERTURA GxP COMPLETADA</span>`
            : `<span class="status-badge status-fail">🚨 ALERTA: BRECHA DE PERSONAL DETECTADA</span>`;

        let html = `
            <div style="margin-bottom: 1rem; text-align: center;">${globalBadge}</div>
            <div style="font-size: 0.72rem; color: var(--text-muted); display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; border-bottom: 1px solid var(--border-color); padding-bottom: 0.3rem; margin-bottom: 0.3rem;">
                <strong>Rol/Competencia</strong>
                <strong style="text-align:center;">Requerido</strong>
                <strong style="text-align:center;">Disponible</strong>
                <strong style="text-align:center;">Estado GxP</strong>
            </div>
        `;

        data.detalles.forEach(det => {
            let estadoHtml = det.cumplido 
                ? `<span class="status-badge status-ok" style="font-size: 0.6rem;">OK</span>`
                : `<span class="status-badge status-fail" style="font-size: 0.6rem;">Faltan ${det.brecha}</span>`;

            html += `
                <div class="validation-row">
                    <span style="font-weight: 500;">${det.rol_nombre}</span>
                    <span style="text-align:center;">${det.cantidad_demandada}</span>
                    <span style="text-align:center; font-weight:bold; color: ${det.cumplido ? 'var(--success)' : 'var(--danger)'};">${det.cantidad_disponible}</span>
                    <span style="text-align:center;">${estadoHtml}</span>
                </div>
            `;
        });

        resContainer.innerHTML = html;

    } catch (error) {
        alert(error.message);
    } finally {
        btn.disabled = false;
        btn.innerText = "Ejecutar Simulación";
    }
}


cargarCatalogosGlobales();
