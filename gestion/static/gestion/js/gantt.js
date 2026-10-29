// gestion/static/gestion/js/gantt.js — Gantt de un proyecto de oficina (SVG propio, sin librerías).
//
//   GanttOficina.pintar(caja, proyecto, tareas, { escala: 'dia'|'semana'|'mes', critica, base, filtrado })
//   GanttOficina.irAHoy()
//
// Izquierda: tabla (EDT, nombre con sangría, responsable, fechas, días hábiles, avance); derecha: línea de tiempo.
// Arrastrar una barra la mueve (conserva su duración en días hábiles) y arrastrar su borde derecho cambia el fin;
// el servidor ajusta a días hábiles, valida dependencias y recorre las sucesoras. Clic en una fila o barra abre la tarea.
// Usa cambiarTarea, abrirTarea y crearTareaRapida de proyecto.js.

const GanttOficina = (() => {
    const FILA = 34;
    const ENCABEZADO = 46;
    const PX_DIA = { dia: 30, semana: 13, mes: 3.6 };
    const NS = 'http://www.w3.org/2000/svg';
    let estado = { scrollLeft: null, scrollTop: 0 };
    let derecha = null, xDe = null, hoyDia = null;

    const colapsadas = (id) => new Set(G.leer(`colapsadas-${id}`, []));

    function filasVisibles(proyecto, tareas, filtrado) {
        if (filtrado) return tareas;
        const cerradas = colapsadas(proyecto.id);
        const ocultas = new Set();
        return tareas.filter(t => {
            if (t.padre && (cerradas.has(t.padre) || ocultas.has(t.padre))) { ocultas.add(t.id); return false; }
            return true;
        });
    }

    function rango(tareas, escala) {
        const dias = tareas.flatMap(t => [t.inicio, t.fin, t.base_inicio, t.base_fin]).filter(Boolean).map(G.dia);
        const hoy = G.hoy();
        let desde = Math.min(hoy, ...dias), hasta = Math.max(hoy, ...dias);
        const margen = { dia: 4, semana: 10, mes: 25 }[escala];
        desde -= margen; hasta += margen * 2;
        desde -= (G.diaSemana(desde) + 6) % 7;   // empezar en lunes
        if (escala === 'mes') { const d = new Date(desde * 86400000); desde = Math.round(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1) / 86400000); }
        if (hasta - desde < 30) hasta = desde + 30;
        return [desde, hasta];
    }

    function el(nombre, atributos = {}, padre = null) {
        const nodo = document.createElementNS(NS, nombre);
        Object.entries(atributos).forEach(([k, v]) => nodo.setAttribute(k, v));
        if (padre) padre.appendChild(nodo);
        return nodo;
    }

    function encabezado(svg, desde, hasta, px, escala) {
        el('rect', { x: 0, y: 0, width: (hasta - desde + 1) * px, height: ENCABEZADO, class: 'gg-enc-fondo' }, svg);
        let mesActual = null, inicioMes = 0;
        const cerrarMes = (fin) => {
            if (mesActual === null) return;
            const ancho = (fin - inicioMes) * px;
            const g = el('g', {}, svg);
            el('line', { x1: (inicioMes - desde) * px, y1: 0, x2: (inicioMes - desde) * px, y2: ENCABEZADO, class: 'gg-enc-linea' }, g);
            // Nombre completo si cabe; si no, abreviado; en un tramo muy corto, nada (no se enciman)
            const [anio, mes] = mesActual.split('-').map(Number);
            const largo = `${G.MESES_LARGOS[mes]} ${anio}`, corto = G.MESES_LARGOS[mes].slice(0, 3);
            const texto = ancho >= largo.length * 7 + 12 ? largo : ancho >= 34 ? corto : '';
            if (texto && escala !== 'mes') {
                const t = el('text', { x: (inicioMes - desde) * px + 6, y: 16, class: 'gg-enc-mes' }, g);
                t.textContent = texto;
            }
        };
        for (let d = desde; d <= hasta; d++) {
            const fecha = new Date(d * 86400000);
            const clave = escala === 'mes' ? `${fecha.getUTCFullYear()}-0` : `${fecha.getUTCFullYear()}-${fecha.getUTCMonth()}`;
            if (clave !== mesActual) { cerrarMes(d); mesActual = clave; inicioMes = d; }
            const x = (d - desde) * px;
            if (escala === 'dia') {
                const t = el('text', { x: x + px / 2, y: 38, class: `gg-enc-dia ${G.esHabil(d) ? '' : 'gg-enc-dia--libre'}`, 'text-anchor': 'middle' }, svg);
                t.textContent = fecha.getUTCDate();
            } else if (escala === 'semana' && G.diaSemana(d) === 1) {
                el('line', { x1: x, y1: 26, x2: x, y2: ENCABEZADO, class: 'gg-enc-linea gg-enc-linea--suave' }, svg);
                const t = el('text', { x: x + 4, y: 39, class: 'gg-enc-dia' }, svg);
                t.textContent = fecha.getUTCDate();
            } else if (escala === 'mes' && fecha.getUTCDate() === 1) {
                el('line', { x1: x, y1: 26, x2: x, y2: ENCABEZADO, class: 'gg-enc-linea gg-enc-linea--suave' }, svg);
                const t = el('text', { x: x + 4, y: 39, class: 'gg-enc-dia' }, svg);
                t.textContent = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'][fecha.getUTCMonth()];
            }
        }
        cerrarMes(hasta + 1);
        if (escala === 'mes') {
            // En escala de meses el renglón de arriba es el año
            svg.querySelectorAll('.gg-enc-mes').forEach(t => t.remove());
            for (let d = desde; d <= hasta; d++) {
                const f = new Date(d * 86400000);
                if (d === desde || (f.getUTCMonth() === 0 && f.getUTCDate() === 1)) {
                    const t = el('text', { x: (d - desde) * px + 6, y: 16, class: 'gg-enc-mes' }, svg);
                    t.textContent = f.getUTCFullYear();
                }
            }
        }
    }

    function tablaIzquierda(caja, proyecto, filas, filtrado) {
        const cerradas = colapsadas(proyecto.id);
        const tieneHijas = new Set(proyecto.tareas.filter(t => t.padre).map(t => t.padre));
        caja.innerHTML = `
            <div class="gg-tabla__enc" style="height:${ENCABEZADO}px">
                <span>EDT</span><span>Tarea</span><span>Responsable</span><span>Inicio</span><span>Fin</span><span title="Días hábiles">Días</span><span>%</span>
            </div>
            ${filas.map(t => `
                <div class="gg-fila ${t.resumen ? 'gg-fila--resumen' : ''} ${t.vencida ? 'gg-fila--vencida' : ''}" data-id="${t.id}" style="height:${FILA}px" tabindex="0">
                    <span class="gg-wbs">${t.wbs}</span>
                    <span class="gg-nombre" style="padding-left:${t.nivel * 14}px">
                        ${tieneHijas.has(t.id) && !filtrado ? `<button type="button" class="gg-plegar" data-plegar="${t.id}" aria-label="${cerradas.has(t.id) ? 'Mostrar' : 'Ocultar'} subtareas">${cerradas.has(t.id) ? '▸' : '▾'}</button>` : '<span class="gg-plegar-hueco"></span>'}
                        <span class="gg-nombre__texto" title="${escaparHtml(t.nombre)}">${t.es_hito ? '◆ ' : ''}${escaparHtml(t.nombre)}</span>
                    </span>
                    <span class="gg-resp" title="${escaparHtml(t.responsable_nombre)}">${t.responsable ? `<i style="background:${G.colorPersona(t.responsable)}">${G.iniciales(t.responsable_nombre)}</i>${escaparHtml(t.responsable_nombre.split(' ')[0])}` : '<span class="g-sub">—</span>'}</span>
                    <span>${G.fechaCorta(t.inicio)}</span>
                    <span class="${t.vencida ? 'g-vencida' : ''}">${G.fechaCorta(t.fin)}</span>
                    <span>${t.inicio ? t.duracion : '—'}</span>
                    <span class="gg-pct">${t.avance}%</span>
                </div>`).join('')}
            <div class="gg-fila gg-fila--nueva" style="height:${FILA}px">
                <span></span><input type="text" class="gg-nueva" placeholder="+ Agregar tarea y Enter…" maxlength="200" aria-label="Nueva tarea">
            </div>
            <div style="height:40px"></div>`;
        caja.querySelectorAll('.gg-fila[data-id]').forEach(f => {
            f.addEventListener('click', (e) => { if (!e.target.closest('[data-plegar]')) abrirTarea(Number(f.dataset.id)); });
            f.addEventListener('keydown', (e) => { if (e.key === 'Enter') abrirTarea(Number(f.dataset.id)); });
        });
        caja.querySelectorAll('[data-plegar]').forEach(b => b.addEventListener('click', () => {
            const set = colapsadas(proyecto.id);
            const id = Number(b.dataset.plegar);
            set.has(id) ? set.delete(id) : set.add(id);
            G.guardar(`colapsadas-${proyecto.id}`, [...set]);
            repintar();
        }));
        const nueva = caja.querySelector('.gg-nueva');
        nueva.addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || !nueva.value.trim()) return;
            const nombre = nueva.value;
            nueva.disabled = true;
            if (await crearTareaRapida({ nombre })) G.aviso(`Tarea «${nombre}» agregada: haz clic en su renglón del Gantt para ponerle fecha.`);
            nueva.disabled = false;
        });
    }

    function pintar(caja, proyecto, tareas, opciones) {
        const escala = opciones.escala || 'semana';
        const px = PX_DIA[escala];
        const filas = filasVisibles(proyecto, tareas, opciones.filtrado);
        const [desde, hasta] = rango(proyecto.tareas, escala);
        const ancho = (hasta - desde + 1) * px;
        const alto = Math.max(filas.length + 1, 6) * FILA + 40;
        hoyDia = G.hoy();
        xDe = (dia) => (dia - desde) * px;

        if (derecha && derecha.isConnected) { estado.scrollLeft = derecha.scrollLeft; estado.scrollTop = derecha.scrollTop; }
        caja.innerHTML = `
            <div class="gg">
                <div class="gg-izq"><div class="gg-tabla"></div></div>
                <div class="gg-der"><svg class="gg-svg-enc" width="${ancho}" height="${ENCABEZADO}"></svg>
                    <svg class="gg-svg" width="${ancho}" height="${alto}"></svg></div>
            </div>
            <div class="gg-leyenda">
                <span><i class="gg-m gg-m--barra" style="background:${escaparHtml(proyecto.color)}"></i>Tarea (más oscuro: avance)</span>
                <span><i class="gg-m gg-m--resumen"></i>Tarea resumen</span><span>◆ Hito</span>
                ${opciones.critica ? '<span><i class="gg-m gg-m--critica"></i>Ruta crítica (sin holgura)</span>' : ''}
                ${opciones.base ? `<span><i class="gg-m gg-m--base"></i>Línea base${proyecto.base_guardada_en ? '' : ' (aún no se guarda)'}</span>` : ''}
                <span class="g-sub">Arrastra una barra para moverla o su borde derecho para cambiar el fin. Clic: abrir.</span>
            </div>`;
        const izq = caja.querySelector('.gg-izq');
        derecha = caja.querySelector('.gg-der');
        tablaIzquierda(caja.querySelector('.gg-tabla'), proyecto, filas, opciones.filtrado);
        encabezado(caja.querySelector('.gg-svg-enc'), desde, hasta, px, escala);
        const svg = caja.querySelector('.gg-svg');

        // Fondo: renglones, fines de semana y hoy
        filas.forEach((t, i) => { if (i % 2) el('rect', { x: 0, y: i * FILA, width: ancho, height: FILA, class: 'gg-renglon' }, svg); });
        if (escala !== 'mes') {
            for (let d = desde; d <= hasta; d++) {
                if (!G.esHabil(d)) el('rect', { x: xDe(d), y: 0, width: px, height: alto, class: 'gg-libre' }, svg);
            }
        }
        el('line', { x1: xDe(hoyDia) + px / 2, y1: 0, x2: xDe(hoyDia) + px / 2, y2: alto, class: 'gg-hoy' }, svg);

        const defs = el('defs', {}, svg);
        const marca = el('marker', { id: 'ggFlecha', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto' }, defs);
        el('path', { d: 'M0,0 L8,4 L0,8 z', class: 'gg-flecha-punta' }, marca);
        const marcaCritica = el('marker', { id: 'ggFlechaCritica', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto' }, defs);
        el('path', { d: 'M0,0 L8,4 L0,8 z', class: 'gg-flecha-punta gg-flecha-punta--critica' }, marcaCritica);

        const fila = Object.fromEntries(filas.map((t, i) => [t.id, i]));
        const porId = Object.fromEntries(proyecto.tareas.map(t => [t.id, t]));
        const capaFlechas = el('g', {}, svg);
        const capaBarras = el('g', {}, svg);

        filas.forEach((t, i) => {
            const y = i * FILA;
            if (opciones.base && t.base_inicio && t.base_fin) {
                el('rect', { x: xDe(G.dia(t.base_inicio)), y: y + 26, width: Math.max(3, (G.dia(t.base_fin) - G.dia(t.base_inicio) + 1) * px),
                             height: 4, rx: 2, class: 'gg-base' }, capaBarras);
            }
            if (!t.inicio || !t.fin) return;
            const x0 = xDe(G.dia(t.inicio)), x1 = xDe(G.dia(t.fin) + 1);
            const g = el('g', { class: 'gg-tarea', 'data-id': t.id }, capaBarras);
            const titulo = el('title', {}, g);
            titulo.textContent = `${t.wbs} ${t.nombre}\n${G.fechaLarga(t.inicio)} → ${G.fechaLarga(t.fin)} · ${t.duracion} d hábiles\nAvance ${t.avance} %`
                + (t.responsable_nombre ? `\nResponsable: ${t.responsable_nombre}` : '')
                + (t.holgura !== null && t.holgura !== undefined ? `\nHolgura: ${t.holgura} d${t.holgura <= 0 ? ' (ruta crítica)' : ''}` : '')
                + (t.atraso ? `\nContra línea base: ${t.atraso > 0 ? '+' : ''}${t.atraso} d` : '');
            const critica = opciones.critica && t.critica;
            let finEtiqueta = x1;
            if (t.resumen) {
                el('path', { d: `M${x0},${y + 10} H${x1} V${y + 22} L${x1 - 6},${y + 16} H${x0 + 6} L${x0},${y + 22} Z`,
                             class: `gg-resumen ${critica ? 'gg-critica' : ''}` }, g);
                if (t.avance) el('rect', { x: x0, y: y + 10, width: (x1 - x0) * t.avance / 100, height: 4, class: 'gg-resumen-avance' }, g);
            } else if (t.es_hito) {
                const cx = x0 + px / 2;
                el('path', { d: `M${cx},${y + 8} L${cx + 9},${y + 17} L${cx},${y + 26} L${cx - 9},${y + 17} Z`,
                             class: `gg-hito ${critica ? 'gg-critica' : ''} ${t.avance >= 100 ? 'gg-hito--hecho' : ''}`, 'data-arrastre': 'mover' }, g);
                finEtiqueta = cx + 12;
            } else {
                const ancho = Math.max(4, x1 - x0);
                el('rect', { x: x0, y: y + 8, width: ancho, height: 18, rx: 4, class: `gg-barra ${critica ? 'gg-critica' : ''} ${t.vencida ? 'gg-barra--vencida' : ''}`,
                             style: critica ? '' : `fill:${proyecto.color}`, 'data-arrastre': 'mover' }, g);
                if (t.avance) el('rect', { x: x0, y: y + 8, width: ancho * t.avance / 100, height: 18, rx: 4, class: 'gg-avance', 'pointer-events': 'none' }, g);
                el('rect', { x: x0 + ancho - 7, y: y + 8, width: 9, height: 18, class: 'gg-asa', 'data-arrastre': 'fin' }, g);
            }
            const texto = el('text', { x: finEtiqueta + 6, y: y + 21, class: 'gg-etiqueta' }, g);
            texto.textContent = [t.es_hito ? t.nombre : t.responsable_nombre, t.avance && !t.resumen ? `${t.avance}%` : '',
                                 opciones.base && t.atraso > 0 ? `+${t.atraso} d` : ''].filter(Boolean).join(' · ');
            if (!t.resumen) conectarArrastre(g, t, px);
            else g.addEventListener('click', () => abrirTarea(t.id));
        });

        // Dependencias: del fin de la predecesora al inicio de la sucesora
        proyecto.dependencias.forEach(d => {
            const a = porId[d.predecesora], b = porId[d.sucesora];
            if (!(a && b && a.fin && b.inicio && d.predecesora in fila && d.sucesora in fila)) return;
            const x1 = a.es_hito ? xDe(G.dia(a.fin)) + px / 2 + 9 : xDe(G.dia(a.fin) + 1);
            const y1 = fila[a.id] * FILA + 17;
            const x2 = b.es_hito ? xDe(G.dia(b.inicio)) + px / 2 - 9 : xDe(G.dia(b.inicio));
            const y2 = fila[b.id] * FILA + 17;
            const baja = y2 > y1 ? 1 : -1;
            const camino = x2 - 10 >= x1 + 6
                ? `M${x1},${y1} H${x1 + 6} V${y2} H${x2}`
                : `M${x1},${y1} H${x1 + 6} V${y1 + baja * FILA / 2} H${x2 - 10} V${y2} H${x2}`;
            const critica = opciones.critica && a.critica && b.critica;
            el('path', { d: camino, class: `gg-flecha ${critica ? 'gg-flecha--critica' : ''}`,
                         'marker-end': `url(#${critica ? 'ggFlechaCritica' : 'ggFlecha'})` }, capaFlechas);
        });

        // Una tarea sin fechas se programa con un clic en su renglón (ese día, duración de 1 día)
        svg.addEventListener('click', (e) => {
            if (e.target.closest('.gg-tarea')) return;
            const caja = svg.getBoundingClientRect();
            const t = filas[Math.floor((e.clientY - caja.top) / FILA)];
            if (!t || t.resumen || t.inicio) return;
            const dia = desde + Math.floor((e.clientX - caja.left) / px);
            cambiarTarea(t.id, { inicio: G.texto(dia), fin: G.texto(dia) }, { silencioso: true });
        });

        // Desplazamiento: la tabla sigue al Gantt en vertical
        derecha.addEventListener('scroll', () => { izq.scrollTop = derecha.scrollTop; });
        izq.addEventListener('wheel', (e) => { if (!e.shiftKey) { derecha.scrollTop += e.deltaY; e.preventDefault(); } }, { passive: false });
        if (estado.scrollLeft !== null) { derecha.scrollLeft = estado.scrollLeft; derecha.scrollTop = estado.scrollTop; izq.scrollTop = estado.scrollTop; }
        else irAHoy();
    }

    // Arrastre: mover toda la barra o su borde derecho (fin), en días enteros
    function conectarArrastre(g, t, px) {
        g.addEventListener('pointerdown', (e) => {
            const tipo = e.target.getAttribute('data-arrastre');
            if (!tipo || e.button !== 0) return;
            e.preventDefault();
            const x0 = e.clientX;
            let dias = 0;
            const forma = g;
            forma.setPointerCapture(e.pointerId);
            forma.classList.add('gg-tarea--arrastrando');
            const barra = g.querySelector('.gg-barra');
            const anchoOriginal = barra ? Number(barra.getAttribute('width')) : 0;
            const pista = document.createElement('div');
            pista.className = 'gg-pista';
            document.body.appendChild(pista);
            const mover = (ev) => {
                dias = Math.round((ev.clientX - x0) / px);
                if (tipo === 'mover') forma.setAttribute('transform', `translate(${dias * px},0)`);
                else if (barra) barra.setAttribute('width', Math.max(px, anchoOriginal + dias * px));
                const ini = G.dia(t.inicio) + (tipo === 'mover' ? dias : 0);
                const fin = Math.max(G.dia(t.inicio), G.dia(t.fin) + dias);
                pista.textContent = tipo === 'mover' ? `Inicio ${G.fechaLarga(G.texto(ini))}` : `Fin ${G.fechaLarga(G.texto(fin))}`;
                pista.style.left = `${ev.clientX + 14}px`;
                pista.style.top = `${ev.clientY + 14}px`;
            };
            const soltar = async () => {
                forma.removeEventListener('pointermove', mover);
                forma.removeEventListener('pointerup', soltar);
                forma.removeEventListener('pointercancel', soltar);
                forma.classList.remove('gg-tarea--arrastrando');
                pista.remove();
                if (!dias) { abrirTarea(t.id); return; }
                if (tipo === 'mover') await cambiarTarea(t.id, { inicio: G.texto(G.dia(t.inicio) + dias) }, { silencioso: true });
                else await cambiarTarea(t.id, { fin: G.texto(Math.max(G.dia(t.inicio), G.dia(t.fin) + dias)) }, { silencioso: true });
            };
            forma.addEventListener('pointermove', mover);
            forma.addEventListener('pointerup', soltar);
            forma.addEventListener('pointercancel', soltar);
        });
    }

    function irAHoy() {
        if (!derecha || !xDe) return;
        derecha.scrollLeft = Math.max(0, xDe(G.hoy()) - derecha.clientWidth / 4);
    }

    return { pintar, irAHoy };
})();
