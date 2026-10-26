// static/core/js/informes.js — Descarga de informes de datos de proceso (PDF / Excel).
//
//   abrirInformeLote({ loteId, procesoId, identificador });   // ventana: alcance (todo el lote o una etapa), gráficas
//                                                             // combinadas (parámetros y vista) y formato
//   descargarArchivo(url, nombrePorDefecto);                  // descarga con fetch: si falla, avisa sin salir de la pantalla
//
// API: /api/informes-proceso/<lote>/pdf|excel/?etapa= y /api/informes-proceso/lotes/ (ver datos_proceso/views.py).
// Cada emisión queda en la bitácora. Estilos en static/core/css/informes.css.

(function () {
    const esc = (texto) => {
        const div = document.createElement('div');
        div.textContent = texto ?? '';
        return div.innerHTML;
    };

    window.descargarArchivo = async function (url, nombrePorDefecto = 'informe') {
        const res = await fetch(url);
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.error || data.detail || 'No se pudo generar el archivo.');
        }
        const disposicion = res.headers.get('Content-Disposition') || '';
        const nombre = (disposicion.match(/filename="([^"]+)"/) || [])[1] || nombrePorDefecto;
        const blob = await res.blob();
        const enlace = document.createElement('a');
        enlace.href = URL.createObjectURL(blob);
        enlace.download = nombre;
        document.body.appendChild(enlace);
        enlace.click();
        setTimeout(() => { URL.revokeObjectURL(enlace.href); enlace.remove(); }, 1000);
        return nombre;
    };

    window.abrirInformeLote = async function ({ loteId, procesoId, identificador }) {
        const fondo = document.createElement('div');
        fondo.className = 'informe-fondo';
        fondo.innerHTML = `
            <div class="informe-modal" role="dialog" aria-modal="true">
                <div class="informe-encabezado">
                    <h3>🧾 Informe del lote ${esc(identificador)}</h3>
                    <button type="button" class="informe-cerrar" title="Cerrar">✕</button>
                </div>
                <p class="informe-ayuda">Datos capturados, indicadores, gráficas, valores fuera de límites, muestras adicionales y
                    correcciones con su firma electrónica. La emisión queda en la bitácora.</p>
                <label class="informe-campo">Alcance
                    <select class="informe-etapa"><option value="">Todo el lote</option></select>
                </label>
                <fieldset class="informe-combinadas">
                    <legend>Gráficas combinadas <small>(opcional, hasta 6 parámetros)</small></legend>
                    <div class="informe-parametros"><span class="informe-cargando">Cargando parámetros…</span></div>
                    <div class="informe-vista">
                        <label><input type="radio" name="vistaInforme" value="apiladas" checked> Apiladas (mismo eje)</label>
                        <label><input type="radio" name="vistaInforme" value="superpuestas"> Superpuestas (0–100 %)</label>
                    </div>
                </fieldset>
                <div class="informe-error" hidden></div>
                <div class="informe-botones">
                    <button type="button" class="informe-btn" data-formato="excel">📊 Excel</button>
                    <button type="button" class="informe-btn informe-btn--primario" data-formato="pdf">📄 PDF</button>
                </div>
            </div>`;
        document.body.appendChild(fondo);
        const cerrar = () => { document.removeEventListener('keydown', alEscape); fondo.remove(); };
        const alEscape = (e) => { if (e.key === 'Escape') cerrar(); };
        document.addEventListener('keydown', alEscape);
        fondo.addEventListener('click', (e) => { if (e.target === fondo) cerrar(); });
        fondo.querySelector('.informe-cerrar').onclick = cerrar;

        const select = fondo.querySelector('.informe-etapa');
        try {
            const info = await fetch(`/api/analisis-proceso/lotes/?proceso=${procesoId}`).then(r => r.json());
            select.insertAdjacentHTML('beforeend', (info.etapas || []).map(e => `<option value="${e.id}">Etapa ${esc(e.nombre)}</option>`).join(''));
        } catch (e) { /* sin etapas: solo "todo el lote" */ }

        // Parámetros con datos en este lote, por etapa; marcados de inicio los que se eligieron en Gráficas › Comparar
        const caja = fondo.querySelector('.informe-parametros');
        let preferencia = {};
        try { preferencia = JSON.parse(localStorage.getItem(`graficas-proceso:comparar-${procesoId}`)) || {}; } catch (e) { /* sin almacenamiento */ }
        if (preferencia.vista === 'superpuestas') fondo.querySelector('input[value="superpuestas"]').checked = true;
        try {
            const analisis = await fetch(`/api/analisis-proceso/?proceso=${procesoId}&lotes=${loteId}`).then(r => r.json());
            const conDatos = (analisis.parametros || []).filter(p => Object.keys(p.series).length);
            const elegidos = new Set(preferencia.seleccion || []);
            caja.innerHTML = conDatos.length ? conDatos.map(p => `
                <label class="informe-parametro" data-etapa="${p.etapa_id ?? ''}">
                    <input type="checkbox" value="${p.clave}" ${elegidos.has(p.clave) ? 'checked' : ''}>
                    ${esc(p.nombre)} <small>${esc(p.etapa)}</small></label>`).join('')
                : '<span class="informe-cargando">Este lote aún no tiene datos numéricos.</span>';
        } catch (e) {
            caja.innerHTML = '<span class="informe-cargando">No se pudieron cargar los parámetros.</span>';
        }
        const filtrarPorEtapa = () => fondo.querySelectorAll('.informe-parametro').forEach(l => {
            l.hidden = !!select.value && l.dataset.etapa !== select.value;
        });
        select.addEventListener('change', filtrarPorEtapa);
        caja.addEventListener('change', (e) => {
            const marcados = caja.querySelectorAll('input:checked');
            if (marcados.length > 6) { e.target.checked = false; alert('Combina hasta 6 parámetros.'); }
        });

        const error = fondo.querySelector('.informe-error');
        fondo.querySelectorAll('[data-formato]').forEach(boton => boton.onclick = async () => {
            const etapa = select.value;
            const combinar = [...caja.querySelectorAll('.informe-parametro:not([hidden]) input:checked')].map(i => i.value);
            const vista = fondo.querySelector('input[name="vistaInforme"]:checked').value;
            const params = new URLSearchParams();
            if (etapa) params.set('etapa', etapa);
            if (combinar.length) { params.set('combinar', combinar.join(',')); params.set('vista', vista); }
            const textoOriginal = boton.textContent;
            fondo.querySelectorAll('[data-formato]').forEach(b => { b.disabled = true; });
            boton.textContent = '⏳ Generando…';
            error.hidden = true;
            try {
                await descargarArchivo(`/api/informes-proceso/${loteId}/${boton.dataset.formato}/${params.toString() ? `?${params}` : ''}`);
                cerrar();
            } catch (err) {
                error.textContent = err.message;
                error.hidden = false;
            } finally {
                boton.textContent = textoOriginal;
                fondo.querySelectorAll('[data-formato]').forEach(b => { b.disabled = false; });
            }
        });
    };
})();
