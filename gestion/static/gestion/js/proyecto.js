// gestion/static/gestion/js/proyecto.js — /proyectos/<id>/: encabezado, filtros, ventana de la tarea, configuración e historial.
// Las vistas se dibujan en gantt.js (GanttOficina) y tablero.js (TableroOficina) con los datos de GET /api/gestion/proyectos/<id>/.
// Tras cada cambio se vuelve a pedir el proyecto completo (las reglas de fechas y dependencias las aplica el servidor).

const PROYECTO_ID = Number(document.body.dataset.proyecto);
let P = null;                      // proyecto con tareas calculadas
let vista = G.leer(`vista-${PROYECTO_ID}`, 'gantt');
let usuariosActivos = null;

async function cargar() {
    try {
        P = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/`);
    } catch (e) {
        document.getElementById('nombreProyecto').textContent = 'Proyecto no disponible';
        document.getElementById('vista').innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
        return false;
    }
    document.title = `${P.nombre} - Proyectos`;
    pintarCabecera();
    llenarFiltros();
    repintar();
    return true;
}

function pintarCabecera() {
    const r = P.resumen;
    // Deshacer: dice qué cambio se va a deshacer y quién lo hizo
    const boton = document.getElementById('botonDeshacer');
    const u = P.ultimo_cambio;
    boton.disabled = !(u && u.deshacible) || !!P.en_papelera_desde;
    boton.title = u ? (u.deshacible ? `Deshacer (Ctrl+Z): ${u.descripcion} — ${u.usuario}, ${G.fechaHora(u.fecha)}`
                                    : 'El último cambio es muy antiguo: usa 💾 Versiones') : 'No hay cambios para deshacer';
    const papelera = document.getElementById('avisoPapelera');
    papelera.hidden = !P.en_papelera_desde;
    if (P.en_papelera_desde) {
        papelera.innerHTML = `🗑 Este proyecto está en la papelera (lo mandó ${escaparHtml(P.en_papelera_por)} el ${G.fechaHora(P.en_papelera_desde)}).
            Se puede ver, pero no modificar.
            ${P.puede_administrar ? '<button type="button" class="btn-primario" onclick="recuperarProyecto()">Recuperar proyecto</button>' : ''}`;
    }
    document.getElementById('nombreProyecto').innerHTML = `<span class="gq-color" style="background:${escaparHtml(P.color)}"></span>${escaparHtml(P.nombre)}`
        + (P.estado !== 'ACTIVO' ? ` <span class="g-chip">${escaparHtml(P.estado_texto)}</span>` : '');
    document.getElementById('detalleProyecto').textContent = [P.descripcion, `Responsable: ${P.responsable_nombre}`,
        `${P.miembros.length} miembro${P.miembros.length === 1 ? '' : 's'}`].filter(Boolean).join(' · ');
    const tarjeta = (etiqueta, valor, sub = '', clase = '') => `
        <div class="gq-dato ${clase}"><span>${etiqueta}</span><strong>${valor}</strong>${sub ? `<small>${sub}</small>` : ''}</div>`;
    const ritmo = r.avance_esperado !== null ? `a hoy se esperaba ${r.avance_esperado} %` : '';
    document.getElementById('resumenProyecto').innerHTML = [
        tarjeta('Avance', `${r.avance} %`, ritmo, r.avance_esperado !== null && r.avance + 5 < r.avance_esperado ? 'gq-dato--mal' : ''),
        tarjeta('Tareas', `${r.terminadas}/${r.tareas}`, r.vencidas ? `${r.vencidas} vencida${r.vencidas === 1 ? '' : 's'}` : 'ninguna vencida',
                r.vencidas ? 'gq-dato--mal' : ''),
        tarjeta('Fin', G.fechaLarga(r.fin), r.base_fin ? `línea base ${G.fechaCorta(r.base_fin)}` : 'sin línea base'),
        r.atraso !== null ? tarjeta('Contra línea base', r.atraso > 0 ? `+${r.atraso} d` : r.atraso < 0 ? `${r.atraso} d` : 'A tiempo',
                                    'días hábiles', r.atraso > 0 ? 'gq-dato--mal' : 'gq-dato--bien') : '',
    ].join('');
}

function llenarFiltros() {
    const resp = document.getElementById('filtroResponsable');
    const etiq = document.getElementById('filtroEtiqueta');
    const r = resp.value, e = etiq.value;
    resp.innerHTML = '<option value="">Todos</option><option value="yo">Mis tareas</option><option value="nadie">Sin responsable</option>'
        + P.miembros.map(m => `<option value="${m.id}">${escaparHtml(m.nombre)}</option>`).join('');
    etiq.innerHTML = '<option value="">Todas las etiquetas</option>'
        + P.etiquetas.map(x => `<option value="${x.id}">${escaparHtml(x.nombre)}</option>`).join('');
    resp.value = r; etiq.value = e;
}

// Tareas que pasan los filtros (en el Gantt se agregan sus tareas resumen para no perder el árbol)
function tareasFiltradas() {
    const texto = normalizarBusqueda(document.getElementById('filtroTexto').value);
    const resp = document.getElementById('filtroResponsable').value;
    const etiq = Number(document.getElementById('filtroEtiqueta').value) || null;
    const yo = P.miembros.find(m => m.usuario === (window.SESION && SESION.usuario));
    const pasa = (t) => (!texto || normalizarBusqueda(`${t.wbs} ${t.nombre} ${t.responsable_nombre}`).includes(texto))
        && (!resp || (resp === 'yo' ? yo && t.responsable === yo.id : resp === 'nadie' ? !t.responsable : t.responsable === Number(resp)))
        && (!etiq || t.etiquetas.includes(etiq));
    const hayFiltro = texto || resp || etiq;
    if (!hayFiltro) return { tareas: P.tareas, filtrado: false };
    const ids = new Set(P.tareas.filter(t => !t.resumen && pasa(t)).map(t => t.id));
    const porId = Object.fromEntries(P.tareas.map(t => [t.id, t]));
    [...ids].forEach(id => { let p = porId[id].padre; while (p) { ids.add(p); p = porId[p].padre; } });
    return { tareas: P.tareas.filter(t => ids.has(t.id)), filtrado: true };
}

function repintar() {
    if (!P) return;
    document.querySelectorAll('.g-pestanas [data-vista]').forEach(b => b.setAttribute('aria-selected', b.dataset.vista === vista));
    document.querySelectorAll('.gq-solo-gantt').forEach(el => { el.hidden = vista !== 'gantt'; });
    const caja = document.getElementById('vista');
    const { tareas, filtrado } = tareasFiltradas();
    if (vista === 'gantt') {
        GanttOficina.pintar(caja, P, tareas, {
            escala: document.getElementById('escalaGantt').value, critica: document.getElementById('verCritica').checked,
            base: document.getElementById('verBase').checked, filtrado,
        });
    } else {
        TableroOficina.pintar(caja, P, tareas.filter(t => !t.resumen));
    }
}

function cambiarVista(nueva) {
    vista = nueva;
    G.guardar(`vista-${PROYECTO_ID}`, vista);
    repintar();
}

function cambiarEscala(escala) {
    G.guardar('escala', escala);
    repintar();
    irAHoy();
}

function irAHoy() { if (vista === 'gantt') GanttOficina.irAHoy(); }

// --- Cambios -------------------------------------------------------------------------

async function cambiarTarea(id, datos, { silencioso = false } = {}) {
    try {
        const r = await G.api(`/api/gestion/tareas/${id}/`, { metodo: 'PATCH', datos });
        if (r.movidas && r.movidas.length) {
            G.aviso(`Se recorrieron ${r.movidas.length} tarea${r.movidas.length === 1 ? '' : 's'} que dependen de esta: ${r.movidas.slice(0, 3).join(', ')}${r.movidas.length > 3 ? '…' : ''}`);
        } else if (!silencioso) {
            G.aviso('Cambios guardados.');
        }
        await cargar();
        return true;
    } catch (e) {
        G.aviso(e.message, 'error');
        await cargar();
        return false;
    }
}

async function moverTarjeta(id, columna, posicion) {
    try {
        await G.api(`/api/gestion/tareas/${id}/mover/`, { metodo: 'POST', datos: { columna, posicion } });
    } catch (e) {
        G.aviso(e.message, 'error');
    }
    await cargar();
}

async function crearTareaRapida(datos) {
    try {
        await G.api('/api/gestion/tareas/', { metodo: 'POST', datos: { proyecto: PROYECTO_ID, ...datos } });
        await cargar();
        return true;
    } catch (e) {
        G.aviso(e.message, 'error');
        return false;
    }
}

async function guardarLineaBase() {
    const previa = P.base_guardada_en ? ` Reemplaza la del ${G.fechaHora(P.base_guardada_en)}.` : '';
    const { caja, cerrar } = G.modal('Guardar línea base', `
        <p class="g-texto">Copia las fechas actuales de todas las tareas como lo planeado. Después, el Gantt muestra la barra
            planeada debajo de la real y cuántos días hábiles va atrasada cada tarea y el proyecto.${previa}</p>
        <div class="modal-actions"><button type="button" class="btn-secundario" data-no>Cancelar</button>
            <button type="button" class="btn-primario" data-si>Guardar línea base</button></div>`, { ancho: 460 });
    caja.querySelector('[data-no]').onclick = cerrar;
    caja.querySelector('[data-si]').onclick = async () => {
        try {
            const r = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/linea-base/`, { metodo: 'POST' });
            cerrar();
            G.aviso(r.mensaje);
            document.getElementById('verBase').checked = true;
            await cargar();
        } catch (e) { G.aviso(e.message, 'error'); }
    };
}

