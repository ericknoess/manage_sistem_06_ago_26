// gestion/static/gestion/js/proyectos.js — /proyectos/: mis tareas pendientes y tarjetas de proyectos.

let proyectos = [];
let usuarios = null;

async function iniciar() {
    await Promise.all([cargarMisTareas(), cargarProyectos()]);
}

async function cargarMisTareas() {
    const caja = document.getElementById('misTareas');
    try {
        const tareas = await G.api('/api/gestion/tareas/');
        document.getElementById('conteoMias').textContent = tareas.length ? `${tareas.length} pendiente${tareas.length === 1 ? '' : 's'}` : '';
        if (!tareas.length) { caja.innerHTML = '<div class="estado-vacio">No tienes tareas pendientes. 🎉</div>'; return; }
        const hoy = G.hoy();
        const grupos = [
            ['Vencidas', t => t.fin && G.dia(t.fin) < hoy],
            ['Esta semana', t => t.fin && G.dia(t.fin) >= hoy && G.dia(t.fin) <= hoy + 7],
            ['Después', t => t.fin && G.dia(t.fin) > hoy + 7],
            ['Sin fecha', t => !t.fin],
        ];
        caja.innerHTML = grupos.map(([titulo, filtro]) => {
            const lista = tareas.filter(filtro);
            if (!lista.length) return '';
            return `<div class="gp-grupo ${titulo === 'Vencidas' ? 'gp-grupo--vencidas' : ''}">
                <h4>${titulo} <span>${lista.length}</span></h4>
                ${lista.map(t => `
                    <a class="gp-tarea" href="/proyectos/${t.proyecto}/?tarea=${t.id}">
                        <span class="gp-tarea__punto" style="background:${escaparHtml(t.proyecto_color)}"></span>
                        <span class="gp-tarea__texto">
                            <strong>${t.es_hito ? '◆ ' : ''}${escaparHtml(t.nombre)}</strong>
                            <span class="g-sub">${escaparHtml(t.proyecto_nombre)} · ${escaparHtml(t.columna_nombre || '')}${t.avance ? ` · ${t.avance} %` : ''}</span>
                        </span>
                        <span class="gp-tarea__fecha ${t.vencida ? 'g-vencida' : ''}">${t.fin ? `${G.fechaCorta(t.fin)}<span class="g-sub">${G.cuando(t.fin)}</span>` : ''}</span>
                        <span class="g-prioridad g-prioridad--${t.prioridad.toLowerCase()}" title="Prioridad ${G.PRIORIDADES[t.prioridad]}"></span>
                    </a>`).join('')}
            </div>`;
        }).join('');
    } catch (e) {
        caja.innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
    }
}

async function cargarProyectos() {
    const ver = document.getElementById('verProyectos').value;
    const filtro = ver === 'archivados' ? '?archivados=1' : ver === 'papelera' ? '?papelera=1' : '';
    try {
        proyectos = await G.api(`/api/gestion/proyectos/${filtro}`);
        pintarProyectos();
    } catch (e) {
        document.getElementById('listaProyectos').innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
    }
}

