// static/core/js/eventos.js — Formulario compartido para reportar un evento GMP (web y tablet).
//
//   abrirReporteEvento({ lote: 12, loteNombre: 'L-001', fase: 345, faseNombre: '[T2] Incubación',
//                        alGuardar: (evento) => {...} });
//   Sin `lote` ni `fase`, el formulario deja elegir el lote (y luego la tarea). Con `fase`, el lote se deduce.
//
// Pide tipo, título, descripción, acción inmediata, hora en que ocurrió y, opcional, la tarea y el equipo.
// POST /api/eventos/ (lo puede hacer cualquier persona con sesión: usuario web u operador con su PIN).
// Estilos en static/core/css/eventos.css (propios: funciona igual en las pantallas web y en la tablet).

(function () {
    const esc = (t) => { const d = document.createElement('div'); d.textContent = t ?? ''; return d.innerHTML; };
    const cookie = (nombre) => {
        const par = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith(`${nombre}=`));
        return par ? decodeURIComponent(par.slice(nombre.length + 1)) : '';
    };
    const ahoraLocal = () => {
        const d = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
        return d.toISOString().slice(0, 16);
    };
    let opciones = null;

    async function cargarOpciones() {
        if (opciones) return opciones;
        const res = await fetch('/api/eventos/opciones/');
        if (!res.ok) throw new Error('No se pudieron cargar los tipos de evento.');
        opciones = await res.json();
        return opciones;
    }

    async function lotesAbiertos() {
        const res = await fetch('/api/lotes/');
        if (!res.ok) return [];
        const lotes = await res.json();
        return (Array.isArray(lotes) ? lotes : lotes.results || []).filter(l => !l.archivado)
            .sort((a, b) => (['EN_PROGRESO', 'DESVIACION'].includes(b.estado) - ['EN_PROGRESO', 'DESVIACION'].includes(a.estado))
                || String(b.identificador_lote).localeCompare(String(a.identificador_lote)));
    }

    async function tareasDelLote(loteId) {
        const res = await fetch(`/api/fases-lote/?lote=${loteId}`);
        if (!res.ok) return [];
        const fases = await res.json();
        // Primero las que están en curso; luego las completadas y las pendientes más cercanas
        const orden = { EN_PROGRESO: 0, COMPLETADA: 1, PENDIENTE: 2, OMITIDA: 3 };
        return fases.sort((a, b) => (orden[a.estado] - orden[b.estado])
            || (new Date(b.inicio_programado) - new Date(a.inicio_programado)) * (a.estado === 'PENDIENTE' ? -1 : 1)).slice(0, 300);
    }

    async function equipos() {
        try {
            const res = await fetch('/api/equipos/');
            if (!res.ok) return [];
            const lista = await res.json();
            return (Array.isArray(lista) ? lista : lista.results || []).filter(e => e.activo !== false);
        } catch (e) { return []; }
    }

    const nombreTarea = (f) => `[${f.operacion_id_paso || ''}] ${f.operacion_nombre || 'Tarea'}`;

    window.abrirReporteEvento = async function ({ lote = null, loteNombre = '', fase = null, faseNombre = '', alGuardar = null } = {}) {
        let datos;
        try { datos = await cargarOpciones(); } catch (e) { alert(e.message); return; }

        const fondo = document.createElement('div');
        fondo.className = 'ev-fondo';
        fondo.innerHTML = `
            <form class="ev-modal" role="dialog" aria-modal="true" aria-labelledby="evTitulo" novalidate>
                <header class="ev-modal__cabecera">
                    <h3 id="evTitulo">⚠️ Reportar evento GMP</h3>
                    <button type="button" class="ev-cerrar" data-cerrar title="Cancelar">✕</button>
                </header>
                <p class="ev-ayuda">Falla de equipo, desviación de procedimiento, material, condición ambiental… Calidad lo evaluará
                    y aparecerá en el informe del lote. Los datos fuera de especificación y los inicios fuera de ventana se reportan solos.</p>
                <div class="ev-rejilla">
                    <label class="ev-campo"><span>Lote</span>
                        ${lote || fase ? `<input type="text" value="${esc(loteNombre || '')}" disabled>`
                                       : '<select name="lote" required><option value="">Cargando lotes…</option></select>'}
                    </label>
                    <label class="ev-campo"><span>Tarea <small>(opcional)</small></span>
                        ${fase ? `<input type="text" value="${esc(faseNombre || '')}" disabled>`
                               : `<select name="fase"><option value="">${lote ? 'Cargando tareas…' : 'Elige primero el lote'}</option></select>`}
                    </label>
                    <label class="ev-campo"><span>Tipo de evento</span>
                        <select name="tipo" required><option value="">Elige…</option>
                            ${datos.tipos_manuales.map(t => `<option value="${t.valor}">${esc(t.nombre)}</option>`).join('')}</select>
                    </label>
                    <label class="ev-campo"><span>¿Cuándo ocurrió?</span>
                        <input type="datetime-local" name="ocurrio_en" value="${ahoraLocal()}" max="${ahoraLocal()}" required>
                    </label>
                    <label class="ev-campo ev-campo--ancho"><span>Equipo involucrado <small>(opcional)</small></span>
                        <select name="equipo"><option value="">Ninguno</option></select>
                    </label>
                    <label class="ev-campo ev-campo--ancho"><span>Título breve</span>
                        <input type="text" name="titulo" maxlength="200" placeholder="Ej. Paro del agitador del biorreactor" required>
                    </label>
                    <label class="ev-campo ev-campo--ancho"><span>¿Qué pasó? <small>(mínimo 10 caracteres)</small></span>
                        <textarea name="descripcion" rows="4" placeholder="Qué se observó, cuánto duró, qué valores o alarmas hubo…" required></textarea>
                    </label>
                    <label class="ev-campo ev-campo--ancho"><span>Acción inmediata <small>(opcional)</small></span>
                        <textarea name="accion_inmediata" rows="2" placeholder="Qué se hizo en el momento (se avisó al supervisor, se cambió el equipo…)"></textarea>
                    </label>
                </div>
                <div class="ev-error" role="alert" hidden></div>
                <footer class="ev-modal__pie">
                    <button type="button" class="ev-boton ev-boton--secundario" data-cerrar>Cancelar</button>
                    <button type="submit" class="ev-boton ev-boton--primario">Reportar evento</button>
                </footer>
            </form>`;
        document.body.appendChild(fondo);
        const form = fondo.querySelector('form');
        const error = fondo.querySelector('.ev-error');
        const cerrar = () => { fondo.remove(); document.removeEventListener('keydown', alTeclado); };
        const alTeclado = (e) => { if (e.key === 'Escape') cerrar(); };
        document.addEventListener('keydown', alTeclado);
        fondo.querySelectorAll('[data-cerrar]').forEach(b => b.addEventListener('click', cerrar));
        fondo.addEventListener('click', (e) => { if (e.target === fondo) cerrar(); });
        form.tipo.focus();

        const llenarTareas = async (loteId) => {
            if (!form.fase) return;
            form.fase.innerHTML = '<option value="">Cargando tareas…</option>';
            const tareas = loteId ? await tareasDelLote(loteId) : [];
            const etiqueta = { EN_PROGRESO: 'En curso', COMPLETADA: 'Completada', PENDIENTE: 'Pendiente', OMITIDA: 'Omitida' };
            form.fase.innerHTML = `<option value="">${loteId ? 'Sin tarea específica (todo el lote)' : 'Elige primero el lote'}</option>`
                + tareas.map(f => `<option value="${f.id}">${esc(etiqueta[f.estado] || f.estado)} · ${esc(nombreTarea(f))}</option>`).join('');
        };
        if (form.lote) {
            lotesAbiertos().then(lotes => {
                form.lote.innerHTML = '<option value="">Elige el lote…</option>'
                    + lotes.map(l => `<option value="${l.id}">${esc(l.identificador_lote)} · ${esc(l.estado)}</option>`).join('');
            });
            form.lote.addEventListener('change', () => llenarTareas(form.lote.value));
        } else if (lote && !fase) {
            llenarTareas(lote);
        }
        equipos().then(lista => {
            form.equipo.innerHTML = '<option value="">Ninguno</option>'
                + lista.map(e => `<option value="${esc(e.id)}">${esc(`[${e.id}] ${e.nombre}`)}</option>`).join('');
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            error.hidden = true;
            const boton = form.querySelector('[type="submit"]');
            const cuerpo = {
                lote: lote || (form.lote ? form.lote.value : '') || '', fase: fase || (form.fase ? form.fase.value : '') || '',
                tipo: form.tipo.value, titulo: form.titulo.value, descripcion: form.descripcion.value,
                accion_inmediata: form.accion_inmediata.value, ocurrio_en: form.ocurrio_en.value, equipo: form.equipo.value,
            };
            boton.disabled = true;
            boton.textContent = 'Reportando…';
            try {
                const res = await fetch('/api/eventos/', {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken') },
                    body: JSON.stringify(cuerpo),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.error || data.detail || 'No se pudo reportar el evento.');
                cerrar();
                aviso(`Evento ${data.folio} reportado. Calidad lo evaluará.`);
                if (alGuardar) alGuardar(data);
            } catch (err) {
                error.textContent = err.message;
                error.hidden = false;
                boton.disabled = false;
                boton.textContent = 'Reportar evento';
            }
        });
    };

    // Aviso breve en una esquina (no bloquea como alert)
    function aviso(texto) {
        const caja = document.createElement('div');
        caja.className = 'ev-aviso';
        caja.setAttribute('role', 'status');
        caja.textContent = `✅ ${texto}`;
        document.body.appendChild(caja);
        setTimeout(() => caja.classList.add('ev-aviso--fuera'), 3500);
        setTimeout(() => caja.remove(), 4000);
    }
    window.avisoEvento = aviso;
})();