// --- Ventana de la tarea ---------------------------------------------------------------

function opcionesPadre(tarea) {
    // Cualquier tarea que no sea ella misma ni una de sus descendientes
    const prohibidas = new Set();
    if (tarea) {
        prohibidas.add(tarea.id);
        let cambio = true;
        while (cambio) {
            cambio = false;
            P.tareas.forEach(t => { if (t.padre && prohibidas.has(t.padre) && !prohibidas.has(t.id)) { prohibidas.add(t.id); cambio = true; } });
        }
    }
    return P.tareas.filter(t => !prohibidas.has(t.id));
}

async function abrirTarea(id, valores = {}) {
    const t = id ? P.tareas.find(x => x.id === id) : null;
    if (id && !t) return;
    const detalle = t ? await G.api(`/api/gestion/tareas/${id}/`).catch(() => null) : null;
    const v = t || { nombre: '', descripcion: '', responsable: null, prioridad: 'MEDIA', columna: null, padre: null, inicio: null,
                     fin: null, es_hito: false, avance: 0, etiquetas: [], resumen: false, ...valores };
    const resumen = v.resumen;
    const opcion = (valor, texto, actual) => `<option value="${valor}" ${String(actual ?? '') === String(valor) ? 'selected' : ''}>${escaparHtml(texto)}</option>`;
    const html = `
        <form class="g-form gq-tarea" novalidate>
            <label class="campo campo--ancho">Nombre<input name="nombre" maxlength="200" value="${escaparHtml(v.nombre)}" required></label>
            <label class="campo campo--ancho">Descripción<textarea name="descripcion" rows="3">${escaparHtml(v.descripcion)}</textarea></label>
            <label class="campo">Responsable<select name="responsable">${opcion('', 'Sin responsable', v.responsable)}
                ${P.miembros.map(m => opcion(m.id, m.nombre, v.responsable)).join('')}</select></label>
            <label class="campo">Prioridad<select name="prioridad">${Object.entries(G.PRIORIDADES).map(([k, n]) => opcion(k, n, v.prioridad)).join('')}</select></label>
            <label class="campo">Dentro de <small>(tarea resumen)</small><select name="padre">${opcion('', '— Ninguna (nivel principal) —', v.padre)}
                ${opcionesPadre(t).map(x => opcion(x.id, `${x.wbs} ${x.nombre}`, v.padre)).join('')}</select></label>
            <label class="campo">Columna del tablero<select name="columna" ${resumen ? 'disabled' : ''}>
                ${resumen ? '<option>— (tarea resumen) —</option>' : P.columnas.map(c => opcion(c.id, c.nombre, v.columna)).join('')}</select></label>
            <label class="campo">Inicio<input type="date" name="inicio" value="${v.inicio || ''}" ${resumen ? 'disabled' : ''}></label>
            <label class="campo">Fin<input type="date" name="fin" value="${v.fin || ''}" ${resumen ? 'disabled' : ''}></label>
            <label class="g-check campo--ancho"><input type="checkbox" name="es_hito" ${v.es_hito ? 'checked' : ''} ${resumen ? 'disabled' : ''}>
                ◆ Es un hito (un momento, sin duración: entrega, aprobación…)</label>
            <div class="campo campo--ancho">Avance <small>${resumen ? '(sale de sus subtareas)' : '(100 % la manda a la columna final)'}</small>
                <div class="gq-avance"><input type="range" name="avance" min="0" max="100" step="5" value="${v.avance}" ${resumen ? 'disabled' : ''}>
                    <output>${v.avance} %</output></div></div>
            <div class="campo campo--ancho">Etiquetas <div class="gq-etiquetas">${P.etiquetas.length ? P.etiquetas.map(e => `
                <label class="gq-etiqueta" style="--color:${escaparHtml(e.color)}"><input type="checkbox" name="etiquetas" value="${e.id}"
                    ${v.etiquetas.includes(e.id) ? 'checked' : ''}>${escaparHtml(e.nombre)}</label>`).join('')
                : '<span class="g-sub">Sin etiquetas: créalas en ⚙ Configurar.</span>'}</div></div>
            <p class="g-sub campo--ancho" id="duracionTarea"></p>
            <div class="error-formulario campo--ancho" hidden></div>
            <div class="modal-actions campo--ancho">
                ${t ? '<button type="button" class="btn-peligro-suave" data-borrar>Borrar</button><span class="gq-espacio"></span>' : ''}
                <button type="button" class="btn-secundario" data-cancelar>Cancelar</button>
                <button type="submit" class="btn-primario">${t ? 'Guardar' : 'Crear tarea'}</button>
            </div>
        </form>
        ${t ? htmlExtrasTarea(t, detalle) : ''}`;
    const { caja, cerrar } = G.modal(t ? `${t.wbs} · ${t.nombre}` : 'Nueva tarea', html, { ancho: 760 });
    const form = caja.querySelector('form');
    const error = form.querySelector('.error-formulario');
    const salida = form.querySelector('output');
    form.avance.oninput = () => { salida.textContent = `${form.avance.value} %`; };
    const duracion = () => {
        const i = G.dia(form.inicio.value), f = G.dia(form.fin.value);
        let n = 0;
        if (i !== null && f !== null && f >= i) for (let d = i; d <= f; d++) if (G.esHabil(d)) n++;
        form.querySelector('#duracionTarea').textContent = form.es_hito.checked ? 'Hito: sin duración.'
            : n ? `Duración: ${n} día${n === 1 ? '' : 's'} hábil${n === 1 ? '' : 'es'} (lunes a viernes).` : '';
    };
    form.inicio.onchange = () => {
        // Al mover el inicio se conserva la duración, como en el Gantt
        if (t && t.inicio && t.fin && form.fin.value === t.fin && form.inicio.value) {
            const delta = G.dia(form.inicio.value) - G.dia(t.inicio);
            form.fin.value = G.texto(G.dia(t.fin) + delta);
        } else if (!form.fin.value || form.fin.value < form.inicio.value) {
            form.fin.value = form.inicio.value;
        }
        duracion();
    };
    form.fin.onchange = duracion;
    form.es_hito.onchange = () => { if (form.es_hito.checked && form.inicio.value) form.fin.value = form.inicio.value; duracion(); };
    duracion();
    form.querySelector('[data-cancelar]').onclick = cerrar;
    if (!t) form.nombre.focus();

    const borrar = form.querySelector('[data-borrar]');
    if (borrar) {
        borrar.onclick = async () => {
            if (!borrar.classList.contains('confirmar')) {
                borrar.classList.add('confirmar');
                borrar.textContent = t.resumen ? '¿Borrar con sus subtareas?' : '¿Seguro? Borrar';
                return;
            }
            try {
                await G.api(`/api/gestion/tareas/${t.id}/`, { metodo: 'DELETE' });
                cerrar();
                G.aviso('Tarea borrada.');
                await cargar();
            } catch (e) { error.textContent = e.message; error.hidden = false; }
        };
    }

    form.onsubmit = async (e) => {
        e.preventDefault();
        error.hidden = true;
        const datos = {
            nombre: form.nombre.value, descripcion: form.descripcion.value, responsable: form.responsable.value || null,
            prioridad: form.prioridad.value, padre: form.padre.value || null,
            etiquetas: [...form.querySelectorAll('[name="etiquetas"]:checked')].map(c => Number(c.value)),
        };
        if (!resumen) {
            Object.assign(datos, { inicio: form.inicio.value || null, fin: form.fin.value || null, es_hito: form.es_hito.checked,
                                   avance: Number(form.avance.value) });
        }
        try {
            if (t) {
                // Solo lo que cambió (así no se recalculan fechas ni avance sin necesidad)
                const cambios = {};
                Object.entries(datos).forEach(([k, val]) => {
                    const antes = k === 'etiquetas' ? JSON.stringify([...t.etiquetas].sort()) : (t[k] ?? null);
                    const ahora = k === 'etiquetas' ? JSON.stringify([...val].sort()) : (val === '' ? null : val);
                    if (String(antes) !== String(ahora ?? null)) cambios[k] = val;
                });
                if (!resumen && form.columna.value && Number(form.columna.value) !== t.columna) {
                    await G.api(`/api/gestion/tareas/${t.id}/mover/`, { metodo: 'POST', datos: { columna: Number(form.columna.value) } });
                }
                if (Object.keys(cambios).length) {
                    const r = await G.api(`/api/gestion/tareas/${t.id}/`, { metodo: 'PATCH', datos: cambios });
                    if (r.movidas.length) G.aviso(`Se recorrieron ${r.movidas.length} tarea${r.movidas.length === 1 ? '' : 's'} que dependen de esta.`);
                }
            } else {
                await G.api('/api/gestion/tareas/', { metodo: 'POST', datos: { proyecto: PROYECTO_ID, columna: form.columna.value || null, ...datos } });
            }
            cerrar();
            await cargar();
        } catch (err) {
            error.textContent = err.message;
            error.hidden = false;
        }
    };
    if (t) conectarExtrasTarea(caja, t, cerrar);
}

