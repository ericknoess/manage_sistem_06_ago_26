// static/core/js/captura.js — Captura de datos de proceso de una fase (web y tablet).
//
//   abrirCapturaDatos({ faseId, terminal: false, adicional: false, alCambiar: () => recargar() });
//
// Muestra lo que pide la fase (secciones y parámetros copiados de la receta al instanciar el lote), calcula los
// parámetros con fórmula mientras se escribe y marca lo que sale de especificación o de alerta. Si ya se capturó,
// muestra los valores con su historial y permite corregir uno (motivo + firma: contraseña en web con firma.js,
// PIN en la terminal). `adicional: true` registra una muestra fuera del calendario en una incubación en curso.
// Al enfocar un parámetro numérico se muestra su gráfica de tendencia (como en Cultivo): los datos anteriores de la
// etapa contra la edad, el valor que se está escribiendo, los límites y el valor esperado (fijo o curva de la receta).
// API: /api/captura/<fase>/ (ver datos_proceso/views.py). Estilos en static/core/css/captura.css.

(function () {
    const esc = (texto) => {
        const div = document.createElement('div');
        div.textContent = texto ?? '';
        return div.innerHTML;
    };
    const cookie = (nombre) => (document.cookie.split('; ').find(c => c.startsWith(nombre + '=')) || '').split('=')[1] || '';
    const enviar = (url, cuerpo) => fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(cookie('csrftoken')) },
        body: JSON.stringify(cuerpo),
    });

    const fechaHora = (iso) => iso ? new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
    const horas = (h) => h === null || h === undefined ? '—' : `${Number(h).toFixed(1)} h`;
    const ahoraLocal = () => {
        const d = new Date();
        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        return d.toISOString().slice(0, 16);
    };

    function textoLimites(lim) {
        if (!lim) return '';
        const rango = (a, b) => (a === null && b === null) ? '' : `${a ?? '−∞'} – ${b ?? '∞'}`;
        const esp = rango(lim.especificacion_min, lim.especificacion_max);
        const ale = rango(lim.alerta_min, lim.alerta_max);
        return [esp && `Esp. ${esp}`, ale && `Alerta ${ale}`].filter(Boolean).join(' · ');
    }

    function marcaEstado(fila) {
        if (fila.fuera_especificacion) return '<span class="captura-marca captura-marca--fuera" title="Fuera de especificación">🚨 Fuera de esp.</span>';
        if (fila.fuera_alerta) return '<span class="captura-marca captura-marca--alerta" title="Fuera del rango de alerta">⚠️ Alerta</span>';
        return '';
    }

    function htmlEdades(detalle, toma) {
        const cero = detalle.edad_cero_etapa;
        const ceroLote = detalle.edad_cero_lote;
        const edadEtapa = toma ? toma.edad_etapa_h : detalle.edad_ahora_etapa_h;
        const edadLote = toma ? toma.edad_lote_h : detalle.edad_ahora_lote_h;
        const titulo = cero ? `Edad 0: ${fechaHora(cero.momento)} · ${cero.origen}${cero.estimada ? ' (estimada: aún no ocurre)' : ''}` : '';
        const tituloLote = ceroLote ? `Edad 0 del lote: ${fechaHora(ceroLote.momento)} · ${ceroLote.origen}` : '';
        return `<div class="captura-edades">
            <span title="${esc(titulo)}">⏱ Edad en ${esc(detalle.etapa)}: <strong>${horas(edadEtapa)}</strong>${cero && cero.estimada ? ' <em>(estimada)</em>' : ''}</span>
            <span title="${esc(tituloLote)}">Edad del lote: <strong>${horas(edadLote)}</strong></span>
            ${detalle.hora_programada !== null && detalle.hora_programada !== undefined ? `<span>Muestreo programado: <strong>${detalle.hora_programada} h</strong></span>` : ''}
        </div>`;
    }

    function htmlEntrada(p) {
        const id = `captura-p-${p.parametro}`;
        const comun = `id="${id}" data-parametro="${p.parametro}" class="captura-entrada"`;
        if (p.formula) return `<output id="${id}" class="captura-calculado" data-parametro="${p.parametro}" title="Se calcula con: ${esc(p.formula)}">—</output>`;
        if (p.tipo === 'OPCION') return `<select ${comun}><option value=""></option>${p.opciones.map(o => `<option>${esc(o)}</option>`).join('')}</select>`;
        if (p.tipo === 'BOOLEANO') return `<select ${comun}><option value=""></option><option value="true">Sí</option><option value="false">No</option></select>`;
        if (p.tipo === 'NUMERO') return `<input ${comun} type="text" inputmode="decimal" autocomplete="off" placeholder="0${p.decimales ? '.' + '0'.repeat(p.decimales) : ''}">`;
        return `<input ${comun} type="text" maxlength="500" autocomplete="off">`;
    }

    function htmlFormulario(plan, adicional) {
        return plan.secciones.map(s => `
            <fieldset class="captura-seccion">
                <legend>${esc(s.nombre)}${s.codigo_muestra ? ` <span class="captura-codigo">🧪 ${esc(s.codigo_muestra)}</span>` : ''}</legend>
                ${s.parametros.map(p => `
                    <label class="captura-fila" data-fila="${p.parametro}">
                        <span class="captura-nombre">${esc(p.nombre)}${p.obligatorio && !adicional ? ' <b class="captura-obligatorio">*</b>' : ''}
                            ${p.unidad ? `<small>${esc(p.unidad)}</small>` : ''}${p.formula ? ' <small class="captura-f">ƒ</small>' : ''}</span>
                        ${htmlEntrada(p)}
                        <span class="captura-ayuda">${esc(textoLimites(p.limites))}</span>
                        <span class="captura-estado"></span>
                    </label>`).join('')}
            </fieldset>`).join('');
    }

    function htmlValoresRegistrados(toma, puedeCorregir) {
        const porSeccion = {};
        toma.valores.forEach(v => (porSeccion[v.seccion] = porSeccion[v.seccion] || []).push(v));
        const codigos = Object.entries(toma.codigos_muestra || {}).map(([s, c]) => `${esc(s)}: <strong>${esc(c)}</strong>`).join(' · ');
        return `
            <div class="captura-toma-info">
                📝 Registrado por <strong>${esc(toma.registrado_por)}</strong> · toma a las ${fechaHora(toma.momento)}
                ${codigos ? `<br>🧪 Muestras: ${codigos}` : ''}
                ${toma.adicional ? `<br>➕ Muestra adicional: ${esc(toma.motivo)}` : ''}
            </div>
            ${Object.entries(porSeccion).map(([seccion, valores]) => `
                <fieldset class="captura-seccion">
                    <legend>${esc(seccion)}</legend>
                    ${valores.map(v => `
                        <div class="captura-fila captura-fila--lectura" ${v.tipo === 'NUMERO' ? `data-grafica="${v.parametro}" data-toma-id="${toma.id}" title="Toca para ver su tendencia"` : ''}>
                            <span class="captura-nombre">${esc(v.nombre)} ${v.unidad ? `<small>${esc(v.unidad)}</small>` : ''}${v.calculado ? ' <small class="captura-f">ƒ</small>' : ''}</span>
                            <span class="captura-valor ${v.fuera_especificacion ? 'captura-valor--fuera' : v.fuera_alerta ? 'captura-valor--alerta' : ''}">${v.valor === null ? '<span class="captura-vacio">sin dato</span>' : esc(v.valor)}</span>
                            <span class="captura-ayuda">${esc(textoLimites(v.limites))}</span>
                            <span class="captura-estado">
                                ${marcaEstado(v)}
                                ${v.corregido ? `<button type="button" class="captura-historial" data-historial="${v.parametro}" title="Ver correcciones">🕘 corregido</button>` : ''}
                                ${puedeCorregir && !v.calculado ? `<button type="button" class="captura-corregir" data-corregir="${v.parametro}" data-toma="${toma.id}">✏️ Corregir</button>` : ''}
                            </span>
                        </div>
                        <div class="captura-historial-lista" data-lista="${toma.id}-${v.parametro}" hidden>
                            ${v.historial.map(h => `<div class="${h.vigente ? 'vigente' : ''}">${h.vigente ? '✔' : '✖'} <strong>${h.valor === null ? 'sin dato' : esc(h.valor)}</strong>
                                · ${esc(h.registrado_por)} · ${fechaHora(h.registrado_en)}${h.motivo ? ` · <em>${esc(h.motivo)}</em>` : ''}</div>`).join('')}
                        </div>`).join('')}
                </fieldset>`).join('')}`;
    }

    // ------------------------------------------------------------------
    // Gráfica de tendencia (SVG propio: funciona sin internet en la tablet)
    // ------------------------------------------------------------------
    const SVG = 'http://www.w3.org/2000/svg';
    const num = (v) => (v === null || v === undefined || v === '') ? null : Number(String(v).replace(',', '.'));

    function marcas(min, max, cuantas = 5) {
        const paso0 = (max - min) / cuantas || 1;
        const base = Math.pow(10, Math.floor(Math.log10(paso0)));
        const paso = [1, 2, 2.5, 5, 10].map(m => m * base).find(p => p >= paso0) || paso0;
        const lista = [];
        for (let v = Math.ceil(min / paso) * paso; v <= max + paso * 1e-9; v += paso) lista.push(Number(v.toFixed(10)));
        return lista;
    }
    const corto = (v) => Math.abs(v) >= 1000 ? v.toFixed(0) : Number(v.toPrecision(4)).toString();

    function htmlPanelTendencia() {
        return `<aside class="captura-tendencia">
            <div class="captura-tendencia__titulo">📈 Tendencia</div>
            <div class="captura-tendencia__leyenda"></div>
            <div class="captura-tendencia__lienzo"><div class="captura-tendencia__vacio">Toca un parámetro numérico para ver sus datos anteriores y el valor esperado.</div></div>
            <div class="captura-tendencia__nota"></div>
        </aside>`;
    }

    /**
     * Dibuja la tendencia de un parámetro en el panel.
     * p: {nombre, unidad, limites, referencia: {objetivo, curva, eje_edad}}; historial: puntos del servidor;
     * vivo: {edad, valor} del dato que se escribe (o null); tomaActual: id de toma a resaltar en consulta.
     */
    function dibujarTendencia(panel, { p, historial, vivo = null, tomaActual = null }) {
        const ref = p.referencia || {};
        const eje = ref.eje_edad === 'ETAPA' ? 'edad_etapa_h' : 'edad_lote_h';
        const textoEje = ref.eje_edad === 'ETAPA' ? 'Edad de la etapa (h)' : 'Edad del lote (h)';
        const lim = p.limites || {};
        const puntos = (historial || []).filter(h => h[eje] !== null && h[eje] !== undefined).map(h => ({ ...h, x: h[eje], y: h.valor }));
        const sinEdad = (historial || []).length - puntos.length;
        const actual = vivo && vivo.valor !== null && Number.isFinite(vivo.valor) && vivo.edad !== null ? { x: vivo.edad, y: vivo.valor } : null;
        const curva = (ref.curva || []).map(([x, y]) => ({ x: Number(x), y: Number(y) }));
        const objetivo = num(ref.objetivo);
        const lineas = [
            ['especificacion_max', 'Esp. máx', 'fuera'], ['especificacion_min', 'Esp. mín', 'fuera'],
            ['alerta_max', 'Alerta máx', 'alerta'], ['alerta_min', 'Alerta mín', 'alerta'],
        ].filter(([c]) => num(lim[c]) !== null).map(([c, etiqueta, tipo]) => ({ y: num(lim[c]), etiqueta, tipo }));

        panel.querySelector('.captura-tendencia__titulo').innerHTML = `📈 ${esc(p.nombre)}${p.unidad ? ` <small>${esc(p.unidad)}</small>` : ''}`;
        const lienzo = panel.querySelector('.captura-tendencia__lienzo');
        const nota = panel.querySelector('.captura-tendencia__nota');
        const leyenda = panel.querySelector('.captura-tendencia__leyenda');

        // Dominio: los datos mandan; la curva se recorta a ese rango de edades
        const xsDatos = [...puntos.map(q => q.x), ...(actual ? [actual.x] : [])];
        let xMin = Math.min(0, ...xsDatos);
        let xMax = xsDatos.length ? Math.max(...xsDatos) : 0;
        xMax = Math.max(xMax + Math.max(6, (xMax - xMin) * 0.15), 24);
        const curvaVisible = curva.filter((q, i) => (q.x >= xMin && q.x <= xMax)
            || (curva[i + 1] && curva[i + 1].x >= xMin && q.x < xMin) || (curva[i - 1] && curva[i - 1].x <= xMax && q.x > xMax));
        const ys = [...puntos.map(q => q.y), ...(actual ? [actual.y] : []), ...lineas.map(l => l.y),
                    ...(objetivo !== null ? [objetivo] : []), ...curvaVisible.map(q => q.y)];
        if (!ys.length) {
            lienzo.innerHTML = '<div class="captura-tendencia__vacio">Sin datos anteriores en esta etapa ni valor esperado configurado. Escribe un valor para verlo aquí.</div>';
            leyenda.innerHTML = '';
            nota.textContent = '';
            return;
        }
        let yMin = Math.min(...ys), yMax = Math.max(...ys);
        const holgura = (yMax - yMin) * 0.12 || Math.abs(yMax) * 0.1 || 1;
        yMin -= holgura; yMax += holgura;

        const ancho = Math.max(lienzo.clientWidth || 0, 280), alto = 240;
        const m = { izq: 46, der: 14, arr: 10, aba: 34 };
        const X = (v) => m.izq + (v - xMin) / (xMax - xMin) * (ancho - m.izq - m.der);
        const Y = (v) => alto - m.aba - (v - yMin) / (yMax - yMin) * (alto - m.arr - m.aba);
        const el = (tag, attrs, padre) => {
            const nodo = document.createElementNS(SVG, tag);
            Object.entries(attrs).forEach(([k, v]) => nodo.setAttribute(k, v));
            if (padre) padre.appendChild(nodo);
            return nodo;
        };
        const svg = el('svg', { viewBox: `0 0 ${ancho} ${alto}`, width: ancho, height: alto, class: 'captura-tendencia__svg', role: 'img',
            'aria-label': `Tendencia de ${p.nombre}` });
        const clipId = `clip-${Math.random().toString(36).slice(2)}`;
        el('rect', { x: m.izq, y: m.arr, width: ancho - m.izq - m.der, height: alto - m.arr - m.aba }, el('clipPath', { id: clipId }, el('defs', {}, svg)));

        // Rejilla y ejes (recesivos)
        marcas(yMin, yMax, 4).forEach(v => {
            el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(v), y2: Y(v), class: 'tg-rejilla' }, svg);
            el('text', { x: m.izq - 6, y: Y(v) + 3, class: 'tg-eje', 'text-anchor': 'end' }, svg).textContent = corto(v);
        });
        marcas(xMin, xMax, 6).forEach(v => {
            el('line', { x1: X(v), x2: X(v), y1: alto - m.aba, y2: alto - m.aba + 4, class: 'tg-tick' }, svg);
            el('text', { x: X(v), y: alto - m.aba + 15, class: 'tg-eje', 'text-anchor': 'middle' }, svg).textContent = corto(v);
        });
        el('line', { x1: m.izq, x2: ancho - m.der, y1: alto - m.aba, y2: alto - m.aba, class: 'tg-base' }, svg);
        el('text', { x: (m.izq + ancho - m.der) / 2, y: alto - 4, class: 'tg-eje', 'text-anchor': 'middle' }, svg).textContent = textoEje;

        const zona = el('g', { 'clip-path': `url(#${clipId})` }, svg);
        lineas.forEach(l => {
            el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(l.y), y2: Y(l.y), class: `tg-limite tg-limite--${l.tipo}` }, zona);
            el('text', { x: ancho - m.der - 3, y: Y(l.y) - 3, class: 'tg-etiqueta', 'text-anchor': 'end' }, zona).textContent = `${l.etiqueta} ${corto(l.y)}`;
        });
        if (objetivo !== null) {
            el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(objetivo), y2: Y(objetivo), class: 'tg-esperado' }, zona);
            el('text', { x: m.izq + 4, y: Y(objetivo) - 3, class: 'tg-etiqueta' }, zona).textContent = `Esperado ${corto(objetivo)}`;
        }
        if (curvaVisible.length > 1) {
            el('polyline', { points: curvaVisible.map(q => `${X(q.x)},${Y(q.y)}`).join(' '), class: 'tg-curva' }, zona);
        }
        if (puntos.length > 1) {
            el('polyline', { points: puntos.map(q => `${X(q.x)},${Y(q.y)}`).join(' '), class: 'tg-historial' }, zona);
        }
        if (actual && puntos.length) {
            const ultimo = puntos[puntos.length - 1];
            el('line', { x1: X(ultimo.x), y1: Y(ultimo.y), x2: X(actual.x), y2: Y(actual.y), class: 'tg-enlace' }, zona);
        }

        // Puntos con su ayuda al pasar el cursor o tocar
        const ayuda = document.createElement('div');
        ayuda.className = 'captura-tendencia__ayuda';
        ayuda.hidden = true;
        const mostrar = (q, texto) => {
            ayuda.innerHTML = texto;
            ayuda.hidden = false;
            const izquierda = Math.min(X(q.x) + 10, ancho - 190);
            ayuda.style.left = `${Math.max(izquierda, 0)}px`;
            ayuda.style.top = `${Math.max(Y(q.y) - 52, 0)}px`;
        };
        const punto = (q, clase, texto) => {
            el('circle', { cx: X(q.x), cy: Y(q.y), r: clase.includes('vivo') ? 6 : 4.5, class: clase }, svg);
            const zonaToque = el('circle', { cx: X(q.x), cy: Y(q.y), r: 12, class: 'tg-toque' }, svg);
            zonaToque.addEventListener('mouseenter', () => mostrar(q, texto));
            zonaToque.addEventListener('click', () => mostrar(q, texto));
            zonaToque.addEventListener('mouseleave', () => { ayuda.hidden = true; });
        };
        const unidad = p.unidad ? ` ${esc(p.unidad)}` : '';
        puntos.forEach(q => {
            const estado = q.fuera_especificacion ? ' tg-punto--fuera' : q.fuera_alerta ? ' tg-punto--alerta' : '';
            const resaltado = tomaActual && q.toma === tomaActual ? ' tg-punto--actual' : '';
            punto(q, `tg-punto${estado}${resaltado}`, `<strong>${esc(corto(q.y))}${unidad}</strong> a ${esc(corto(q.x))} h<br>${esc(q.tarea)}${q.adicional ? ' · adicional' : ''}<br>${fechaHora(q.momento)}${q.fuera_especificacion ? '<br>🚨 Fuera de especificación' : q.fuera_alerta ? '<br>⚠️ Fuera de alerta' : ''}`);
        });
        if (actual) punto(actual, 'tg-punto tg-punto--vivo', `<strong>${esc(corto(actual.y))}${unidad}</strong> a ${esc(corto(actual.x))} h<br>Valor que estás capturando`);

        lienzo.innerHTML = '';
        lienzo.appendChild(svg);
        lienzo.appendChild(ayuda);

        const items = [];
        if (puntos.length) items.push(`<span><i class="tg-l tg-l--historial"></i>Registros anteriores (${puntos.length})</span>`);
        if (actual) items.push('<span><i class="tg-l tg-l--vivo"></i>Valor actual</span>');
        if (curvaVisible.length > 1) items.push('<span><i class="tg-l tg-l--curva"></i>Curva esperada</span>');
        if (objetivo !== null) items.push('<span><i class="tg-l tg-l--esperado"></i>Esperado fijo</span>');
        if (lineas.some(l => l.tipo === 'fuera')) items.push('<span><i class="tg-l tg-l--fuera"></i>Especificación</span>');
        if (lineas.some(l => l.tipo === 'alerta')) items.push('<span><i class="tg-l tg-l--alerta"></i>Alerta</span>');
        leyenda.innerHTML = items.join('');
        const notas = [];
        if (!puntos.length) notas.push('Aún no hay datos anteriores de este parámetro en la etapa.');
        if (sinEdad) notas.push(`${sinEdad} registro(s) sin edad (falta la edad 0) no se grafican.`);
        if (curva.length && curvaVisible.length < 2) notas.push('La curva esperada queda fuera de este rango de edades.');
        nota.textContent = notas.join(' ');
    }

    // Firma con PIN para la terminal (en web se usa ejecutarConFirma de firma.js)
    function firmarConPin({ titulo, detalle, url, cuerpo }) {
        return new Promise(resolver => {
            const fondo = document.createElement('div');
            fondo.className = 'captura-fondo captura-fondo--firma';
            fondo.innerHTML = `
                <form class="captura-modal captura-modal--firma" autocomplete="off">
                    <h3>✍️ Firma con tu PIN</h3>
                    <p><strong>${esc(titulo)}</strong><br>${esc(detalle)}</p>
                    <p class="captura-significado">«Corrijo el dato de proceso registrado»</p>
                    <input type="password" inputmode="numeric" class="captura-pin" placeholder="PIN" required>
                    <div class="captura-error" hidden></div>
                    <div class="captura-botones">
                        <button type="button" class="captura-btn captura-btn--secundario">Cancelar</button>
                        <button type="submit" class="captura-btn captura-btn--primario">Firmar</button>
                    </div>
                </form>`;
            document.body.appendChild(fondo);
            const pin = fondo.querySelector('.captura-pin');
            const error = fondo.querySelector('.captura-error');
            pin.focus();
            const cerrar = (r) => { fondo.remove(); resolver(r); };
            fondo.querySelector('.captura-btn--secundario').onclick = () => cerrar(null);
            fondo.querySelector('form').onsubmit = async (e) => {
                e.preventDefault();
                try {
                    const res = await enviar(url, { ...cuerpo, firma_pin: pin.value });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok && ['FIRMA_INVALIDA', 'FIRMA_REQUERIDA'].includes(data.codigo)) {
                        error.textContent = data.error; error.hidden = false; pin.value = ''; pin.focus();
                        return;
                    }
                    cerrar({ ok: res.ok, status: res.status, data });
                } catch (err) {
                    error.textContent = 'Error de red. Intenta de nuevo.'; error.hidden = false;
                }
            };
        });
    }

    window.abrirCapturaDatos = async function ({ faseId, terminal = false, adicional = false, alCambiar = null }) {
        const fondo = document.createElement('div');
        fondo.className = `captura-fondo${terminal ? ' captura--terminal' : ''}`;
        fondo.innerHTML = '<div class="captura-modal"><div class="captura-cargando">Cargando…</div></div>';
        document.body.appendChild(fondo);
        const modal = fondo.querySelector('.captura-modal');
        const cerrar = () => { document.removeEventListener('keydown', alEscape); fondo.remove(); };
        const alEscape = (e) => { if (e.key === 'Escape' && !fondo.querySelector('.captura-fondo--firma')) cerrar(); };
        document.addEventListener('keydown', alEscape);
        const urlBase = `/api/captura/${faseId}/`;

        async function cargar() {
            const res = await fetch(urlBase);
            if (!res.ok) throw new Error('No se pudo cargar la captura de datos.');
            return res.json();
        }

        function encabezado(detalle, titulo) {
            return `<div class="captura-encabezado">
                <h3>${titulo}</h3>
                <button type="button" class="captura-cerrar" title="Cerrar">✕</button>
            </div>
            <div class="captura-contexto"><strong>${esc(detalle.tarea)}</strong> · Lote ${esc(detalle.lote)} · Etapa ${esc(detalle.etapa)}</div>`;
        }

        // Edad (h) de un momento según el eje de la gráfica del parámetro
        function edadDe(detalle, p, momento) {
            const cero = (p.referencia || {}).eje_edad === 'ETAPA' ? detalle.edad_cero_etapa : detalle.edad_cero_lote;
            if (!cero || !cero.momento || !momento) return null;
            return Math.round((new Date(momento) - new Date(cero.momento)) / 36e3) / 100;
        }

        function marcarGraficada(id) {
            modal.querySelectorAll('.captura-fila--graficada').forEach(f => f.classList.remove('captura-fila--graficada'));
            modal.querySelectorAll(`[data-fila="${id}"], [data-grafica="${id}"]`).forEach(f => f.classList.add('captura-fila--graficada'));
        }

        function pintarRegistro(detalle) {
            const plan = adicional ? detalle.plan_adicional : detalle.plan;
            const numericos = Object.fromEntries(plan.secciones.flatMap(s => s.parametros).filter(p => p.tipo === 'NUMERO').map(p => [p.parametro, p]));
            const conGrafica = Object.keys(numericos).length > 0;
            modal.classList.toggle('captura-modal--con-tendencia', conGrafica);
            modal.innerHTML = `
                ${encabezado(detalle, adicional ? '➕ Muestra adicional' : '📊 Capturar datos de proceso')}
                ${htmlEdades(detalle, null)}
                <div class="captura-cuerpo">
                <form class="captura-form" autocomplete="off">
                    <div class="captura-generales">
                        <label>Hora real de la toma <input type="datetime-local" name="momento" value="${ahoraLocal()}" max="${ahoraLocal()}"></label>
                        ${adicional ? `<label>Código de la muestra (opcional) <input type="text" name="codigo_muestra" maxlength="60"></label>` : ''}
                    </div>
                    ${adicional ? `<label class="captura-motivo">Motivo de la muestra adicional *
                        <textarea name="motivo" rows="2" minlength="10" maxlength="500" required placeholder="¿Por qué se toma fuera del calendario?"></textarea></label>` : ''}
                    ${htmlFormulario(plan, adicional)}
                    <div class="captura-avisos" hidden></div>
                    <div class="captura-error" hidden></div>
                    <div class="captura-botones">
                        <button type="button" class="captura-btn captura-btn--secundario captura-cancelar">Cancelar</button>
                        <button type="submit" class="captura-btn captura-btn--primario">💾 Guardar datos</button>
                    </div>
                </form>
                ${conGrafica ? htmlPanelTendencia() : ''}
                </div>`;
            modal.querySelector('.captura-cerrar').onclick = cerrar;
            modal.querySelector('.captura-cancelar').onclick = cerrar;
            const form = modal.querySelector('form');
            const error = modal.querySelector('.captura-error');
            const avisos = modal.querySelector('.captura-avisos');
            const valores = () => {
                const v = {};
                form.querySelectorAll('.captura-entrada').forEach(e => { if (e.value !== '') v[e.dataset.parametro] = e.value; });
                return v;
            };

            // Tendencia del parámetro seleccionado con el valor que se escribe
            const panel = modal.querySelector('.captura-tendencia');
            let graficado = null;
            const refrescarGrafica = () => {
                if (!panel || !graficado) return;
                const p = numericos[graficado];
                const nodo = form.querySelector(`#captura-p-${graficado}`);
                const texto = p.formula ? nodo.textContent : nodo.value;
                const momento = form.elements.momento.value ? new Date(form.elements.momento.value) : new Date();
                dibujarTendencia(panel, {
                    p, historial: (detalle.tendencias || {})[graficado] || [],
                    vivo: { edad: edadDe(detalle, p, momento), valor: texto === '—' ? null : num(texto) },
                });
            };
            const graficar = (id) => {
                if (!numericos[id] || graficado === String(id)) return;
                graficado = String(id);
                marcarGraficada(id);
                refrescarGrafica();
            };
            form.addEventListener('focusin', (e) => { const f = e.target.closest('[data-fila]'); if (f) graficar(f.dataset.fila); });
            form.addEventListener('click', (e) => { const f = e.target.closest('[data-fila]'); if (f) graficar(f.dataset.fila); });
            form.elements.momento.addEventListener('change', refrescarGrafica);
            form.addEventListener('input', (e) => { if (e.target.classList.contains('captura-entrada')) refrescarGrafica(); });

            let temporizador = null;
            const vistaPrevia = async () => {
                try {
                    const res = await enviar(`${urlBase}vista-previa/`, { valores: valores(), adicional });
                    const data = await res.json();
                    form.querySelectorAll('.captura-fila').forEach(f => f.classList.remove('captura-fila--fuera', 'captura-fila--alerta', 'captura-fila--invalida'));
                    if (!res.ok) {
                        error.textContent = data.error; error.hidden = false;
                        return;
                    }
                    error.hidden = true;
                    data.valores.forEach(v => {
                        const fila = form.querySelector(`[data-fila="${v.parametro}"]`);
                        if (!fila) return;
                        if (v.calculado) fila.querySelector('.captura-calculado').textContent = v.valor ?? '—';
                        if (v.fuera_especificacion) fila.classList.add('captura-fila--fuera');
                        else if (v.fuera_alerta) fila.classList.add('captura-fila--alerta');
                        fila.querySelector('.captura-estado').innerHTML = marcaEstado(v);
                    });
                    avisos.innerHTML = data.avisos.map(esc).join('<br>');
                    avisos.hidden = !data.avisos.length;
                    if (graficado && numericos[graficado].formula) refrescarGrafica();
                } catch (err) { /* sin red: se valida al guardar */ }
            };
            form.addEventListener('input', (e) => {
                if (!e.target.classList.contains('captura-entrada')) return;
                clearTimeout(temporizador);
                temporizador = setTimeout(vistaPrevia, 350);
            });
            form.querySelector('.captura-entrada')?.focus();
            if (!graficado && conGrafica) graficar(Object.keys(numericos)[0]);

            form.onsubmit = async (e) => {
                e.preventDefault();
                const boton = form.querySelector('.captura-btn--primario');
                boton.disabled = true;
                error.hidden = true;
                const cuerpo = { valores: valores(), momento: form.elements.momento.value || null };
                if (adicional) {
                    cuerpo.motivo = form.elements.motivo.value.trim();
                    cuerpo.codigo_muestra = form.elements.codigo_muestra.value.trim();
                }
                try {
                    const res = await enviar(`${urlBase}${adicional ? 'adicional' : 'registrar'}/`, cuerpo);
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) {
                        error.textContent = data.error || data.detail || 'No se pudieron guardar los datos.';
                        error.hidden = false;
                        return;
                    }
                    if (data.avisos && data.avisos.length) alert('Datos guardados con observaciones:\n\n' + data.avisos.join('\n'));
                    if (alCambiar) alCambiar();
                    adicional = false;
                    pintarConsulta(data);
                } catch (err) {
                    error.textContent = 'Error de red. Revisa la conexión e intenta de nuevo.';
                    error.hidden = false;
                } finally {
                    boton.disabled = false;
                }
            };
        }

        function pintarConsulta(detalle) {
            const toma = detalle.toma;
            const sinCaptura = !toma && !detalle.adicionales.length;
            let aviso = '';
            if (sinCaptura && detalle.plan && detalle.plan.secciones && detalle.estado === 'PENDIENTE') aviso = 'Inicia la tarea para capturar sus datos.';
            else if (sinCaptura) aviso = 'Esta tarea no tiene datos capturados.';
            const tomas = [toma, ...detalle.adicionales].filter(Boolean);
            const conGrafica = tomas.some(t => t.valores.some(v => v.tipo === 'NUMERO'));
            modal.classList.toggle('captura-modal--con-tendencia', conGrafica);
            modal.innerHTML = `
                ${encabezado(detalle, '📊 Datos de proceso')}
                ${htmlEdades(detalle, toma)}
                ${aviso ? `<div class="captura-vacio-grande">${aviso}</div>` : ''}
                <div class="captura-cuerpo"><div class="captura-registrados">
                ${toma ? htmlValoresRegistrados(toma, detalle.puede_corregir) : ''}
                ${detalle.adicionales.length ? `<h4 class="captura-subtitulo">➕ Muestras adicionales (${detalle.adicionales.length})</h4>
                    ${detalle.adicionales.map(t => htmlValoresRegistrados(t, detalle.puede_corregir)).join('')}` : ''}
                </div>${conGrafica ? htmlPanelTendencia() : ''}</div>
                <div class="captura-botones">
                    ${detalle.admite_adicional ? '<button type="button" class="captura-btn captura-btn--secundario captura-nueva-adicional">➕ Muestra adicional</button>' : ''}
                    <button type="button" class="captura-btn captura-btn--primario captura-listo">Cerrar</button>
                </div>`;
            modal.querySelector('.captura-cerrar').onclick = cerrar;
            modal.querySelector('.captura-listo').onclick = cerrar;
            const nueva = modal.querySelector('.captura-nueva-adicional');
            if (nueva) nueva.onclick = () => { adicional = true; pintarRegistro(detalle); };
            modal.querySelectorAll('[data-historial]').forEach(b => b.onclick = () => {
                const lista = b.closest('.captura-seccion').querySelector(`[data-lista$="-${b.dataset.historial}"]`);
                if (lista) lista.hidden = !lista.hidden;
            });
            modal.querySelectorAll('[data-corregir]').forEach(b => b.onclick = () => corregir(detalle, Number(b.dataset.toma), Number(b.dataset.corregir), b));

            const panel = modal.querySelector('.captura-tendencia');
            const graficar = (fila) => {
                const tomaId = Number(fila.dataset.tomaId);
                const v = tomas.find(t => t.id === tomaId).valores.find(x => String(x.parametro) === fila.dataset.grafica);
                modal.querySelectorAll('.captura-fila--graficada').forEach(f => f.classList.remove('captura-fila--graficada'));
                fila.classList.add('captura-fila--graficada');
                dibujarTendencia(panel, { p: v, historial: (detalle.tendencias || {})[fila.dataset.grafica] || [], tomaActual: tomaId });
            };
            modal.querySelectorAll('[data-grafica]').forEach(f => f.addEventListener('click', (e) => {
                if (!e.target.closest('button')) graficar(f);
            }));
            const primera = modal.querySelector('[data-grafica]');
            if (panel && primera) graficar(primera);
        }

        function corregir(detalle, tomaId, parametroId, boton) {
            const toma = [detalle.toma, ...detalle.adicionales].find(t => t && t.id === tomaId);
            const valor = toma.valores.find(v => v.parametro === parametroId);
            const fila = boton.closest('.captura-fila');
            if (fila.nextElementSibling && fila.nextElementSibling.classList.contains('captura-correccion')) return;
            const p = { ...valor, formula: '' };
            const caja = document.createElement('div');
            caja.className = 'captura-correccion';
            caja.innerHTML = `
                <label>Nuevo valor de ${esc(valor.nombre)} ${htmlEntrada(p)}</label>
                <label>Motivo de la corrección * <textarea rows="2" maxlength="500" placeholder="¿Por qué se corrige? (mínimo 10 caracteres)"></textarea></label>
                <div class="captura-error" hidden></div>
                <div class="captura-botones">
                    <button type="button" class="captura-btn captura-btn--secundario">Cancelar</button>
                    <button type="button" class="captura-btn captura-btn--primario">✍️ Firmar corrección</button>
                </div>`;
            fila.after(caja);
            const entrada = caja.querySelector('.captura-entrada');
            if (valor.valor !== null) entrada.value = valor.tipo === 'BOOLEANO' ? (valor.valor === 'Sí' ? 'true' : 'false') : valor.valor;
            entrada.focus();
            const error = caja.querySelector('.captura-error');
            caja.querySelector('.captura-btn--secundario').onclick = () => caja.remove();
            caja.querySelector('.captura-btn--primario').onclick = async () => {
                const motivo = caja.querySelector('textarea').value.trim();
                if (motivo.length < 10) { error.textContent = 'Escribe el motivo (mínimo 10 caracteres).'; error.hidden = false; return; }
                const peticion = {
                    accion: 'CORREGIR_DATO', titulo: `Corregir ${valor.nombre}`,
                    detalle: `${detalle.tarea} · lote ${detalle.lote}: ${valor.valor ?? 'sin dato'} → ${entrada.value || 'sin dato'}`,
                    url: `${urlBase}corregir/`, cuerpo: { toma: tomaId, parametro: parametroId, valor: entrada.value, motivo },
                };
                const r = terminal ? await firmarConPin(peticion) : await ejecutarConFirma(peticion);
                if (!r) return;
                if (!r.ok) { error.textContent = r.data.error || r.data.detail || 'No se pudo corregir.'; error.hidden = false; return; }
                if (alCambiar) alCambiar();
                pintarConsulta(r.data);
            };
        }

        try {
            const detalle = await cargar();
            if (adicional ? detalle.admite_adicional : detalle.puede_registrar) pintarRegistro(detalle);
            else { adicional = false; pintarConsulta(detalle); }
        } catch (err) {
            modal.innerHTML = `<div class="captura-error">${esc(err.message)}</div>
                <div class="captura-botones"><button type="button" class="captura-btn captura-btn--primario">Cerrar</button></div>`;
            modal.querySelector('button').onclick = cerrar;
        }
    };
})();
