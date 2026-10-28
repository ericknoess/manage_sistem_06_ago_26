// procesos/static/procesos/js/ejecucion.js

let lotesGlobales = [];
let procesosMaestrosGlobales = [];
let loteSeleccionado = null;
let fasesLoteActual = [];  // tareas del lote abierto (se piden con ?lote=)


// Minutos de desviación en texto corto: 45m, 3h 20m, 14d 17h
function formatearDesviacion(minutos) {
    if (minutos < 60) return `${minutos}m`;
    const horas = Math.floor(minutos / 60);
    if (horas < 24) return `${horas}h ${minutos % 60}m`;
    return `${Math.floor(horas / 24)}d ${horas % 24}h`;
}

async function cargarCatalogos() {
    try {
        const [resLotes, resProcesos] = await Promise.all([
            fetch('/api/lotes/'),
            fetch('/api/procesos-maestros/')
        ]);

        lotesGlobales = await resLotes.json();
        procesosMaestrosGlobales = await resProcesos.json();

        renderizarLotes();
        llenarSelectProcesos();

        if(loteSeleccionado) {
            const actualizado = lotesGlobales.find(l => l.id === loteSeleccionado.id);
            if(actualizado) seleccionarLote(actualizado.id);
        }
    } catch (err) {
        console.error("Error al cargar datos del servidor:", err);
    }
}

function renderizarLotes() {
    const container = document.getElementById('listaLotes');
    container.innerHTML = '';

    if (lotesGlobales.length === 0) {
        container.innerHTML = `<div class="empty-state">No hay lotes activos. Haz clic en 'Instanciar Lote'.</div>`;
        return;
    }

    lotesGlobales.forEach(lote => {
        const card = document.createElement('div');
        card.className = `lote-item ${loteSeleccionado && loteSeleccionado.id === lote.id ? 'active' : ''}`;

        let badgeClass = lote.estado === 'PLANEADO' ? 'status-planeado' : (lote.estado === 'COMPLETADO' ? 'status-completado' : 'status-progreso');
        let progress = lote.progreso_porcentual !== undefined ? lote.progreso_porcentual : 0;

        let actionButtonHtml = '';
        if (lote.estado === 'PLANEADO') {
            actionButtonHtml = `<button class="btn-icon" data-permiso="abortar_lote" style="color: var(--danger);" title="Eliminar Lote Planificado" onclick="eliminarLoteAPI(${lote.id}, event)">🗑️</button>`;
        } else if (lote.estado === 'EN_PROGRESO' || lote.estado === 'DESVIACION') {
            actionButtonHtml = `<button class="btn-icon" data-permiso="abortar_lote" style="color: var(--warning);" title="Abortar Lote" onclick="abrirModalAbortar(${lote.id}, event)">🛑</button>`;
        } else if (lote.estado === 'COMPLETADO') {
            actionButtonHtml = `<button class="btn-icon" data-permiso="abortar_lote" style="color: var(--success);" title="Archivar Lote" onclick="archivarLoteAPI(${lote.id}, event)">📦</button>`;
        }

        card.innerHTML = `
            <div style="flex: 1;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <h4 style="margin: 0; font-size: 0.85rem; color: var(--text);">${lote.identificador_lote}</h4>
                    <div style="display: flex; align-items: center; gap: 0.25rem;">
                        <span class="badge-status ${badgeClass}">${lote.estado}</span>
                        ${actionButtonHtml}
                    </div>
                </div>
                <span style="font-size: 0.7rem; color: var(--text-muted);">${lote.proceso_nombre}</span>
                <div class="progress-container">
                    <div class="progress-fill" style="width: ${progress}%;"></div>
                </div>
            </div>
        `;

        card.onclick = () => seleccionarLote(lote.id);
        container.appendChild(card);
    });
}

function seleccionarLote(id) {
    loteSeleccionado = lotesGlobales.find(l => l.id === id);
    renderizarLotes(); 
    renderizarDetalleLote(); 
}