function htmlExtrasTarea(t, d) {
    if (!d) return '<div class="estado-vacio">No se pudo cargar el detalle de la tarea.</div>';
    const candidatas = P.tareas.filter(x => !x.resumen && x.id !== t.id && !d.predecesoras.some(p => p.tarea === x.id));
    const desfase = (n) => n ? ` (${n > 0 ? '+' : ''}${n} d)` : '';
    return `
        <section class="gq-seccion">
            <h4>🔗 Depende de <small>(fin a inicio: empieza el día hábil siguiente a que terminan)</small></h4>
            ${t.resumen ? '<p class="g-sub">Una tarea resumen no lleva dependencias: ponlas en sus subtareas.</p>' : `
            <ul class="gq-lista">${d.predecesoras.map(p => `<li>${escaparHtml(p.nombre)}${desfase(p.desfase_dias)}
                <button type="button" class="btn-icono" data-quitar-dep="${p.id}" title="Quitar dependencia">✕</button></li>`).join('')
                || '<li class="g-sub">Ninguna.</li>'}</ul>
            <div class="gq-agregar">
                <select data-nueva-dep><option value="">Agregar predecesora…</option>
                    ${candidatas.map(x => `<option value="${x.id}">${escaparHtml(`${x.wbs} ${x.nombre}`)}</option>`).join('')}</select>
                <input type="number" data-desfase value="0" step="1" title="Días hábiles de espera (+) o de traslape (−)" aria-label="Desfase en días">
                <button type="button" class="btn-secundario" data-agregar-dep>Agregar</button>
            </div>`}
            ${d.sucesoras.length ? `<p class="g-sub">La esperan: ${d.sucesoras.map(s => escaparHtml(s.nombre)).join(', ')}.</p>` : ''}
        </section>
        <section class="gq-seccion">
            <h4>☑️ Checklist ${d.checklist.length ? `<small>${d.checklist.filter(c => c.hecho).length}/${d.checklist.length}</small>` : ''}</h4>
            <ul class="gq-lista gq-checklist">${d.checklist.map(c => `<li>
                <label class="g-check"><input type="checkbox" data-check="${c.id}" ${c.hecho ? 'checked' : ''}>
                    <span class="${c.hecho ? 'gq-hecho' : ''}">${escaparHtml(c.texto)}</span></label>
                <button type="button" class="btn-icono" data-borrar-check="${c.id}" title="Quitar">✕</button></li>`).join('')}</ul>
            <div class="gq-agregar"><input type="text" data-nuevo-check maxlength="300" placeholder="Agregar elemento y Enter…"></div>
        </section>
        <section class="gq-seccion">
            <h4>💬 Comentarios</h4>
            <ul class="gq-comentarios">${d.comentarios.map(c => `<li><strong>${escaparHtml(c.autor)}</strong>
                <span class="g-sub">${G.fechaHora(c.fecha)}</span><p>${escaparHtml(c.texto)}</p></li>`).join('') || '<li class="g-sub">Sin comentarios.</li>'}</ul>
            <div class="gq-agregar gq-agregar--comentario"><textarea data-nuevo-comentario rows="2" placeholder="Escribe un comentario…"></textarea>
                <button type="button" class="btn-secundario" data-comentar>Comentar</button></div>
        </section>
        <details class="gq-seccion"><summary><h4>🕘 Historial</h4></summary>
            <ul class="gq-historial">${d.historial.map(h => `<li class="${h.deshecho ? 'gq-deshecho' : ''}"><span class="g-sub">${G.fechaHora(h.fecha)} · <strong>${escaparHtml(h.usuario)}</strong>${h.deshecho ? ' · <em>deshecho</em>' : ''}</span>
                ${escaparHtml(h.descripcion)}${htmlCambios(h.cambios)}</li>`).join('') || '<li class="g-sub">Sin cambios registrados.</li>'}</ul>
        </details>`;
}

