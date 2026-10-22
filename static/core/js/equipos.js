// static/core/js/equipos.js — Equipos de una fase de lote, compartido por Planificación y Piso de planta.
//
//   panel.innerHTML = htmlEquiposFase(fase, { editable: true });     // requerimientos, reservas y acciones
//   cargarCandidatosEquipos(panel);                                  // llena los selectores de reserva
//   configurarEquipos({ alActualizar: () => recargarPantalla() });   // qué hacer tras cada cambio
//
// `editable` (fase por iniciar): reservar, liberar, agregar, ajustar y retirar requerimientos (con motivo).
// `permiteCambio` (fase en ejecución): sustituir un equipo con motivo y firma electrónica (firma.js).
// Requiere utils.js (escaparHtml, getCookie) y core/css/equipos.css.

let alActualizarEquipos = () => location.reload();

function configurarEquipos({ alActualizar }) {
    if (alActualizar) alActualizarEquipos = alActualizar;
}

function formatearMomentoEquipo(iso) {
    if (!iso) return '--';
    return new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

// Texto corto para tarjetas: "🏗️ 1/2" (reservados / requeridos). Vacío si la fase no pide equipo.
function resumenEquiposFase(fase) {
    const activos = (fase.equipos || []).filter(ef => ef.activo);
    if (!activos.length) return null;
    const requeridos = activos.reduce((suma, ef) => suma + ef.cantidad, 0);
    const reservados = activos.reduce((suma, ef) => suma + ef.reservados, 0);
    return { requeridos, reservados, completo: reservados >= requeridos };
}

function htmlEquiposFase(fase, { editable = false, permiteCambio = false } = {}) {
    const requerimientos = fase.equipos || [];
    const activos = requerimientos.filter(ef => ef.activo);
    const retirados = requerimientos.filter(ef => !ef.activo);
    const botonAgregar = editable
        ? `<button type="button" class="btn-equipo-agregar" data-permiso="ajustar_material_lote" onclick="abrirModalEquipoFase('agregar', ${fase.id})">➕ Agregar tipo de equipo</button>`
        : '';
    if (!requerimientos.length) return `<div class="equipos-fase-vacio">Esta actividad no requiere equipo.</div>${botonAgregar}`;

    const bloques = activos.map(ef => {
        const vigentes = ef.reservas.filter(r => r.vigente);
        const cambiadas = ef.reservas.filter(r => r.activo && r.hasta);
        const faltan = ef.cantidad - vigentes.length;
        const horas = [ef.horas_preparacion ? `prep. ${ef.horas_preparacion} h` : '', ef.horas_limpieza ? `limpieza ${ef.horas_limpieza} h` : ''].filter(Boolean).join(' · ');
        const ajuste = ef.ajustado
            ? `<span class="equipo-fase__ajuste" data-tooltip="${escaparHtml(ef.motivo_ajuste)}">${ef.cantidad_receta === null ? 'agregado en el lote' : `receta: ×${ef.cantidad_receta}`}</span>`
            : '';
        const acciones = editable ? `
            <button class="btn-icon" data-permiso="ajustar_material_lote" data-tooltip="Ajustar cantidad, preparación o limpieza" onclick="abrirModalEquipoFase('ajustar', ${fase.id}, ${ef.id})">✏️</button>
            <button class="btn-icon" data-permiso="ajustar_material_lote" data-tooltip="Retirar este equipo de la fase" onclick="abrirModalEquipoFase('retirar', ${fase.id}, ${ef.id})">✕</button>` : '';

        const chips = vigentes.map(r => {
            const aviso = r.equipo_estado !== 'DISPONIBLE' ? ' <span data-tooltip="El equipo ya no está disponible">⚠️</span>' : '';
            const liberar = editable
                ? `<span class="chip-equipo__quitar" data-permiso="asignar_personal" data-tooltip="Liberar reserva" onclick="liberarReservaEquipo(${ef.id}, ${r.id})">✕</span>` : '';
            const cambiar = permiteCambio
                ? `<button type="button" class="btn-equipo-cambiar" data-permiso="asignar_personal" data-tooltip="Sustituir este equipo durante la ejecución" onclick="abrirCambioEquipo(${fase.id}, ${ef.id}, ${r.id})">🔁 Cambiar</button>` : '';
            return `<span class="chip-equipo" data-tooltip="${escaparHtml(r.equipo_nombre)} · ocupa ${formatearMomentoEquipo(r.inicio)} – ${formatearMomentoEquipo(r.fin)}">🏗️ ${escaparHtml(r.equipo)}${aviso} ${liberar}</span>${cambiar}`;
        }).join('');

        const falta = faltan > 0
            ? `<div class="equipo-fase__falta">⚠️ Falta reservar ${faltan}</div>
               ${editable ? `<select class="select-equipo" data-equipo-fase="${ef.id}" data-permiso="asignar_personal" onchange="reservarEquipoFase(${ef.id}, this.value)"><option value="">Cargando equipos…</option></select>` : ''}`
            : '';
        const historial = cambiadas.map(r =>
            `<div class="equipo-fase__historial" data-tooltip="${escaparHtml(r.motivo)}">↪ [${escaparHtml(r.equipo)}] usado hasta ${formatearMomentoEquipo(r.hasta)} · ${escaparHtml(r.motivo)}</div>`
        ).join('');

        return `
            <div class="equipo-fase">
                <div class="equipo-fase__cabecera">
                    <div>
                        <strong>${escaparHtml(ef.tipo_nombre)}</strong> ×${ef.cantidad} ${ajuste}
                        <div class="equipo-fase__meta">Ocupa ${formatearMomentoEquipo(ef.ocupacion_inicio)} – ${formatearMomentoEquipo(ef.ocupacion_fin)}${horas ? ` (${horas})` : ''}</div>
                    </div>
                    <div class="equipo-fase__acciones">${acciones}</div>
                </div>
                ${chips ? `<div class="equipo-fase__reservas">${chips}</div>` : ''}
                ${falta}
                ${historial}
            </div>`;
    }).join('');

    const chipsRetirados = retirados.map(ef =>
        `<span class="chip-equipo chip-equipo--retirado" data-tooltip="Retirado: ${escaparHtml(ef.motivo_ajuste)}">${escaparHtml(ef.tipo_nombre)}</span>`
    ).join('');

    return `${bloques || '<div class="equipos-fase-vacio">Todos los equipos fueron retirados.</div>'}
        ${chipsRetirados ? `<div class="equipos-fase-retirados">Retirados: ${chipsRetirados}</div>` : ''}
        ${botonAgregar}`;
}

// Versión compacta para tablas (Piso de planta): chips de los equipos reservados y aviso si falta alguno.
function htmlEquiposCompacto(fase, { permiteCambio = false } = {}) {
    const activos = (fase.equipos || []).filter(ef => ef.activo);
    if (!activos.length) return '';
    return `<div class="equipos-compacto">${activos.map(ef => {
        const vigentes = ef.reservas.filter(r => r.vigente);
        const chips = vigentes.map(r => {
            const aviso = r.equipo_estado !== 'DISPONIBLE' ? ' ⚠️' : '';
            const cambiar = permiteCambio
                ? `<button type="button" class="btn-equipo-cambiar" data-permiso="asignar_personal" data-tooltip="Sustituir este equipo durante la ejecución" onclick="abrirCambioEquipo(${fase.id}, ${ef.id}, ${r.id})">🔁</button>` : '';
            return `<span class="chip-equipo" data-tooltip="${escaparHtml(r.equipo_nombre)}">🏗️ ${escaparHtml(r.equipo)}${aviso}</span>${cambiar}`;
        }).join('');
        const faltan = ef.cantidad - vigentes.length;
        const falta = faltan > 0 ? `<span class="equipo-fase__falta" data-tooltip="Resérvalo en Planificación">⚠️ Falta ${faltan} ${escaparHtml(ef.tipo_nombre)}</span>` : '';
        return chips + falta;
    }).join('')}</div>`;
}

async function obtenerCandidatosEquipo(equipoFaseId, desdeAhora = false) {
    const res = await fetch(`/api/equipos-fase/${equipoFaseId}/candidatos/${desdeAhora ? '?desde=ahora' : ''}`);
    if (!res.ok) throw new Error('No se pudieron consultar los equipos.');
    return res.json();
}

// Llena los selectores de reserva: primero los equipos libres; los ocupados aparecen deshabilitados con su motivo.
async function cargarCandidatosEquipos(raiz) {
    const selects = raiz.querySelectorAll('select.select-equipo');
    await Promise.all([...selects].map(async (select) => {
        try {
            const candidatos = await obtenerCandidatosEquipo(select.dataset.equipoFase);
            const libres = candidatos.filter(c => c.disponible);
            const ocupados = candidatos.filter(c => !c.disponible);
            select.innerHTML = `<option value="">${libres.length ? '+ Reservar equipo…' : 'Sin equipos libres'}</option>`
                + libres.map(c => `<option value="${escaparHtml(c.id)}">[${escaparHtml(c.id)}] ${escaparHtml(c.nombre)}${c.area ? ` · ${escaparHtml(c.area)}` : ''}</option>`).join('')
                + ocupados.map(c => `<option value="" disabled title="${escaparHtml(c.motivo)}">✖ [${escaparHtml(c.id)}] ${escaparHtml(c.motivo)}</option>`).join('');
        } catch (e) {
            select.innerHTML = '<option value="">⚠️ No se pudieron cargar los equipos</option>';
        }
    }));
}

async function enviarEquipo(url, datos) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(datos),
    });
    const respuesta = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(respuesta.error || respuesta.detail || 'No se pudo guardar el cambio.');
    return respuesta;
}

