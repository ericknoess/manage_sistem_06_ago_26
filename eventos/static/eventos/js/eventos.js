// eventos/static/eventos/js/eventos.js — Pantalla /eventos/: lista, detalle, evaluación y anulación de eventos GMP.
//
// La URL acepta ?lote=<id> (eventos de un lote, ej. desde Piso de planta) y ?evento=<id> (abre su detalle).
// Reportar usa el formulario compartido (static/core/js/eventos.js); cerrar y anular piden firma (firma.js)
// y el permiso `evaluar_evento` (los botones llevan data-permiso; quien reportó no los ve: regla de cuatro ojos).

let eventos = [];
let opcionesEventos = null;
let eventoAbierto = null;
const parametrosUrl = new URLSearchParams(location.search);
let loteFiltro = parametrosUrl.get('lote');

const fechaHora = (iso) => iso ? new Date(iso).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' }) : '—';
const ICONO_TIPO = {
    FUERA_ESPECIFICACION: '🚨', INICIO_FUERA_VENTANA: '⏰', FALLA_EQUIPO: '🛠️', MATERIAL: '📦',
    PROCEDIMIENTO: '📋', AMBIENTAL: '🌡️', CONTAMINACION: '🦠', OTRO: '❔',
};

async function iniciar() {
    const res = await fetch('/api/eventos/opciones/');
    opcionesEventos = await res.json();
    document.getElementById('filtroTipo').innerHTML = '<option value="">Todos los tipos</option>'
        + opcionesEventos.tipos.map(t => `<option value="${t.valor}">${ICONO_TIPO[t.valor] || ''} ${escaparHtml(t.nombre)}</option>`).join('');
    if (loteFiltro) document.getElementById('filtroEstado').value = '';
    await buscar();
    if (parametrosUrl.get('evento')) abrirDetalle(Number(parametrosUrl.get('evento')));
}

function quitarFiltroLote() {
    loteFiltro = null;
    history.replaceState(null, '', location.pathname);
    buscar();
}

async function buscar() {
    const p = new URLSearchParams();
    const valor = (id) => document.getElementById(id).value.trim();
    if (valor('filtroEstado')) p.set('estado', valor('filtroEstado'));
    if (valor('filtroTipo')) p.set('tipo', valor('filtroTipo'));
    if (valor('filtroDesde')) p.set('desde', valor('filtroDesde'));
    if (valor('filtroHasta')) p.set('hasta', valor('filtroHasta'));
    if (valor('filtroTexto')) p.set('q', valor('filtroTexto'));
    if (loteFiltro) p.set('lote', loteFiltro);
    const cuerpo = document.getElementById('cuerpoEventos');
    try {
        const [res, resumen] = await Promise.all([
            fetch(`/api/eventos/?${p}`),
            fetch(`/api/eventos/resumen/${loteFiltro ? `?lote=${loteFiltro}` : ''}`),
        ]);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || data.detail || 'No se pudieron cargar los eventos.');
        eventos = data.eventos;
        pintarResumen(await resumen.json());
        document.getElementById('conteo').textContent = data.total > data.limite
            ? `${data.limite} de ${data.total} (afina los filtros)` : `${data.total} evento${data.total === 1 ? '' : 's'}`;
        const chip = document.getElementById('filtroLote');
        chip.hidden = !loteFiltro;
        if (loteFiltro) {
            const nombre = eventos[0] ? eventos[0].lote_identificador : `#${loteFiltro}`;
            chip.innerHTML = `Lote ${escaparHtml(nombre)} <button type="button" onclick="quitarFiltroLote()" title="Ver todos los lotes">✕</button>`;
        }
        pintarTabla();
    } catch (err) {
        cuerpo.innerHTML = `<tr><td colspan="7" class="estado-vacio">⚠️ ${escaparHtml(err.message)}</td></tr>`;
    }
}

function pintarResumen(conteo) {
    const caja = document.getElementById('resumenEventos');
    const tarjeta = (estado, nombre, clase) => `
        <button type="button" class="tarjeta-resumen tarjeta-resumen--${clase}" onclick="document.getElementById('filtroEstado').value='${estado}'; buscar()">
            <span class="tarjeta-resumen__numero">${conteo[estado] || 0}</span><span>${nombre}</span></button>`;
    caja.innerHTML = tarjeta('ABIERTO', 'Abiertos · por evaluar', 'abierto') + tarjeta('CERRADO', 'Cerrados', 'cerrado')
        + tarjeta('ANULADO', 'Anulados', 'anulado');
}

function htmlEstado(ev) {
    if (ev.estado === 'ABIERTO') return '<span class="estado-evento estado-evento--abierto">Abierto</span>';
    if (ev.estado === 'ANULADO') return '<span class="estado-evento estado-evento--anulado">Anulado</span>';
    return `<span class="estado-evento estado-evento--${(ev.clasificacion || 'cerrado').toLowerCase()}">${escaparHtml(ev.clasificacion_nombre || 'Cerrado')}</span>`
        + (ev.numero_desviacion ? `<small class="numero-desviacion">${escaparHtml(ev.numero_desviacion)}</small>` : '');
}