const NOMBRES_CAMPO = { nombre: 'Nombre', descripcion: 'Descripción', responsable: 'Responsable', prioridad: 'Prioridad', inicio: 'Inicio',
                        fin: 'Fin', avance: 'Avance', es_hito: 'Hito', padre: 'Dentro de', columna: 'Columna', etiquetas: 'Etiquetas',
                        estado: 'Estado', miembros: 'Miembros', color: 'Color' };
function htmlCambios(cambios) {
    const filas = Object.entries(cambios || {}).map(([k, [a, b]]) => `${NOMBRES_CAMPO[k] || k}: ${escaparHtml(a ?? '—')} → ${escaparHtml(b ?? '—')}`);
    return filas.length ? `<span class="g-sub gq-cambios">${filas.join(' · ')}</span>` : '';
}

function conectarExtrasTarea(caja, t, cerrar) {
    const recargar = async () => { cerrar(); await cargar(); abrirTarea(t.id); };
    const intentar = (fn) => async (...args) => { try { await fn(...args); } catch (e) { G.aviso(e.message, 'error'); } };
    caja.querySelectorAll('[data-quitar-dep]').forEach(b => b.onclick = intentar(async () => {
        await G.api(`/api/gestion/dependencias/${b.dataset.quitarDep}/`, { metodo: 'DELETE' }); await recargar();
    }));
    const agregar = caja.querySelector('[data-agregar-dep]');
    if (agregar) agregar.onclick = intentar(async () => {
        const pred = caja.querySelector('[data-nueva-dep]').value;
        if (!pred) return;
        const r = await G.api(`/api/gestion/tareas/${t.id}/dependencias/`, { metodo: 'POST', datos: {
            predecesora: Number(pred), desfase_dias: Number(caja.querySelector('[data-desfase]').value) || 0 } });
        if (r.movidas.length) G.aviso(`Se recorrieron ${r.movidas.length} tarea${r.movidas.length === 1 ? '' : 's'} para respetar la dependencia.`);
        await recargar();
    });
    caja.querySelectorAll('[data-check]').forEach(c => c.onchange = intentar(async () => {
        await G.api(`/api/gestion/checklist/${c.dataset.check}/`, { metodo: 'PATCH', datos: { hecho: c.checked } });
        c.nextElementSibling.classList.toggle('gq-hecho', c.checked);
        await cargar();
    }));
    caja.querySelectorAll('[data-borrar-check]').forEach(b => b.onclick = intentar(async () => {
        await G.api(`/api/gestion/checklist/${b.dataset.borrarCheck}/`, { metodo: 'DELETE' }); await recargar();
    }));
    const nuevo = caja.querySelector('[data-nuevo-check]');
    nuevo.onkeydown = intentar(async (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        if (!nuevo.value.trim()) return;
        await G.api(`/api/gestion/tareas/${t.id}/checklist/`, { metodo: 'POST', datos: { texto: nuevo.value } });
        await recargar();
    });
    caja.querySelector('[data-comentar]').onclick = intentar(async () => {
        const texto = caja.querySelector('[data-nuevo-comentario]').value;
        if (!texto.trim()) return;
        await G.api(`/api/gestion/tareas/${t.id}/comentarios/`, { metodo: 'POST', datos: { texto } });
        await recargar();
    });
}