async function renderizarDetalleLote() {
    const container = document.getElementById('editorLote');
    const headerTitle = document.getElementById('tituloLoteActivo');

    if (!loteSeleccionado) {
        container.innerHTML = '<div class="empty-state">👈 Selecciona un lote activo del panel izquierdo para ver sus fases y registrar firmas GxP.</div>';
        headerTitle.innerHTML = '<span>⚡ Monitor de Ejecución: <strong style="color: white;">Selecciona un Lote</strong></span>';
        return;
    }

    let headerBadge = loteSeleccionado.estado === 'PLANEADO' ? 'status-planeado' : (loteSeleccionado.estado === 'COMPLETADO' ? 'status-completado' : 'status-progreso');
    headerTitle.innerHTML = `
        <span>⚡ eBR - Lote: <strong style="color: var(--text);">${loteSeleccionado.identificador_lote}</strong></span>
        <span class="encabezado-lote-acciones">
            <a class="btn-secondary btn-historial" href="/graficas/?proceso=${loteSeleccionado.proceso_maestro}&lotes=${loteSeleccionado.id}"
               title="Parámetros contra la edad, curva esperada e indicadores de este lote">📉 Gráficas</a>
            <button class="btn-secondary btn-historial" title="Informe de datos de proceso en PDF o Excel"
                    onclick="abrirInformeLote({ loteId: ${loteSeleccionado.id}, procesoId: ${loteSeleccionado.proceso_maestro}, identificador: ${JSON.stringify(loteSeleccionado.identificador_lote).replace(/"/g, '&quot;')} })">🧾 Informe</button>
            <button class="btn-secondary btn-historial" onclick="abrirHistorialLote()" title="Quién hizo qué con este lote">📜 Historial</button>
            <a class="btn-secondary btn-historial btn-eventos-lote" id="enlaceEventosLote" href="/eventos/?lote=${loteSeleccionado.id}"
               title="Eventos GMP de este lote">⚠️ Eventos</a>
            ${loteSeleccionado.archivado ? '' : `<button class="btn-secondary btn-historial btn-evento" title="Reportar una falla, desviación u otro evento GMP del lote"
                onclick="abrirReporteEvento({ lote: ${loteSeleccionado.id}, loteNombre: ${JSON.stringify(loteSeleccionado.identificador_lote).replace(/"/g, '&quot;')}, alGuardar: contarEventosLote })">+ Reportar evento</button>`}
            <span class="badge-status ${headerBadge}">${loteSeleccionado.estado}</span>
        </span>
    `;

    let fechaPlaneadaTxt = loteSeleccionado.fecha_inicio_planeada ? new Date(loteSeleccionado.fecha_inicio_planeada).toLocaleString() : '-';
    let progress = loteSeleccionado.progreso_porcentual !== undefined ? loteSeleccionado.progreso_porcentual : 0;
    let isLocked = loteSeleccionado.estado === 'COMPLETADO';

    let bannerLockHtml = isLocked ? `
        <div class="gxp-lock-banner">
            <span style="font-size: 1.2rem;">🔒</span> 
            <div><strong>Data Lock (QA Release):</strong> Este Lote de Producción ha sido cerrado. Sus registros son estrictamente inmutables (21 CFR Part 11).</div>
        </div>
    ` : '';

    let html = `
        <div style="padding: 1rem; border-bottom: 1px solid var(--border-color); background: rgba(0,0,0,0.2); display: flex; gap: 3rem;">
            <div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">Proceso / Receta Maestra</div>
                <div style="font-weight: bold; color: var(--info);">${loteSeleccionado.proceso_nombre}</div>
            </div>
            <div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">Fecha Planeada</div>
                <div style="font-weight: bold;">${fechaPlaneadaTxt}</div>
            </div>
            <div style="flex: 1; max-width: 200px;">
                <div style="font-size: 0.75rem; color: var(--text-muted); display: flex; justify-content: space-between;">
                    <span>Progreso</span>
                    <span style="font-weight: bold; color: var(--success);">${progress}%</span>
                </div>
                <div class="progress-container"><div class="progress-fill" style="width: ${progress}%;"></div></div>
            </div>
        </div>
        ${bannerLockHtml}
        <div style="padding: 1rem;">
            <h4 style="margin-top: 0; margin-bottom: 0.8rem; color: var(--accent);">Fases de Producción (Ruta Crítica Instanciada)</h4>
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">ID</th>
                        <th>Operación / Fase</th>
                        <th>Estado</th>
                        <th>Horario (Forecast vs Real)</th>
                        <th>Desviación (Live)</th>
                        <th>Operadores Asignados</th>
                        <th style="text-align: center; width: 110px;">Acciones</th>
                    </tr>
                </thead>
                <tbody>
    `;

    try {
        // Solo las tareas de este lote (con cientos de lotes, pedir todas sería lentísimo)
        const resFases = await fetch(`/api/fases-lote/?lote=${loteSeleccionado.id}`);
        if (!resFases.ok) throw new Error('No se pudieron cargar las tareas del lote');
        const fasesLote = await resFases.json();
        fasesLoteActual = fasesLote;

        let fasesPorEtapa = {};
        fasesLote.forEach(fase => {
            let etapaNombre = fase.etapa_nombre || 'Actividades Sueltas (Sin Etapa)';
            let etapaOrden = fase.etapa_orden || 999999;
            if (!fasesPorEtapa[etapaNombre]) fasesPorEtapa[etapaNombre] = { orden: etapaOrden, fases: [] };
            fasesPorEtapa[etapaNombre].fases.push(fase);
        });

        let etapasArray = Object.keys(fasesPorEtapa).map(key => ({
            nombre: key, orden: fasesPorEtapa[key].orden, fases: fasesPorEtapa[key].fases
        })).sort((a, b) => a.orden - b.orden);

        etapasArray.forEach(etapa => {
            html += `<tr class="etapa-header-row"><td colspan="7">📁 ETAPA: ${etapa.nombre}</td></tr>`;

            etapa.fases.forEach(fase => {
                let badgeClass = 'status-pendiente';
                if(fase.estado === 'EN_PROGRESO') badgeClass = 'status-progreso';
                if(fase.estado === 'COMPLETADA') badgeClass = 'status-completado';

                // INDICADORES Y BLOQUEOS
                let estaIniciada = ['EN_PROGRESO', 'COMPLETADA'].includes(fase.estado);
                let lockIconUI = estaIniciada ? '<span style="color:var(--warning); font-size:0.7rem;" title="Iniciada en Piso">🔒</span> ' : '';

                const [fcstInicio, fcstFin] = formatearRangoFase(fase.inicio_programado, fase.fin_programado).split(' - ');
                let actInicio = fase.fecha_inicio_real ? new Date(fase.fecha_inicio_real).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', hour12: false}) : '--:--';
                let actFin = fase.fecha_fin_real ? new Date(fase.fecha_fin_real).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', hour12: false}) : '--:--';

                let rendimientoHtml = `<span class="tag-none">Sin Medición</span>`;
                if (fase.inicio_programado) {
                    const dtForecast = new Date(fase.inicio_programado);

                    if (estaIniciada && fase.fecha_inicio_real) {
                        const dtReal = new Date(fase.fecha_inicio_real);
                        const diffMins = Math.round((dtReal - dtForecast) / 60000);
                        if (diffMins < -5) rendimientoHtml = `<span class="tag-warning" title="Inició antes de lo programado">⏩ −${formatearDesviacion(-diffMins)}</span>`;
                        else if (diffMins <= 5) rendimientoHtml = `<span class="tag-ontime">✔ A tiempo</span>`;
                        else if (diffMins <= 30) rendimientoHtml = `<span class="tag-warning">⚠ +${formatearDesviacion(diffMins)}</span>`;
                        else rendimientoHtml = `<span class="tag-delay">🚨 +${formatearDesviacion(diffMins)}</span>`;
                    } else if (fase.estado === 'PENDIENTE') {
                        const now = new Date();
                        const diffMins = Math.round((now - dtForecast) / 60000);
                        if (diffMins > 15) rendimientoHtml = `<span class="tag-delay" title="Retraso proyectado actual">🚨 Proyecta +${formatearDesviacion(diffMins)}</span>`;
                        else rendimientoHtml = `<span class="tag-none">A la espera</span>`;
                    }
                }

                let asignacionesHtml = fase.operadores_asignados.length > 0 
                    ? fase.operadores_asignados.map(a => `<div class="tag-resource">👤 ${a.operador_nombre}</div>`).join('') 
                    : '<span style="color: var(--text-muted); font-size: 0.7rem;">Sin asignar</span>';

                // [NUEVO] IDENTIFICACIÓN DE TAREA PASIVA (MÁQUINA)
                let esPasiva = fase.tipo_operacion === 'INCUBACION' && !fase.es_subtarea_muestreo;
                let rowClass = esPasiva ? 'class="row-incubation"' : '';

                if(esPasiva) {
                    asignacionesHtml = `<span class="tag-machine" title="Tiempo de Máquina continuo. No requiere firma de asignación humana.">🧫 Automatizado</span>`;
                }

                // Datos de proceso: estado de la captura y acceso al formulario
                let capturaHtml = '';
                if (fase.captura) {
                    const c = fase.captura;
                    capturaHtml = c.capturada
                        ? `<span class="chip-captura chip-captura--ok" title="${escaparHtml(c.secciones.join(', '))}">📊 Datos capturados</span>`
                        : `<span class="chip-captura ${c.requerida ? 'chip-captura--pendiente' : ''}" title="${escaparHtml(c.secciones.join(', '))}">📊 ${c.requerida ? 'Datos por capturar' : 'Datos opcionales'}</span>`;
                }
                let btnDatos = fase.captura || fase.admite_muestra_adicional
                    ? `<button class="btn-icon" title="Datos de proceso${fase.admite_muestra_adicional ? ' y muestras adicionales' : ''}" onclick="abrirDatosFase(${fase.id})">📊</button>` : '';

                let idMostrar = fase.operacion_id_paso || fase.operacion_maestra?.identificador_paso || '-';
                let nombreMostrar = fase.operacion_nombre || fase.nombre_tarea_dinamica || fase.operacion_maestra?.nombre || 'Operación';

                // Reportar un evento GMP de esta tarea (cualquiera con sesión)
                const btnEvento = loteSeleccionado.archivado ? '' : `<button class="btn-icon" title="Reportar un evento GMP de esta tarea"
                    onclick="abrirReporteEvento({ fase: ${fase.id}, faseNombre: ${JSON.stringify(`[${idMostrar}] ${nombreMostrar}`).replace(/"/g, '&quot;')}, loteNombre: ${JSON.stringify(loteSeleccionado.identificador_lote).replace(/"/g, '&quot;')}, alGuardar: contarEventosLote })">⚠️</button>`;

                // ACCIONES CON BLOQUEOS
                let accionesHtml = '';
                if (isLocked) {
                    accionesHtml = `${btnDatos}${btnEvento}<span style="font-size: 1rem; opacity: 0.5;" title="Registro Inmutable (Solo Lectura)">🔒</span>`;
                } else {
                    let btnReprogramar = estaIniciada
                        ? `<button class="btn-icon" title="Bloqueo GxP: Tarea iniciada en planta. No se puede reprogramar." disabled>🔒</button>`
                        : `<button class="btn-icon" data-permiso="reprogramar_fase" title="Reprogramar Tarea (Ajustar Forecast)" onclick="abrirModalReprogramar(${fase.id}, '${fase.fecha_programada}', '${fase.hora_inicio_programada}')">⏱️</button>`;

                    // [NUEVO] Bloqueo de Asignación Manual para Tareas Pasivas
                    let btnAsignar = esPasiva 
                        ? `<button class="btn-icon" disabled title="Bloqueo GxP: Fase puramente mecanizada/pasiva.">🚫</button>`
                        : `<button class="btn-icon" data-permiso="asignar_personal" title="Asignar Operador GxP" onclick="abrirModalAsignacion(${fase.id})">👤</button>`;

                    accionesHtml = `
                        ${btnDatos}
                        ${btnEvento}
                        ${btnReprogramar}
                        ${btnAsignar}
                        <button class="btn-icon" data-permiso="ejecutar_fase" title="Forzar Estado (Supervisor)" onclick="cambiarEstadoFase(${fase.id}, '${fase.estado}')">🔄</button>
                    `;
                }

                html += `
                    <tr ${rowClass}>
                        <td style="color: var(--info); font-weight: bold;">${idMostrar}</td>
                        <td style="font-weight: bold;">${lockIconUI}${nombreMostrar}${capturaHtml ? `<div>${capturaHtml}</div>` : ''}</td>
                        <td><span class="badge-status ${badgeClass}">${fase.estado}</span></td>
                        <td style="font-size: 0.75rem;">
                            <div style="color: var(--text-muted); font-size: 0.65rem;">FCST: ${fcstInicio} a ${fcstFin}</div>
                            <div style="color: white; margin-top:2px;">REAL: ${actInicio} a ${actFin}</div>
                        </td>
                        <td>${rendimientoHtml}</td>
                        <td>${asignacionesHtml}${htmlEquiposCompacto(fase, { permiteCambio: fase.estado === 'EN_PROGRESO' && !isLocked })}</td>
                        <td style="text-align: center; white-space: nowrap;">${accionesHtml}</td>
                    </tr>
                `;
            });
        });

        html += `</tbody></table></div>`;
        container.innerHTML = html;
        contarEventosLote();

    } catch (err) {
        container.innerHTML = '<div style="color:var(--danger); text-align:center;">Error cargando fases.</div>';
    }
}

// Botón «Eventos» del lote: muestra cuántos siguen abiertos
async function contarEventosLote() {
    if (!loteSeleccionado) return;
    const loteId = loteSeleccionado.id;
    try {
        const res = await fetch(`/api/eventos/resumen/?lote=${loteId}`);
        const conteo = await res.json();
        const enlace = document.getElementById('enlaceEventosLote');
        if (!enlace || !loteSeleccionado || loteSeleccionado.id !== loteId) return;
        const total = (conteo.ABIERTO || 0) + (conteo.CERRADO || 0) + (conteo.ANULADO || 0);
        enlace.textContent = conteo.ABIERTO ? `⚠️ Eventos · ${conteo.ABIERTO} abierto${conteo.ABIERTO === 1 ? '' : 's'}` : `⚠️ Eventos (${total})`;
        enlace.classList.toggle('btn-eventos-lote--abiertos', !!conteo.ABIERTO);
    } catch (e) { /* sin conteo */ }
}

// --- FUNCIONES ORIGINALES ---
function llenarSelectProcesos() {
    const select = document.getElementById('selectProcesoMaestro');
    select.innerHTML = '<option value="">-- Seleccione una Receta Maestra --</option>';
    procesosMaestrosGlobales.forEach(p => { select.innerHTML += `<option value="${p.id}">${p.nombre} (${p.operaciones.length} fases)</option>`; });
}

function abrirModalInstanciarLote() {
    document.getElementById('nuevoLoteId').value = '';
    document.getElementById('selectProcesoMaestro').value = '';
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    document.getElementById('nuevoLoteFecha').value = now.toISOString().slice(0, 16);
    document.getElementById('modalInstanciarLote').style.display = 'flex';
}

function cerrarModalInstanciarLote() { document.getElementById('modalInstanciarLote').style.display = 'none'; }

async function crearLoteAPI() {
    const idLote = document.getElementById('nuevoLoteId').value.trim();
    const idProceso = document.getElementById('selectProcesoMaestro').value;
    const fechaPlaneada = document.getElementById('nuevoLoteFecha').value;

    if (!idLote || !idProceso || !fechaPlaneada) return alert("Complete los campos obligatorios.");

    try {
        const res = await fetch('/api/lotes/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ identificador_lote: idLote, proceso_maestro: parseInt(idProceso), estado: 'PLANEADO', fecha_inicio_planeada: new Date(fechaPlaneada).toISOString() })
        });

        if (res.ok) { cerrarModalInstanciarLote(); await cargarCatalogos(); } 
        else { const data = await res.json(); alert("Error al instanciar: " + JSON.stringify(data)); }
    } catch (err) { alert("Error de red."); }
}

function codigoLote(loteId) {
    const lote = lotesGlobales.find(l => l.id === loteId);
    return lote ? `Lote ${lote.identificador_lote}` : '';
}

// Las acciones críticas piden firma electrónica (static/core/js/firma.js)
async function eliminarLoteAPI(loteId, event) {
    event.stopPropagation();
    const r = await ejecutarConFirma({
        accion: 'ELIMINAR_LOTE', titulo: '🗑️ Eliminar lote planeado', detalle: codigoLote(loteId),
        url: `/api/lotes/${loteId}/`, metodo: 'DELETE',
    });
    if (!r) return;
    if (r.ok) { limpiarSeleccionSiCorresponde(loteId); await cargarCatalogos(); }
    else alert(r.data.error || r.data.detail || 'No se pudo eliminar el lote.');
}

async function archivarLoteAPI(loteId, event) {
    event.stopPropagation();
    const r = await ejecutarConFirma({
        accion: 'ARCHIVAR_LOTE', titulo: '📦 Archivar lote completado', detalle: codigoLote(loteId),
        url: `/api/lotes/${loteId}/archivar/`,
    });
    if (!r) return;
    if (r.ok) { limpiarSeleccionSiCorresponde(loteId); await cargarCatalogos(); }
    else alert(r.data.error || r.data.detail || 'No se pudo archivar el lote.');
}

function abrirModalAbortar(loteId, event) {
    event.stopPropagation();
    document.getElementById('abortarLoteId').value = loteId;
    document.getElementById('textareaMotivoAborto').value = '';
    document.getElementById('modalAbortarLote').style.display = 'flex';
}

async function ejecutarAbortarAPI() {
    const loteId = document.getElementById('abortarLoteId').value;
    const motivo = document.getElementById('textareaMotivoAborto').value.trim();
    if (motivo.length < 10) return alert("Violación GxP: El motivo debe contener al menos 10 caracteres.");
    document.getElementById('modalAbortarLote').style.display = 'none';
    const r = await ejecutarConFirma({
        accion: 'ABORTAR_LOTE', titulo: '🛑 Abortar lote de producción', detalle: `${codigoLote(parseInt(loteId))} · Motivo: ${motivo}`,
        url: `/api/lotes/${loteId}/abortar/`, cuerpo: { motivo_aborto: motivo },
    });
    if (!r) { document.getElementById('modalAbortarLote').style.display = 'flex'; return; }
    if (r.ok) { limpiarSeleccionSiCorresponde(parseInt(loteId)); await cargarCatalogos(); }
    else alert(r.data.error || r.data.detail || 'No se pudo abortar el lote.');
}

function limpiarSeleccionSiCorresponde(loteId) {
    if (loteSeleccionado && loteSeleccionado.id === loteId) {
        loteSeleccionado = null;
        document.getElementById('editorLote').innerHTML = '<div class="empty-state">👈 Selecciona un lote activo.</div>';
        document.getElementById('tituloLoteActivo').innerHTML = '<span>⚡ Monitor de Ejecución: <strong style="color: white;">Selecciona un Lote</strong></span>';
    }
}

function abrirDatosFase(faseId) {
    abrirCapturaDatos({ faseId, alCambiar: () => cargarCatalogos() });
}

async function cambiarEstadoFase(faseId, estadoActual) {
    let siguienteEstado = estadoActual === 'PENDIENTE' ? 'EN_PROGRESO' : (estadoActual === 'EN_PROGRESO' ? 'COMPLETADA' : null);
    if (!siguienteEstado) return;
    const fase = fasesLoteActual.find(f => f.id === faseId) || null;
    const avisoDesviacion = estadoActual === 'PENDIENTE' && fase ? avisoVentanaInicio(fase) : '';
    const r = await ejecutarConFirma({
        avisoDesviacion,
        accion: `FASE_${siguienteEstado}`,
        titulo: siguienteEstado === 'EN_PROGRESO' ? '▶ Iniciar fase' : '✔ Completar fase',
        detalle: fase ? `[${fase.operacion_id_paso}] ${fase.operacion_nombre} · ${codigoLote(loteSeleccionado.id)}` : '',
        url: `/api/fases-lote/${faseId}/cambiar-estado/`, cuerpo: { estado: siguienteEstado },
    });
    if (!r) return;
    if (r.ok) {
        const avisos = [];
        if (r.data.advertencia_materiales) avisos.push('⚠️ Se inició con material incompleto:\n' + r.data.advertencia_materiales.join('\n'));
        if (r.data.mensaje_cascada) avisos.push(r.data.mensaje_cascada);
        if (r.data.evento_gmp) avisos.push(`📋 Se abrió el evento GMP ${r.data.evento_gmp} por el inicio fuera de ventana; Calidad lo evaluará.`);
        if (avisos.length) alert(avisos.join('\n\n'));
        await cargarCatalogos();
    } else if (r.data.codigo === 'DATOS_PENDIENTES') {
        // Falta capturar los datos de proceso: se abre el formulario directamente
        alert(r.data.error);
        abrirDatosFase(faseId);
    } else alert(r.data.error || r.data.detail || 'No se pudo cambiar el estado.');
}

async function abrirModalAsignacion(faseId) {
    document.getElementById('asignarFaseId').value = faseId;
    try {
        const [resOps, resRoles] = await Promise.all([fetch('/api/operadores/'), fetch('/api/roles-operador/')]);
        const ops = await resOps.json();
        const roles = await resRoles.json();
        document.getElementById('selectOperador').innerHTML = ops.map(o => `<option value="${o.id}">${o.nombre}</option>`).join('');
        document.getElementById('selectRolAsignado').innerHTML = roles.map(r => `<option value="${r.id}">${r.nombre}</option>`).join('');
        document.getElementById('modalAsignarOperador').style.display = 'flex';
    } catch (err) { alert("Error al cargar catálogos."); }
}

async function ejecutarAsignacionAPI() {
    const f_id = document.getElementById('asignarFaseId').value, op_id = document.getElementById('selectOperador').value, rol_id = document.getElementById('selectRolAsignado').value;
    try {
        const res = await fetch('/api/asignaciones-operador/', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ fase_lote: parseInt(f_id), operador: parseInt(op_id), rol_ejercido: parseInt(rol_id), horas_invertidas: 0.0 })
        });
        if (res.ok) { document.getElementById('modalAsignarOperador').style.display = 'none'; await cargarCatalogos(); } 
        else { const data = await res.json(); alert("Error GxP: " + JSON.stringify(data)); }
    } catch (err) { alert("Error de red."); }
}

function abrirModalReprogramar(faseId, currentFecha, currentHora) {
    document.getElementById('repFaseId').value = faseId;
    document.getElementById('repFecha').value = currentFecha || '';
    document.getElementById('repCHora').value = currentHora ? currentHora.substring(0,5) : '';
    document.getElementById('repMotivo').value = '';
    document.getElementById('repNotas').value = '';
    document.getElementById('modalReprogramar').style.display = 'flex';
}

function cerrarModalReprogramar() { document.getElementById('modalReprogramar').style.display = 'none'; }

async function ejecutarReprogramacionAPI() {
    const id = document.getElementById('repFaseId').value;
    const fecha = document.getElementById('repFecha').value;
    const hora = document.getElementById('repCHora').value;
    const motivo = document.getElementById('repMotivo').value;
    const notas = document.getElementById('repNotas').value;

    if (!fecha || !hora || !motivo) return alert("Fecha, Hora y Motivo son obligatorios.");

    try {
        const res = await fetch(`/api/fases-lote/${id}/reprogramar/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ fecha_programada: fecha, hora_inicio_programada: hora, motivo_reprogramacion: motivo, notas_reprogramacion: notas })
        });

        if (res.ok) {
            const data = await res.json();
            cerrarModalReprogramar();
            // Recargar del servidor: la reprogramación también movió las tareas sucesoras
            await cargarCatalogos();
            if (data.mensaje) alert(data.mensaje);
        } else {
            const data = await res.json();
            alert("Error GxP:\n" + (data.error || JSON.stringify(data)));
        }
    } catch (err) { alert("Error de red."); }
}