function pintarTabla() {
    const cuerpo = document.getElementById('cuerpoEventos');
    if (!eventos.length) {
        cuerpo.innerHTML = '<tr><td colspan="7" class="estado-vacio">No hay eventos con estos filtros.</td></tr>';
        return;
    }
    cuerpo.innerHTML = eventos.map(ev => `
        <tr class="fila-evento fila-evento--${ev.estado.toLowerCase()}" onclick="abrirDetalle(${ev.id})" tabindex="0"
            onkeydown="if (event.key === 'Enter') abrirDetalle(${ev.id})">
            <td class="col-codigo">${escaparHtml(ev.folio)}</td>
            <td>${fechaHora(ev.ocurrio_en)}</td>
            <td><strong>${escaparHtml(ev.lote_identificador)}</strong>${ev.tarea ? `<small class="sub">${escaparHtml(ev.tarea)}</small>` : ''}</td>
            <td><span class="tipo-evento">${ICONO_TIPO[ev.tipo] || ''} ${escaparHtml(ev.tipo_nombre)}</span>
                ${ev.origen === 'AUTOMATICO' ? '<small class="sub">automático</small>' : ''}</td>
            <td class="col-que"><strong>${escaparHtml(ev.titulo)}</strong><small class="sub">${escaparHtml(ev.descripcion.slice(0, 140))}${ev.descripcion.length > 140 ? '…' : ''}</small></td>
            <td>${escaparHtml(ev.reportado_por_nombre)}</td>
            <td>${htmlEstado(ev)}</td>
        </tr>`).join('');
}

// ------------------------------------------------------------------
// Detalle, evaluación y anulación
// ------------------------------------------------------------------
async function abrirDetalle(id) {
    let ev = eventos.find(e => e.id === id);
    if (!ev) {
        const res = await fetch(`/api/eventos/${id}/`);
        if (!res.ok) return;
        ev = await res.json();
    }
    eventoAbierto = ev;
    document.getElementById('modalEvento').style.display = 'flex';
    pintarDetalle();
}

function cerrarDetalle() {
    eventoAbierto = null;
    document.getElementById('modalEvento').style.display = 'none';
}

