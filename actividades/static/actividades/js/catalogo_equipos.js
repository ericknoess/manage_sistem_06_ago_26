// actividades/static/actividades/js/catalogo_equipos.js
// Catálogo maestro de equipos y tipos de equipo: búsqueda, filtros, alta, edición, estado operativo,
// calibración y baja lógica (activo=false). Los cambios quedan en la bitácora (AuditoriaMixin).

const DIAS_AVISO_CALIBRACION = 30;

let equipos = [];
let tipos = [];
let opciones = { estados: [], tipos: [] };
let equipoEnEdicion = null;  // código del equipo que se edita; null = alta
let tipoEnEdicion = null;

async function cargarCatalogo() {
    try {
        const [resEq, resTipos, resOpc] = await Promise.all([
            fetch('/api/equipos/'), fetch('/api/tipos-equipo/'), fetch('/api/equipos/opciones/'),
        ]);
        equipos = await resEq.json();
        tipos = await resTipos.json();
        opciones = await resOpc.json();
        llenarSelects();
        renderizarEquipos();
        renderizarTipos();
    } catch (err) {
        document.getElementById('cuerpoEquipos').innerHTML = `<tr><td colspan="10" class="estado-vacio">⚠️ No se pudo cargar el catálogo.</td></tr>`;
    }
}

function llenarSelects() {
    const opcionesHtml = (lista) => lista.map(o => `<option value="${escaparHtml(o.valor)}">${escaparHtml(o.etiqueta)}</option>`).join('');
    const filtroTipo = document.getElementById('filtroTipo');
    const seleccionTipo = filtroTipo.value;
    filtroTipo.innerHTML = '<option value="">Todos los tipos</option>' + tipos.map(t => `<option value="${escaparHtml(t.codigo)}">${escaparHtml(t.nombre)}</option>`).join('');
    filtroTipo.value = seleccionTipo;
    const filtroEstado = document.getElementById('filtroEstadoOperativo');
    if (filtroEstado.options.length === 1) filtroEstado.insertAdjacentHTML('beforeend', opcionesHtml(opciones.estados));
    document.getElementById('campoEstado').innerHTML = opcionesHtml(opciones.estados);
}

function mostrarSeccion(seccion) {
    const esEquipos = seccion === 'equipos';
    document.getElementById('seccionEquipos').hidden = !esEquipos;
    document.getElementById('seccionTipos').hidden = esEquipos;
    document.getElementById('pestanaEquipos').classList.toggle('is-activa', esEquipos);
    document.getElementById('pestanaTipos').classList.toggle('is-activa', !esEquipos);
    document.getElementById('pestanaEquipos').setAttribute('aria-selected', esEquipos);
    document.getElementById('pestanaTipos').setAttribute('aria-selected', !esEquipos);
}

// --- Equipos ---------------------------------------------------------------------

function equiposFiltrados() {
    const palabras = normalizarBusqueda(document.getElementById('filtroTexto').value).split(/\s+/).filter(Boolean);
    const tipo = document.getElementById('filtroTipo').value;
    const estadoOperativo = document.getElementById('filtroEstadoOperativo').value;
    const alta = document.getElementById('filtroEstado').value;
    return equipos.filter(e => {
        const pajar = normalizarBusqueda([e.id, e.nombre, e.area, e.tipo_nombre, e.capacidad].join(' '));
        return palabras.every(p => pajar.includes(p))
            && (!tipo || e.tipo === tipo)
            && (!estadoOperativo || e.estado === estadoOperativo)
            && (alta === 'todos' || (alta === 'activos') === e.activo);
    });
}

function insigniaEstado(e) {
    const clase = { DISPONIBLE: 'disponible', MANTENIMIENTO: 'mantenimiento', FUERA_SERVICIO: 'fuera' }[e.estado] || 'fuera';
    return `<span class="estado-equipo estado-equipo--${clase}">${escaparHtml(e.estado_display)}</span>`;
}

function celdaCalibracion(e) {
    if (!e.calibracion_vence) return '<span class="sin-dato">—</span>';
    const fecha = new Date(e.calibracion_vence + 'T00:00:00').toLocaleDateString('es-MX');
    if (e.dias_calibracion < 0) return `<span class="calibracion calibracion--vencida" title="No se puede reservar">⛔ ${fecha} · vencida</span>`;
    if (e.dias_calibracion <= DIAS_AVISO_CALIBRACION) return `<span class="calibracion calibracion--proxima">⚠️ ${fecha} · ${e.dias_calibracion} d</span>`;
    return `<span class="calibracion">${fecha}</span>`;
}