cargarCatalogos();


// --- Historial del lote (bitácora de auditoría) ---
async function abrirHistorialLote() {
    if (!loteSeleccionado) return;
    document.getElementById('tituloHistorialLote').textContent = `📜 Historial del lote ${loteSeleccionado.identificador_lote}`;
    const contenedor = document.getElementById('contenidoHistorialLote');
    contenedor.innerHTML = '<div class="aud-vacio">Cargando…</div>';
    document.getElementById('modalHistorialLote').style.display = 'flex';
    try {
        const datos = await cargarHistorialAuditoria({ lote: loteSeleccionado.id, limite: 500 });
        renderizarHistorialAuditoria(contenedor, datos.resultados, { vacio: 'Este lote todavía no tiene movimientos registrados (la bitácora empezó con la fase 2 de usuarios).' });
    } catch (e) {
        contenedor.innerHTML = `<div class="aud-vacio">${e.message}</div>`;
    }
}

function cerrarHistorialLote() {
    document.getElementById('modalHistorialLote').style.display = 'none';
}


// Si iniciar ahora queda fuera de la ventana de tolerancia de la receta, devuelve el aviso; si no, ''.
// El servidor vuelve a validarlo: esto solo adelanta la pregunta del motivo en el modal de firma.
function avisoVentanaInicio(fase) {
    if (!fase.inicio_programado) return '';
    const programado = new Date(fase.inicio_programado);
    const minutos = Math.round((Date.now() - programado) / 60000);
    const hora = programado.toLocaleString('es-MX', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    if (minutos < -(fase.tolerancia_antes_horas || 0) * 60) {
        return `⏩ Inicio adelantado ${formatearDesviacion(-minutos)} respecto a lo programado (${hora}); la tolerancia es de ${fase.tolerancia_antes_horas || 0} h.`;
    }
    if (minutos > (fase.tolerancia_despues_horas || 0) * 60) {
        return `⏰ Inicio con ${formatearDesviacion(minutos)} de retraso respecto a lo programado (${hora}); la tolerancia es de ${fase.tolerancia_despues_horas || 0} h.`;
    }
    return '';
}

// Usado por core/js/equipos.js para encontrar la fase de los modales
function buscarFaseParaEquipos(faseId) {
    return fasesLoteActual.find(f => f.id === faseId) || null;
}

configurarEquipos({ alActualizar: () => cargarCatalogos() });