function pintarDetalle(modo = '') {
    const ev = eventoAbierto;
    document.getElementById('tituloEvento').innerHTML = `${ICONO_TIPO[ev.tipo] || ''} ${escaparHtml(ev.folio)} ${htmlEstado(ev)}`;
    const fila = (etiqueta, valor) => valor ? `<div class="dato"><span>${etiqueta}</span><strong>${valor}</strong></div>` : '';
    const dato = ev.dato ? `${escaparHtml(ev.dato.parametro)} = ${escaparHtml(ev.dato.valor)} ${escaparHtml(ev.dato.unidad || '')}`
        + (ev.dato.limites ? ` <small>(especificación ${escaparHtml(ev.dato.limites.especificacion_min || '−∞')} a ${escaparHtml(ev.dato.limites.especificacion_max || '∞')})</small>` : '')
        + (ev.dato.vigente ? '' : ' <small>· después se corrigió</small>') : '';
    const puedeEvaluar = ev.estado === 'ABIERTO' && opcionesEventos.puede_evaluar && !ev.reporto_yo;
    const firma = ev.firma ? `<div class="firma-evento">✍️ <strong>${escaparHtml(ev.firma.nombre)}</strong> · ${escaparHtml(ev.firma.significado)}
        · ${fechaHora(ev.firma.fecha)} · ${escaparHtml(ev.firma.metodo)}</div>` : '';

    let evaluacion = '';
    if (ev.estado === 'CERRADO') {
        evaluacion = `<section class="bloque-evento bloque-evento--evaluacion"><h4>Evaluación de Calidad</h4>
            <div class="datos-evento">${fila('Clasificación', escaparHtml(ev.clasificacion_nombre))}${fila('Nº de desviación', escaparHtml(ev.numero_desviacion))}</div>
            <p class="texto-evento">${escaparHtml(ev.evaluacion)}</p>${firma}</section>`;
    } else if (ev.estado === 'ANULADO') {
        evaluacion = `<section class="bloque-evento bloque-evento--anulado"><h4>Anulado</h4>
            <p class="texto-evento">${escaparHtml(ev.motivo_anulacion)}</p>${firma}</section>`;
    }

    let acciones = '';
    if (modo === 'cerrar') {
        acciones = `
            <form class="form-evaluar" onsubmit="event.preventDefault(); enviarCierre(this)">
                <h4>Evaluar y cerrar</h4>
                <div class="formulario">
                    <label class="campo">Clasificación
                        <select name="clasificacion" required onchange="this.form.numero_desviacion.required = this.value !== 'SIN_IMPACTO'">
                            <option value="">Elige…</option>
                            ${opcionesEventos.clasificaciones.map(c => `<option value="${c.valor}">${escaparHtml(c.nombre)}</option>`).join('')}
                        </select></label>
                    <label class="campo">Nº de desviación <small>(obligatorio si es desviación)</small>
                        <input type="text" name="numero_desviacion" maxlength="50" placeholder="Ej. DV-2026-031"></label>
                    <label class="campo campo--ancho">Evaluación del impacto <small>(mínimo 10 caracteres)</small>
                        <textarea name="evaluacion" rows="4" required placeholder="Impacto en la calidad del lote, en qué se basa la decisión…"></textarea></label>
                </div>
                <div class="form-evaluar__pie">
                    <button type="button" class="btn-secundario" onclick="pintarDetalle()">Cancelar</button>
                    <button type="submit" class="btn-primario">✍️ Firmar y cerrar</button>
                </div>
            </form>`;
    } else if (modo === 'anular') {
        acciones = `
            <form class="form-evaluar" onsubmit="event.preventDefault(); enviarAnulacion(this)">
                <h4>Anular evento</h4>
                <p class="nota-evento">Solo si se registró por error (lote equivocado, duplicado…). Queda en el informe como anulado.</p>
                <label class="campo campo--ancho">Motivo <small>(mínimo 10 caracteres)</small>
                    <textarea name="motivo" rows="3" required></textarea></label>
                <div class="form-evaluar__pie">
                    <button type="button" class="btn-secundario" onclick="pintarDetalle()">Cancelar</button>
                    <button type="submit" class="btn-peligro">✍️ Firmar y anular</button>
                </div>
            </form>`;
    } else if (puedeEvaluar) {
        acciones = `<div class="acciones-evento">
            <button type="button" class="btn-secundario" data-permiso="evaluar_evento" onclick="pintarDetalle('anular')">Anular…</button>
            <button type="button" class="btn-primario" data-permiso="evaluar_evento" onclick="pintarDetalle('cerrar')">✅ Evaluar y cerrar</button></div>`;
    } else if (ev.estado === 'ABIERTO') {
        acciones = `<p class="nota-evento">${ev.reporto_yo ? 'Lo reportaste tú: lo evalúa otra persona de Calidad, Supervisión o Jefatura (regla de cuatro ojos).'
            : 'Pendiente de evaluación por Calidad, Supervisión o Jefatura.'}</p>`;
    }

    document.getElementById('detalleEvento').innerHTML = `
        <h4 class="titulo-evento">${escaparHtml(ev.titulo)}</h4>
        <div class="datos-evento">
            ${fila('Lote', `<a href="/ejecucion/" title="Abrir Piso de planta">${escaparHtml(ev.lote_identificador)}</a>`)}
            ${fila('Tarea', escaparHtml(ev.tarea))}
            ${fila('Tipo', `${escaparHtml(ev.tipo_nombre)}${ev.origen === 'AUTOMATICO' ? ' · automático' : ''}`)}
            ${fila('Ocurrió', fechaHora(ev.ocurrio_en))}
            ${fila('Equipo', escaparHtml(ev.equipo_nombre))}
            ${fila('Dato', dato)}
            ${fila('Reportó', `${escaparHtml(ev.reportado_por_nombre)} · ${fechaHora(ev.reportado_en)}`)}
        </div>
        <section class="bloque-evento"><h4>¿Qué pasó?</h4><p class="texto-evento">${escaparHtml(ev.descripcion)}</p>
            ${ev.accion_inmediata ? `<h4>Acción inmediata</h4><p class="texto-evento">${escaparHtml(ev.accion_inmediata)}</p>` : ''}</section>
        ${evaluacion}
        ${acciones}
        <p class="pie-evento"><a href="/graficas/?proceso=${ev.proceso}&lotes=${ev.lote}">📉 Gráficas del lote</a>
           · <a href="?lote=${ev.lote}">⚠️ Todos los eventos del lote</a></p>`;
    if (window.aplicarPermisos) aplicarPermisos(document.getElementById('detalleEvento'));
    const primero = document.querySelector('#detalleEvento form select, #detalleEvento form textarea');
    if (primero) primero.focus();
}

async function firmarAccion(accion, titulo, url, cuerpo) {
    const r = await ejecutarConFirma({ accion, titulo, detalle: `${eventoAbierto.folio} · ${eventoAbierto.titulo}`, url, metodo: 'POST', cuerpo });
    if (!r) return;
    if (!r.ok) { alert((r.data && r.data.error) || 'No se pudo completar la acción.'); return; }
    eventoAbierto = r.data;
    const i = eventos.findIndex(e => e.id === r.data.id);
    if (i >= 0) eventos[i] = r.data;
    pintarDetalle();
    buscar();
}

function enviarCierre(form) {
    firmarAccion('CERRAR_EVENTO', 'Evaluar y cerrar evento', `/api/eventos/${eventoAbierto.id}/cerrar/`, {
        clasificacion: form.clasificacion.value, numero_desviacion: form.numero_desviacion.value, evaluacion: form.evaluacion.value,
    });
}

function enviarAnulacion(form) {
    firmarAccion('ANULAR_EVENTO', 'Anular evento', `/api/eventos/${eventoAbierto.id}/anular/`, { motivo: form.motivo.value });
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !document.querySelector('.ev-fondo, .firma-fondo')) cerrarDetalle(); });
document.addEventListener('DOMContentLoaded', iniciar);