function renderizarEquipos() {
    const lista = equiposFiltrados();
    document.getElementById('conteo').innerText = `${lista.length} de ${equipos.length} equipos`;
    const cuerpo = document.getElementById('cuerpoEquipos');
    if (!lista.length) {
        cuerpo.innerHTML = `<tr><td colspan="10" class="estado-vacio">Ningún equipo coincide con la búsqueda.</td></tr>`;
        return;
    }
    cuerpo.innerHTML = lista.map(e => `
        <tr class="${e.activo ? '' : 'fila-inactiva'}">
            <td class="col-codigo">${escaparHtml(e.id)}</td>
            <td><strong>${escaparHtml(e.nombre)}</strong></td>
            <td>${escaparHtml(e.tipo_nombre)}</td>
            <td>${escaparHtml(e.area) || '<span class="sin-dato">—</span>'}</td>
            <td>${escaparHtml(e.capacidad) || '<span class="sin-dato">—</span>'}</td>
            <td>${insigniaEstado(e)}</td>
            <td>${celdaCalibracion(e)}</td>
            <td>${e.reservas_vigentes || '<span class="sin-dato">0</span>'}</td>
            <td><span class="estado ${e.activo ? 'estado--activo' : 'estado--inactivo'}">${e.activo ? 'Activo' : 'Baja'}</span></td>
            <td class="col-acciones">
                <button class="btn-icono" data-permiso="gestionar_catalogos" title="Editar" onclick="abrirModalEquipo('${escaparHtml(e.id)}')">✏️</button>
                ${e.activo
                    ? `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Dar de baja (baja lógica)" onclick="cambiarAltaEquipo('${escaparHtml(e.id)}', false)">⏸️</button>`
                    : `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Reactivar" onclick="cambiarAltaEquipo('${escaparHtml(e.id)}', true)">▶️</button>`}
            </td>
        </tr>`).join('');
}

function abrirModalEquipo(id = null) {
    equipoEnEdicion = id;
    const e = id ? equipos.find(x => x.id === id) : null;
    // En el selector de tipo solo aparecen los activos, salvo el que ya tenga el equipo
    const tiposVisibles = tipos.filter(t => t.activo || (e && t.codigo === e.tipo));
    document.getElementById('campoTipo').innerHTML = tiposVisibles.map(t => `<option value="${escaparHtml(t.codigo)}">${escaparHtml(t.nombre)}</option>`).join('');
    document.getElementById('modalEquipoTitulo').innerText = e ? `✏️ Editar ${e.id}` : '➕ Nuevo equipo';
    document.getElementById('campoId').value = e ? e.id : '';
    document.getElementById('campoId').readOnly = !!e;
    document.getElementById('ayudaCodigo').innerText = e ? 'El código no se puede cambiar.' : 'Único y permanente: lo referencian las reservas de los lotes.';
    document.getElementById('campoNombre').value = e ? e.nombre : '';
    document.getElementById('campoTipo').value = e ? e.tipo : (document.getElementById('filtroTipo').value || (tiposVisibles[0] || {}).codigo || '');
    document.getElementById('campoArea').value = e ? e.area : '';
    document.getElementById('campoCapacidad').value = e ? e.capacidad : '';
    document.getElementById('campoEstado').value = e ? e.estado : 'DISPONIBLE';
    document.getElementById('campoCalibracion').value = e && e.calibracion_vence ? e.calibracion_vence : '';
    document.getElementById('errorEquipo').hidden = true;
    document.getElementById('modalEquipo').style.display = 'flex';
    document.getElementById(e ? 'campoNombre' : 'campoId').focus();
}

async function guardarEquipo(evento) {
    evento.preventDefault();
    const datos = {
        nombre: document.getElementById('campoNombre').value.trim(),
        tipo: document.getElementById('campoTipo').value,
        area: document.getElementById('campoArea').value.trim(),
        capacidad: document.getElementById('campoCapacidad').value.trim(),
        estado: document.getElementById('campoEstado').value,
        calibracion_vence: document.getElementById('campoCalibracion').value || null,
    };
    if (!equipoEnEdicion) {
        datos.id = document.getElementById('campoId').value.trim();
        if (equipos.some(e => e.id.toLowerCase() === datos.id.toLowerCase())) {
            return mostrarError('errorEquipo', { id: `Ya existe un equipo con el código "${datos.id}".` });
        }
    }
    const url = equipoEnEdicion ? `/api/equipos/${encodeURIComponent(equipoEnEdicion)}/` : '/api/equipos/';
    await enviar(url, equipoEnEdicion ? 'PATCH' : 'POST', datos, 'modalEquipo', 'errorEquipo');
}

async function cambiarAltaEquipo(id, activo) {
    const e = equipos.find(x => x.id === id);
    if (!activo) {
        const aviso = e.reservas_vigentes
            ? `\n\nTiene ${e.reservas_vigentes} reserva(s) vigente(s) en lotes: se conservan, pero aparecerán como alerta en Planificación.`
            : '';
        if (!confirm(`¿Dar de baja [${e.id}] ${e.nombre}?${aviso}`)) return;
    }
    await enviar(`/api/equipos/${encodeURIComponent(id)}/`, 'PATCH', { activo });
}

// --- Tipos de equipo ---------------------------------------------------------------

function renderizarTipos() {
    const cuerpo = document.getElementById('cuerpoTipos');
    if (!tipos.length) {
        cuerpo.innerHTML = `<tr><td colspan="6" class="estado-vacio">Aún no hay tipos de equipo.</td></tr>`;
        return;
    }
    cuerpo.innerHTML = tipos.map(t => `
        <tr class="${t.activo ? '' : 'fila-inactiva'}">
            <td class="col-codigo">${escaparHtml(t.codigo)}</td>
            <td><strong>${escaparHtml(t.nombre)}</strong></td>
            <td>${t.equipos_registrados || '<span class="sin-dato">0</span>'}</td>
            <td>${t.usos_en_recetas || '<span class="sin-dato">0</span>'}</td>
            <td><span class="estado ${t.activo ? 'estado--activo' : 'estado--inactivo'}">${t.activo ? 'Activo' : 'Baja'}</span></td>
            <td class="col-acciones">
                <button class="btn-icono" data-permiso="gestionar_catalogos" title="Editar" onclick="abrirModalTipo('${escaparHtml(t.codigo)}')">✏️</button>
                ${t.activo
                    ? `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Dar de baja" onclick="cambiarAltaTipo('${escaparHtml(t.codigo)}', false)">⏸️</button>`
                    : `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Reactivar" onclick="cambiarAltaTipo('${escaparHtml(t.codigo)}', true)">▶️</button>`}
            </td>
        </tr>`).join('');
}

function abrirModalTipo(codigo = null) {
    tipoEnEdicion = codigo;
    const t = codigo ? tipos.find(x => x.codigo === codigo) : null;
    document.getElementById('modalTipoTitulo').innerText = t ? `✏️ Editar ${t.nombre}` : '➕ Nuevo tipo de equipo';
    document.getElementById('campoTipoCodigo').value = t ? t.codigo : '';
    document.getElementById('campoTipoCodigo').readOnly = !!t;
    document.getElementById('campoTipoNombre').value = t ? t.nombre : '';
    document.getElementById('errorTipo').hidden = true;
    document.getElementById('modalTipo').style.display = 'flex';
    document.getElementById(t ? 'campoTipoNombre' : 'campoTipoCodigo').focus();
}

async function guardarTipo(evento) {
    evento.preventDefault();
    const datos = { nombre: document.getElementById('campoTipoNombre').value.trim() };
    if (!tipoEnEdicion) datos.codigo = document.getElementById('campoTipoCodigo').value.trim();
    const url = tipoEnEdicion ? `/api/tipos-equipo/${encodeURIComponent(tipoEnEdicion)}/` : '/api/tipos-equipo/';
    await enviar(url, tipoEnEdicion ? 'PATCH' : 'POST', datos, 'modalTipo', 'errorTipo');
}

async function cambiarAltaTipo(codigo, activo) {
    const t = tipos.find(x => x.codigo === codigo);
    if (!activo && !confirm(`¿Dar de baja el tipo ${t.nombre}?\n\nLas recetas y equipos que ya lo usan se conservan, pero no se podrá elegir en altas nuevas.`)) return;
    await enviar(`/api/tipos-equipo/${encodeURIComponent(codigo)}/`, 'PATCH', { activo });
}

// --- Comunes --------------------------------------------------------------------------

function cerrarModal(id) {
    document.getElementById(id).style.display = 'none';
}

function mostrarError(idCaja, datos) {
    const caja = document.getElementById(idCaja);
    const etiquetas = { id: 'Código', codigo: 'Código', calibracion_vence: 'Calibración', tipo: 'Tipo', nombre: 'Nombre' };
    const mensajes = typeof datos === 'object'
        ? Object.entries(datos).map(([campo, errores]) => `${etiquetas[campo] || campo}: ${[].concat(errores).join(' ')}`)
        : [String(datos)];
    caja.innerHTML = mensajes.map(escaparHtml).join('<br>');
    caja.hidden = false;
}

// Envía el cambio; si viene de un modal, muestra ahí los errores y lo cierra al terminar bien.
async function enviar(url, metodo, datos, idModal = null, idError = null) {
    try {
        const res = await fetch(url, {
            method: metodo,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify(datos),
        });
        if (!res.ok) {
            const error = await res.json().catch(() => ({ detalle: 'El servidor rechazó el cambio.' }));
            if (idError) return mostrarError(idError, error);
            return alert(error.detail || Object.values(error).flat().join('\n'));
        }
        if (idModal) cerrarModal(idModal);
        await cargarCatalogo();
    } catch (err) {
        if (idError) mostrarError(idError, 'Error de red al guardar.');
        else alert('Error de red al guardar.');
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    ['modalEquipo', 'modalTipo'].forEach(id => {
        if (document.getElementById(id).style.display === 'flex') cerrarModal(id);
    });
});
document.addEventListener('DOMContentLoaded', cargarCatalogo);