function pintarProyectos() {
    const texto = normalizarBusqueda(document.getElementById('filtroProyecto').value);
    const lista = proyectos.filter(p => !texto || normalizarBusqueda(`${p.nombre} ${p.descripcion} ${p.responsable_nombre}`).includes(texto));
    const caja = document.getElementById('listaProyectos');
    if (document.getElementById('verProyectos').value === 'papelera') {
        caja.innerHTML = lista.length ? lista.map(p => `
            <div class="gp-proyecto gp-proyecto--papelera" style="--color:${escaparHtml(p.color)}">
                <span class="gp-proyecto__cabecera"><strong>${escaparHtml(p.nombre)}</strong></span>
                <span class="g-sub">En la papelera desde ${G.fechaHora(p.en_papelera_desde)} (lo mandó ${escaparHtml(p.en_papelera_por)}) ·
                    ${p.resumen.tareas} tareas</span>
                <span class="gp-proyecto__pie">
                    <a class="btn-secundario" href="/proyectos/${p.id}/">Ver</a>
                    ${p.puede_administrar ? `<button type="button" class="btn-primario" data-recuperar="${p.id}">Recuperar</button>
                    <button type="button" class="btn-peligro-suave" data-eliminar="${p.id}">Eliminar definitivamente</button>` : ''}
                </span>
            </div>`).join('') : '<div class="estado-vacio">La papelera está vacía.</div>';
        caja.querySelectorAll('[data-recuperar]').forEach(b => b.onclick = async () => {
            try { G.aviso((await G.api(`/api/gestion/proyectos/${b.dataset.recuperar}/recuperar/`, { metodo: 'POST' })).mensaje); }
            catch (e) { G.aviso(e.message, 'error'); }
            cargarProyectos();
        });
        caja.querySelectorAll('[data-eliminar]').forEach(b => b.onclick = async () => {
            if (!b.classList.contains('confirmar')) {
                b.classList.add('confirmar');
                b.textContent = '¿Seguro? Se borra con su historial y versiones';
                return;
            }
            try { G.aviso((await G.api(`/api/gestion/proyectos/${b.dataset.eliminar}/eliminar-definitivo/`, { metodo: 'POST' })).mensaje); }
            catch (e) { G.aviso(e.message, 'error'); }
            cargarProyectos();
        });
        return;
    }
    if (!lista.length) {
        caja.innerHTML = proyectos.length ? '<div class="estado-vacio">Ningún proyecto coincide con la búsqueda.</div>'
            : `<div class="gp-vacio"><p>Aún no participas en ningún proyecto.</p>
               <button type="button" class="btn-primario" onclick="nuevoProyecto()">+ Crear el primero</button></div>`;
        return;
    }
    caja.innerHTML = lista.map(p => {
        const r = p.resumen;
        const atraso = r.atraso > 0 ? `<span class="g-chip g-chip--mal">+${r.atraso} d vs. línea base</span>`
            : r.atraso < 0 ? `<span class="g-chip g-chip--bien">${r.atraso} d vs. línea base</span>` : '';
        const ritmo = r.avance_esperado !== null && r.avance + 5 < r.avance_esperado && p.estado === 'ACTIVO'
            ? `<span class="g-chip g-chip--mal" title="Según las fechas, a hoy debería llevar ${r.avance_esperado} %">Debería ir en ${r.avance_esperado} %</span>` : '';
        return `
        <a class="gp-proyecto" href="/proyectos/${p.id}/" style="--color:${escaparHtml(p.color)}">
            <span class="gp-proyecto__cabecera">
                <strong>${escaparHtml(p.nombre)}</strong>
                ${p.estado !== 'ACTIVO' ? `<span class="g-chip">${escaparHtml(p.estado_texto)}</span>` : ''}
            </span>
            <span class="g-sub">${escaparHtml(p.descripcion || '')}</span>
            <span class="gp-avance"><span class="gp-avance__barra"><span style="width:${r.avance}%"></span></span><strong>${r.avance} %</strong></span>
            <span class="gp-proyecto__datos">
                <span>${r.terminadas}/${r.tareas} tareas</span>
                ${r.vencidas ? `<span class="g-vencida">${r.vencidas} vencida${r.vencidas === 1 ? '' : 's'}</span>` : ''}
                ${r.fin ? `<span>Fin ${G.fechaCorta(r.fin)}</span>` : ''}
            </span>
            <span class="gp-proyecto__pie">
                <span class="g-sub">👤 ${escaparHtml(p.responsable_nombre)} · ${p.miembros} miembro${p.miembros === 1 ? '' : 's'}</span>
                <span class="gp-proyecto__chips">${atraso}${ritmo}</span>
            </span>
        </a>`;
    }).join('');
}

async function nuevoProyecto() {
    if (!usuarios) usuarios = await G.api('/api/gestion/proyectos/usuarios/').catch(() => []);
    const yo = (window.SESION && SESION.usuario) || '';
    const { caja, cerrar } = G.modal('Nuevo proyecto o tablero', `
        <form class="g-form" novalidate>
            <label class="campo campo--ancho">Nombre<input name="nombre" maxlength="200" required placeholder="Ej. Validación de limpieza del área 3"></label>
            <label class="campo campo--ancho">Descripción <small>(opcional)</small><textarea name="descripcion" rows="2"></textarea></label>
            <label class="campo">Color<input type="color" name="color" value="#2a78d6"></label>
            <div class="campo campo--ancho">Miembros <small>(pueden ver y editar sus tareas; tú quedas como responsable)</small>
                <input type="search" class="g-buscar-miembro" placeholder="🔎 Buscar persona…">
                <div class="g-miembros">${usuarios.map(u => `
                    <label class="g-check" data-nombre="${escaparHtml(normalizarBusqueda(u.nombre + ' ' + u.usuario))}">
                        <input type="checkbox" name="miembros" value="${u.id}" ${u.usuario === yo ? 'checked disabled' : ''}>
                        ${escaparHtml(u.nombre)} <span class="g-sub">${escaparHtml(u.usuario)}</span></label>`).join('')}</div>
            </div>
            <p class="g-sub campo--ancho">Se crea con las columnas Por hacer, En curso, En revisión y Hecho (las puedes cambiar después).</p>
            <div class="error-formulario campo--ancho" hidden></div>
            <div class="modal-actions campo--ancho">
                <button type="button" class="btn-secundario" data-cancelar>Cancelar</button>
                <button type="submit" class="btn-primario">Crear</button>
            </div>
        </form>`);
    const form = caja.querySelector('form');
    form.nombre.focus();
    caja.querySelector('[data-cancelar]').onclick = cerrar;
    caja.querySelector('.g-buscar-miembro').oninput = (e) => {
        const t = normalizarBusqueda(e.target.value);
        caja.querySelectorAll('.g-miembros label').forEach(l => { l.hidden = t && !l.dataset.nombre.includes(t); });
    };
    form.onsubmit = async (e) => {
        e.preventDefault();
        const error = form.querySelector('.error-formulario');
        try {
            const r = await G.api('/api/gestion/proyectos/', { metodo: 'POST', datos: {
                nombre: form.nombre.value, descripcion: form.descripcion.value, color: form.color.value,
                miembros: [...form.querySelectorAll('[name="miembros"]:checked')].map(c => Number(c.value)),
            } });
            location.href = `/proyectos/${r.id}/`;
        } catch (err) {
            error.textContent = err.message;
            error.hidden = false;
        }
    };
}

iniciar();