async function reservarEquipoFase(equipoFaseId, equipoId) {
    if (!equipoId) return;
    try {
        await enviarEquipo(`/api/equipos-fase/${equipoFaseId}/reservar/`, { equipo: equipoId });
        await alActualizarEquipos();
    } catch (e) {
        alert('⚠️ ' + e.message);
        await alActualizarEquipos();
    }
}

async function liberarReservaEquipo(equipoFaseId, reservaId) {
    try {
        await enviarEquipo(`/api/equipos-fase/${equipoFaseId}/liberar/`, { reserva: reservaId });
        await alActualizarEquipos();
    } catch (e) {
        alert('⚠️ ' + e.message);
    }
}

// --- Modales (se construyen al abrirlos) ------------------------------------------------

function crearModalEquipo(titulo, cuerpoHtml, textoBoton) {
    const fondo = document.createElement('div');
    fondo.className = 'equipo-modal-fondo';
    fondo.innerHTML = `
        <form class="equipo-modal" role="dialog" aria-modal="true" autocomplete="off">
            <h3>${titulo}</h3>
            ${cuerpoHtml}
            <div class="equipo-modal__error" role="alert" hidden></div>
            <div class="equipo-modal__botones">
                <button type="button" class="equipo-modal__cancelar">Cancelar</button>
                <button type="submit" class="equipo-modal__aceptar">${textoBoton}</button>
            </div>
        </form>`;
    document.body.appendChild(fondo);
    const cerrar = () => { document.removeEventListener('keydown', alEscape); fondo.remove(); };
    const alEscape = (e) => { if (e.key === 'Escape') cerrar(); };
    document.addEventListener('keydown', alEscape);
    fondo.querySelector('.equipo-modal__cancelar').addEventListener('click', cerrar);
    const mostrarError = (texto) => {
        const caja = fondo.querySelector('.equipo-modal__error');
        caja.textContent = texto;
        caja.hidden = false;
    };
    return { fondo, formulario: fondo.querySelector('form'), cerrar, mostrarError };
}