// --- Configuración del proyecto ------------------------------------------------------------

async function configurar() {
    if (!usuariosActivos) usuariosActivos = await G.api('/api/gestion/proyectos/usuarios/').catch(() => []);
    const admin = P.puede_administrar;
    const bloqueo = admin ? '' : 'disabled';
    const miembros = new Set(P.miembros.map(m => m.id));
    const estados = { ACTIVO: 'Activo', PAUSADO: 'En pausa', TERMINADO: 'Terminado', ARCHIVADO: 'Archivado' };
    const { caja, cerrar } = G.modal('Configurar proyecto', `
        ${admin ? '' : '<p class="g-aviso-linea">Solo el responsable del proyecto o un administrador cambia sus datos, miembros y columnas. Las etiquetas las puede editar cualquier miembro.</p>'}
        <form class="g-form" data-proyecto novalidate>
            <label class="campo campo--ancho">Nombre<input name="nombre" value="${escaparHtml(P.nombre)}" ${bloqueo}></label>
            <label class="campo campo--ancho">Descripción<textarea name="descripcion" rows="2" ${bloqueo}>${escaparHtml(P.descripcion)}</textarea></label>
            <label class="campo">Estado<select name="estado" ${bloqueo}>${Object.entries(estados).map(([k, n]) =>
                `<option value="${k}" ${P.estado === k ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
            <label class="campo">Color<input type="color" name="color" value="${escaparHtml(P.color)}" ${bloqueo}></label>
            <label class="campo campo--ancho">Responsable<select name="responsable" ${bloqueo}>${usuariosActivos.map(u =>
                `<option value="${u.id}" ${u.id === P.responsable ? 'selected' : ''}>${escaparHtml(u.nombre)}</option>`).join('')}</select></label>
            <div class="campo campo--ancho">Miembros
                <input type="search" class="g-buscar-miembro" placeholder="🔎 Buscar persona…" ${bloqueo}>
                <div class="g-miembros">${usuariosActivos.map(u => `
                    <label class="g-check" data-nombre="${escaparHtml(normalizarBusqueda(u.nombre + ' ' + u.usuario))}">
                        <input type="checkbox" name="miembros" value="${u.id}" ${miembros.has(u.id) ? 'checked' : ''} ${bloqueo}>
                        ${escaparHtml(u.nombre)} <span class="g-sub">${escaparHtml(u.usuario)}</span></label>`).join('')}</div>
            </div>
            ${admin ? `<div class="modal-actions campo--ancho"><button type="button" class="btn-peligro-suave" data-borrar-proyecto>🗑 Mandar a la papelera</button>
                <span class="gq-espacio"></span><button type="submit" class="btn-primario">Guardar datos</button></div>` : ''}
        </form>
        <section class="gq-seccion">
            <h4>🗂️ Columnas del tablero <small>(una final = terminada)</small></h4>
            <ul class="gq-lista gq-columnas">${P.columnas.map((c, i) => `<li data-columna="${c.id}">
                <input type="text" value="${escaparHtml(c.nombre)}" data-campo="nombre" maxlength="60" ${bloqueo} aria-label="Nombre de la columna">
                <label class="g-check" title="Las tarjetas aquí cuentan como terminadas"><input type="checkbox" data-campo="es_final" ${c.es_final ? 'checked' : ''} ${bloqueo}> Final</label>
                <input type="number" min="0" placeholder="Sin límite" value="${c.limite ?? ''}" data-campo="limite" title="Máximo de tarjetas (límite WIP)" ${bloqueo}>
                ${admin ? `<button type="button" class="btn-icono" data-subir ${i === 0 ? 'disabled' : ''} title="Mover a la izquierda">◀</button>
                <button type="button" class="btn-icono" data-bajar ${i === P.columnas.length - 1 ? 'disabled' : ''} title="Mover a la derecha">▶</button>
                <button type="button" class="btn-icono" data-borrar-columna title="Borrar (sus tarjetas pasan a la columna anterior)">🗑</button>` : ''}
            </li>`).join('')}</ul>
            ${admin ? '<div class="gq-agregar"><input type="text" data-nueva-columna maxlength="60" placeholder="Nueva columna y Enter…"></div>' : ''}
        </section>
        <section class="gq-seccion">
            <h4>🏷️ Etiquetas</h4>
            <ul class="gq-lista gq-etiquetas-config">${P.etiquetas.map(e => `<li data-etiqueta="${e.id}">
                <input type="color" value="${escaparHtml(e.color)}" data-campo="color" aria-label="Color">
                <input type="text" value="${escaparHtml(e.nombre)}" data-campo="nombre" maxlength="40" aria-label="Nombre de la etiqueta">
                <button type="button" class="btn-icono" data-borrar-etiqueta title="Borrar etiqueta">🗑</button></li>`).join('') || '<li class="g-sub">Sin etiquetas.</li>'}</ul>
            <div class="gq-agregar"><input type="color" data-color-etiqueta value="#8b5cf6" aria-label="Color">
                <input type="text" data-nueva-etiqueta maxlength="40" placeholder="Nueva etiqueta y Enter…"></div>
        </section>`, { ancho: 720 });

    const intentar = (fn) => async (...a) => { try { await fn(...a); } catch (e) { G.aviso(e.message, 'error'); } };
    const reabrir = async () => { cerrar(); await cargar(); configurar(); };
    const form = caja.querySelector('[data-proyecto]');
    caja.querySelector('.g-buscar-miembro').oninput = (e) => {
        const t = normalizarBusqueda(e.target.value);
        caja.querySelectorAll('.g-miembros label').forEach(l => { l.hidden = t && !l.dataset.nombre.includes(t); });
    };
    form.onsubmit = intentar(async (e) => {
        e.preventDefault();
        await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/`, { metodo: 'PATCH', datos: {
            nombre: form.nombre.value, descripcion: form.descripcion.value, estado: form.estado.value, color: form.color.value,
            responsable: Number(form.responsable.value),
            miembros: [...form.querySelectorAll('[name="miembros"]:checked')].map(c => Number(c.value)) } });
        G.aviso('Proyecto actualizado.');
        await reabrir();
    });
    const borrarProyecto = caja.querySelector('[data-borrar-proyecto]');
    if (borrarProyecto) borrarProyecto.onclick = intentar(async () => {
        if (!borrarProyecto.classList.contains('confirmar')) {
            borrarProyecto.classList.add('confirmar');
            borrarProyecto.textContent = `¿Mandar «${P.nombre}» a la papelera? Se puede recuperar`;
            return;
        }
        await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/`, { metodo: 'DELETE' });
        location.href = '/proyectos/';
    });

    // Columnas: cada cambio se guarda al salir del campo
    caja.querySelectorAll('[data-columna]').forEach((li, i) => {
        const id = li.dataset.columna;
        li.querySelectorAll('[data-campo]').forEach(campo => campo.onchange = intentar(async () => {
            const valor = campo.type === 'checkbox' ? campo.checked : campo.value;
            await G.api(`/api/gestion/columnas/${id}/`, { metodo: 'PATCH', datos: { [campo.dataset.campo]: valor } });
            await cargar();
        }));
        const mover = (destino) => intentar(async () => {
            await G.api(`/api/gestion/columnas/${id}/`, { metodo: 'PATCH', datos: { posicion: destino } });
            await reabrir();
        });
        const subir = li.querySelector('[data-subir]'), bajar = li.querySelector('[data-bajar]'), borrar = li.querySelector('[data-borrar-columna]');
        if (subir) subir.onclick = mover(i - 1);
        if (bajar) bajar.onclick = mover(i + 1);
        if (borrar) borrar.onclick = intentar(async () => {
            await G.api(`/api/gestion/columnas/${id}/`, { metodo: 'DELETE' });
            await reabrir();
        });
    });
    const nuevaColumna = caja.querySelector('[data-nueva-columna]');
    if (nuevaColumna) nuevaColumna.onkeydown = intentar(async (e) => {
        if (e.key !== 'Enter' || !nuevaColumna.value.trim()) return;
        e.preventDefault();
        // Antes de la columna final, que suele ser la última
        const finales = P.columnas.filter(c => c.es_final).length;
        await G.api('/api/gestion/columnas/', { metodo: 'POST', datos: { proyecto: PROYECTO_ID, nombre: nuevaColumna.value,
                                                                      posicion: P.columnas.length - finales } });
        await reabrir();
    });

    // Etiquetas
    caja.querySelectorAll('[data-etiqueta]').forEach(li => {
        const id = li.dataset.etiqueta;
        li.querySelectorAll('[data-campo]').forEach(campo => campo.onchange = intentar(async () => {
            await G.api(`/api/gestion/etiquetas/${id}/`, { metodo: 'PATCH', datos: { [campo.dataset.campo]: campo.value } });
            await cargar();
        }));
        li.querySelector('[data-borrar-etiqueta]').onclick = intentar(async () => {
            await G.api(`/api/gestion/etiquetas/${id}/`, { metodo: 'DELETE' });
            await reabrir();
        });
    });
    const nuevaEtiqueta = caja.querySelector('[data-nueva-etiqueta]');
    nuevaEtiqueta.onkeydown = intentar(async (e) => {
        if (e.key !== 'Enter' || !nuevaEtiqueta.value.trim()) return;
        e.preventDefault();
        await G.api('/api/gestion/etiquetas/', { metodo: 'POST', datos: { proyecto: PROYECTO_ID, nombre: nuevaEtiqueta.value,
                                                                       color: caja.querySelector('[data-color-etiqueta]').value } });
        await reabrir();
    });
}

// --- Deshacer, historial y versiones -------------------------------------------------------

async function deshacerUltimo() {
    if (!P.ultimo_cambio || !P.ultimo_cambio.deshacible) return;
    const boton = document.getElementById('botonDeshacer');
    boton.disabled = true;
    try {
        const r = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/deshacer/`, { metodo: 'POST' });
        G.aviso(`↶ ${r.mensaje}`);
    } catch (e) { G.aviso(e.message, 'error'); }
    await cargar();
}

async function recuperarProyecto() {
    try {
        const r = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/recuperar/`, { metodo: 'POST' });
        G.aviso(r.mensaje);
    } catch (e) { G.aviso(e.message, 'error'); }
    await cargar();
}

// Ctrl+Z / Cmd+Z deshace (salvo mientras se escribe en un campo)
document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.key.toLowerCase() !== 'z') return;
    if (e.target.closest('input, textarea, select, [contenteditable]') || document.querySelector('.g-fondo')) return;
    e.preventDefault();
    deshacerUltimo();
});

// Botón de dos pasos (evita confirm(), que bloquea la página)
function dosPasos(boton, texto, accion) {
    boton.onclick = async () => {
        if (!boton.classList.contains('confirmar')) {
            boton.classList.add('confirmar');
            boton.dataset.original = boton.textContent;
            boton.textContent = texto;
            setTimeout(() => { if (boton.isConnected && boton.classList.contains('confirmar')) {
                boton.classList.remove('confirmar'); boton.textContent = boton.dataset.original; } }, 5000);
            return;
        }
        boton.disabled = true;
        await accion();
    };
}

const ICONO_TIPO = { CAMBIO: '✏️', DESHACER: '↶', RESTAURAR: '⏪' };

async function verHistorial() {
    const { caja, cerrar } = G.modal('Historial de cambios', '<div class="estado-vacio">Cargando…</div>', { ancho: 760 });
    let historial;
    try {
        historial = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/historial/`);
    } catch (e) {
        caja.innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
        return;
    }
    const personas = [...new Set(historial.map(h => h.usuario))].sort();
    caja.innerHTML = `
        <p class="g-sub">Cada cambio guarda quién lo hizo y cuándo. «Regresar aquí» deja el proyecto como estaba justo antes de ese
            cambio (deshace también los posteriores); el estado actual se guarda antes como versión, así que no se pierde nada.</p>
        <div class="gq-filtros-historial">
            <select data-persona aria-label="Persona"><option value="">Todas las personas</option>
                ${personas.map(p => `<option>${escaparHtml(p)}</option>`).join('')}</select>
            <input type="search" data-texto placeholder="🔎 Buscar en el historial…">
        </div>
        <ul class="gq-historial gq-historial--completo"></ul>`;
    const lista = caja.querySelector('ul');
    const pintar = () => {
        const persona = caja.querySelector('[data-persona]').value;
        const texto = normalizarBusqueda(caja.querySelector('[data-texto]').value);
        const filas = historial.filter(h => (!persona || h.usuario === persona)
            && (!texto || normalizarBusqueda(`${h.descripcion} ${h.tarea_nombre} ${JSON.stringify(h.cambios)}`).includes(texto)));
        lista.innerHTML = filas.map(h => `
            <li class="${h.deshecho ? 'gq-deshecho' : ''}">
                <span class="gq-historial__icono" title="${h.tipo === 'CAMBIO' ? 'Cambio' : h.tipo === 'DESHACER' ? 'Deshacer' : 'Restauración'}">${ICONO_TIPO[h.tipo] || '•'}</span>
                <span class="gq-historial__texto">
                    <span class="g-sub"><strong>${escaparHtml(h.usuario)}</strong> · ${G.fechaHora(h.fecha)}${h.deshecho ? ' · <em>deshecho</em>' : ''}</span>
                    ${h.tarea ? `<a href="#" data-tarea="${h.tarea}">${escaparHtml(h.descripcion)}</a>` : escaparHtml(h.descripcion)}${htmlCambios(h.cambios)}
                </span>
                ${h.puede_regresar && !P.en_papelera_desde ? `<button type="button" class="btn-secundario gq-regresar" data-regresar="${h.id}"
                    title="Dejar el proyecto como estaba antes de este cambio">⏪ Regresar aquí</button>` : ''}
            </li>`).join('') || '<li class="g-sub">Sin cambios con esos filtros.</li>';
        lista.querySelectorAll('[data-tarea]').forEach(a => a.onclick = (e) => { e.preventDefault(); abrirTarea(Number(a.dataset.tarea)); });
        lista.querySelectorAll('[data-regresar]').forEach(b => dosPasos(b, '¿Regresar a antes de esto?', async () => {
            try {
                const r = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/regresar/`, { metodo: 'POST', datos: { historial: Number(b.dataset.regresar) } });
                cerrar();
                G.aviso(r.mensaje);
                await cargar();
            } catch (e) { G.aviso(e.message, 'error'); b.disabled = false; }
        }));
    };
    caja.querySelector('[data-persona]').onchange = pintar;
    caja.querySelector('[data-texto]').oninput = pintar;
    pintar();
}

async function verVersiones() {
    const { caja, cerrar } = G.modal('Versiones del proyecto', '<div class="estado-vacio">Cargando…</div>', { ancho: 720 });
    const pintar = async () => {
        let versiones;
        try {
            versiones = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/versiones/`);
        } catch (e) {
            caja.innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
            return;
        }
        caja.innerHTML = `
            <p class="g-sub">Una versión es una copia completa del proyecto (tareas, fechas, columnas, dependencias, checklist y comentarios).
                El sistema guarda un respaldo automático cada día que hay cambios y otro antes de cada restauración.</p>
            ${P.en_papelera_desde ? '' : `<form class="gq-agregar" data-guardar>
                <input type="text" name="nombre" maxlength="200" placeholder="Nombre de la versión (ej. Plan aprobado por Calidad)">
                <button type="submit" class="btn-primario">💾 Guardar versión</button></form>`}
            <ul class="gq-versiones">${versiones.map(v => `
                <li class="${v.automatica ? 'gq-version--auto' : ''}">
                    <span class="gq-version__num">v${v.numero}</span>
                    <span class="gq-version__texto"><strong>${escaparHtml(v.nombre)}</strong>
                        ${v.automatica ? '<span class="g-chip">automática</span>' : ''}
                        <span class="g-sub">${escaparHtml(v.creado_por)} · ${G.fechaHora(v.creado_en)} · ${v.resumen.tareas ?? '—'} tareas,
                            ${v.resumen.terminadas ?? 0} terminadas</span></span>
                    ${P.en_papelera_desde ? '' : `<button type="button" class="btn-secundario" data-restaurar="${v.id}">Restaurar</button>`}
                </li>`).join('') || '<li class="g-sub">Aún no hay versiones guardadas.</li>'}</ul>`;
        const form = caja.querySelector('[data-guardar]');
        if (form) form.onsubmit = async (e) => {
            e.preventDefault();
            try {
                const r = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/versiones/`, { metodo: 'POST', datos: { nombre: form.nombre.value } });
                G.aviso(r.mensaje);
                await cargar();
                await pintar();
            } catch (err) { G.aviso(err.message, 'error'); }
        };
        caja.querySelectorAll('[data-restaurar]').forEach(b => dosPasos(b, '¿Restaurar? (lo actual se guarda antes)', async () => {
            try {
                const r = await G.api(`/api/gestion/proyectos/${PROYECTO_ID}/restaurar-version/`, { metodo: 'POST', datos: { version: Number(b.dataset.restaurar) } });
                cerrar();
                G.aviso(r.mensaje);
                await cargar();
            } catch (e) { G.aviso(e.message, 'error'); b.disabled = false; }
        }));
    };
    await pintar();
}

(async () => {
    document.getElementById('escalaGantt').value = G.leer('escala', 'semana');
    document.getElementById('verBase').checked = G.leer('ver-base', false);
    document.getElementById('verCritica').checked = G.leer('ver-critica', false);
    document.getElementById('verBase').addEventListener('change', (e) => G.guardar('ver-base', e.target.checked));
    document.getElementById('verCritica').addEventListener('change', (e) => G.guardar('ver-critica', e.target.checked));
    if (await cargar()) {
        if (vista === 'gantt') GanttOficina.irAHoy();
        const tarea = new URLSearchParams(location.search).get('tarea');
        if (tarea) abrirTarea(Number(tarea));
    }
})();