// Agregar un tipo de equipo a la fase, ajustar su cantidad / horas, o retirarlo. Todo exige motivo.
async function abrirModalEquipoFase(modo, faseId, equipoFaseId = null, fase = null) {
    fase = fase || (typeof buscarFaseParaEquipos === 'function' ? buscarFaseParaEquipos(faseId) : null);
    const actual = fase && equipoFaseId ? (fase.equipos || []).find(ef => ef.id === equipoFaseId) : null;
    let tipos = [];
    if (modo === 'agregar') {
        try {
            const usados = new Set((fase ? fase.equipos : []).filter(ef => ef.activo).map(ef => ef.tipo));
            tipos = (await (await fetch('/api/tipos-equipo/?activo=true')).json()).filter(t => !usados.has(t.codigo));
        } catch (e) {
            return alert('No se pudo cargar el catálogo de tipos de equipo.');
        }
        if (!tipos.length) return alert('No hay más tipos de equipo activos para agregar.');
    }
    const titulos = { agregar: '➕ Agregar equipo a la fase', ajustar: '✏️ Ajustar equipo del lote', retirar: '✕ Retirar equipo de la fase' };
    const contexto = fase ? `[${escaparHtml(fase.operacion_id_paso)}] ${escaparHtml(fase.operacion_nombre)} · Lote ${escaparHtml(fase.lote_codigo)}` : '';
    const campos = modo === 'retirar' ? '' : `
        <div class="equipo-modal__campos">
            ${modo === 'agregar' ? `<label class="equipo-modal__campo equipo-modal__campo--ancho"><span>Tipo de equipo</span>
                <select name="tipo">${tipos.map(t => `<option value="${escaparHtml(t.codigo)}">${escaparHtml(t.nombre)}</option>`).join('')}</select></label>` : ''}
            <label class="equipo-modal__campo"><span>Cantidad</span><input type="number" name="cantidad" min="1" step="1" value="${actual ? actual.cantidad : 1}" required></label>
            <label class="equipo-modal__campo"><span>Preparación (h)</span><input type="number" name="horas_preparacion" min="0" step="0.5" value="${actual ? actual.horas_preparacion : 0}"></label>
            <label class="equipo-modal__campo"><span>Limpieza (h)</span><input type="number" name="horas_limpieza" min="0" step="0.5" value="${actual ? actual.horas_limpieza : 0}"></label>
        </div>`;
    const resumen = actual
        ? `<div class="equipo-modal__resumen"><strong>${escaparHtml(actual.tipo_nombre)}</strong> ×${actual.cantidad}<br>${contexto}
           ${actual.cantidad_receta !== null ? `<br>Cantidad de receta: ×${actual.cantidad_receta}` : ''}
           ${modo === 'retirar' && actual.reservados ? `<br>⚠️ Se liberarán ${actual.reservados} reserva(s).` : ''}</div>`
        : `<div class="equipo-modal__resumen">${contexto}</div>`;
    const { formulario, cerrar, mostrarError } = crearModalEquipo(titulos[modo], `${resumen}${campos}
        <label class="equipo-modal__campo equipo-modal__campo--ancho"><span>Motivo del cambio (GxP)</span>
            <textarea name="motivo" rows="2" minlength="5" required placeholder="Ej. Escalamiento a dos biorreactores"></textarea></label>`,
        modo === 'retirar' ? 'Retirar' : 'Guardar');
    formulario.elements[modo === 'retirar' ? 'motivo' : 'cantidad'].focus();

    formulario.addEventListener('submit', async (evento) => {
        evento.preventDefault();
        const valor = (nombre) => formulario.elements[nombre] ? formulario.elements[nombre].value : undefined;
        const datos = { motivo: valor('motivo').trim(), cantidad: valor('cantidad'),
                        horas_preparacion: valor('horas_preparacion'), horas_limpieza: valor('horas_limpieza') };
        const url = modo === 'agregar' ? '/api/equipos-fase/agregar/' : `/api/equipos-fase/${equipoFaseId}/${modo}/`;
        if (modo === 'agregar') Object.assign(datos, { fase: faseId, tipo: valor('tipo') });
        try {
            await enviarEquipo(url, datos);
            cerrar();
            await alActualizarEquipos();
        } catch (e) {
            mostrarError(e.message);
        }
    });
}

// Sustituir un equipo con la fase en ejecución: se elige el nuevo, se escribe el motivo y se firma.
async function abrirCambioEquipo(faseId, equipoFaseId, reservaId, fase = null) {
    fase = fase || (typeof buscarFaseParaEquipos === 'function' ? buscarFaseParaEquipos(faseId) : null);
    const ef = fase ? (fase.equipos || []).find(x => x.id === equipoFaseId) : null;
    const reserva = ef ? ef.reservas.find(r => r.id === reservaId) : null;
    let candidatos;
    try {
        candidatos = await obtenerCandidatosEquipo(equipoFaseId, true);
    } catch (e) {
        return alert(e.message);
    }
    const libres = candidatos.filter(c => c.disponible && (!reserva || c.id !== reserva.equipo));
    if (!libres.length) return alert('No hay otro equipo de este tipo libre desde ahora hasta el fin de la fase.');

    const { formulario, cerrar } = crearModalEquipo('🔁 Cambiar equipo durante la ejecución', `
        <div class="equipo-modal__resumen">
            ${fase ? `[${escaparHtml(fase.operacion_id_paso)}] ${escaparHtml(fase.operacion_nombre)} · Lote ${escaparHtml(fase.lote_codigo)}<br>` : ''}
            Equipo actual: <strong>${reserva ? `[${escaparHtml(reserva.equipo)}] ${escaparHtml(reserva.equipo_nombre)}` : ''}</strong><br>
            El actual queda registrado hasta este momento y el nuevo desde ahora.
        </div>
        <label class="equipo-modal__campo equipo-modal__campo--ancho"><span>Equipo nuevo</span>
            <select name="equipo" required>${libres.map(c => `<option value="${escaparHtml(c.id)}">[${escaparHtml(c.id)}] ${escaparHtml(c.nombre)}${c.area ? ` · ${escaparHtml(c.area)}` : ''}</option>`).join('')}</select></label>
        <label class="equipo-modal__campo equipo-modal__campo--ancho"><span>Motivo del cambio (obligatorio)</span>
            <textarea name="motivo" rows="2" minlength="5" required placeholder="Ej. Falla del agitador del biorreactor"></textarea></label>`, 'Continuar a la firma');
    formulario.elements.motivo.focus();

    formulario.addEventListener('submit', async (evento) => {
        evento.preventDefault();
        const equipo = formulario.elements.equipo.value;
        const motivo = formulario.elements.motivo.value.trim();
        cerrar();
        const r = await ejecutarConFirma({
            accion: 'CAMBIAR_EQUIPO', titulo: '🔁 Cambiar equipo',
            detalle: `${reserva ? reserva.equipo : ''} → ${equipo} · ${motivo}`,
            url: `/api/equipos-fase/${equipoFaseId}/cambiar/`, cuerpo: { reserva: reservaId, equipo, motivo },
        });
        if (!r) return;
        if (!r.ok) alert('⚠️ ' + (r.data.error || r.data.detail || 'No se pudo cambiar el equipo.'));
        await alActualizarEquipos();
    });
}
