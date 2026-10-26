// static/core/js/graficas.js — Gráfica de líneas contra la edad (SVG propio: sin librerías, funciona sin internet).
//
//   graficaLineas(contenedor, {
//       series: [{ id, nombre, color, destacada, puntos: [{ x, y, estado: ''|'alerta'|'fuera', texto }] }],
//                                      // color null = lote de fondo (gris tenue, sin puntos)
//       vivo: { x, y, texto } | null,  // dato que se está capturando
//       curva: [[x, y], …],            // valor esperado por edad (línea punteada)
//       objetivo: número | null,       // valor esperado fijo
//       limites: { especificacion_min, especificacion_max, alerta_min, alerta_max },
//       banda: false,                  // banda P10–P90 y mediana de todas las series (para muchos lotes)
//       mostrarPuntos: true,           // puntos en las series de fondo (las destacadas siempre los llevan)
//       zoom: [x0, x1] | null,         // rango de edades visible
//       alZoom: (rango|null) => {},    // si se da, arrastrar acerca y doble clic restablece
//       alElegirSerie: (id) => {},     // clic sobre una línea o un punto
//       textoPunto: (serie, punto) => html,   // detalle del punto (si no trae `texto`)
//       textoX: 'Edad del lote (h)', alto: 260,
//       tema: 'oscuro' | 'claro',      // claro = fondo blanco (usa COLORES_SERIES_CLARO para las series)
//   });
//
// Al pasar el cursor: guía vertical con la edad, la serie más cercana se ilumina y una ficha muestra el punto.
// Estilos en static/core/css/graficas.css. Devuelve { curvaVisible, rango: [x0, x1] }.

(function () {
    const SVG = 'http://www.w3.org/2000/svg';
    const numero = (v) => (v === null || v === undefined || v === '') ? null : Number(String(v).replace(',', '.'));

    // Colores de los lotes destacados en orden fijo (paleta validada para fondo oscuro); nunca se reciclan
    window.COLORES_SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
    // Los mismos tonos, en los pasos validados para fondo blanco
    window.COLORES_SERIES_CLARO = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
    const NEUTRO = { oscuro: { anillo: '#f8fafc', linea: '#e2e8f0', ficha: '#94a3b8' }, claro: { anillo: '#0f172a', linea: '#334155', ficha: '#64748b' } };

    window.numeroCorto = (v) => Math.abs(v) >= 1000 ? Number(v).toFixed(0) : Number(Number(v).toPrecision(4)).toString();
    const corto = window.numeroCorto;

    function marcas(min, max, cuantas) {
        const paso0 = (max - min) / cuantas || 1;
        const base = Math.pow(10, Math.floor(Math.log10(paso0)));
        const paso = [1, 2, 2.5, 5, 10].map(m => m * base).find(p => p >= paso0) || paso0;
        const lista = [];
        for (let v = Math.ceil(min / paso) * paso; v <= max + paso * 1e-9; v += paso) lista.push(Number(v.toFixed(10)));
        return lista;
    }

    function lineasLimite(lim) {
        lim = lim || {};
        return [
            ['especificacion_max', 'Esp. máx', 'fuera'], ['especificacion_min', 'Esp. mín', 'fuera'],
            ['alerta_max', 'Alerta máx', 'alerta'], ['alerta_min', 'Alerta mín', 'alerta'],
        ].filter(([c]) => numero(lim[c]) !== null).map(([c, etiqueta, tipo]) => ({ y: numero(lim[c]), etiqueta, tipo }));
    }

    // Valor de una serie (ordenada por x) en la edad x, solo dentro de su rango de edades
    function interpolarSerie(orden, x) {
        if (!orden.length || x < orden[0].x || x > orden[orden.length - 1].x) return null;
        let i = 1;
        while (i < orden.length && orden[i].x < x) i++;
        if (i >= orden.length) return orden[orden.length - 1].y;
        const a = orden[i - 1], b = orden[i];
        return b.x === a.x ? b.y : a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x);
    }

    function cuantil(ordenados, q) {
        const pos = (ordenados.length - 1) * q;
        const base = Math.floor(pos);
        const resto = pos - base;
        return ordenados[base + 1] !== undefined ? ordenados[base] + resto * (ordenados[base + 1] - ordenados[base]) : ordenados[base];
    }

    // Banda P10–P90 y mediana sobre una rejilla de edades (con al menos 3 series con dato en cada edad)
    function calcularBanda(seriesOrdenadas, xMin, xMax) {
        const pasos = 90;
        const banda = [];
        for (let k = 0; k <= pasos; k++) {
            const x = xMin + (xMax - xMin) * k / pasos;
            const valores = seriesOrdenadas.map(o => interpolarSerie(o, x)).filter(v => v !== null).sort((a, b) => a - b);
            banda.push(valores.length >= 3 ? { x, p10: cuantil(valores, 0.1), p50: cuantil(valores, 0.5), p90: cuantil(valores, 0.9), n: valores.length } : null);
        }
        return banda;
    }

    window.graficaLineas = function (contenedor, opciones) {
        const {
            series = [], vivo = null, curva = [], objetivo = null, limites = null, banda = false, mostrarPuntos = true,
            zoom = null, alZoom = null, alElegirSerie = null, textoPunto = null, textoX = 'Edad (h)', alto = 260, tema = 'oscuro',
        } = opciones;
        const neutro = NEUTRO[tema] || NEUTRO.oscuro;
        const lineas = lineasLimite(limites);
        const esperado = numero(objetivo);
        const puntosCurva = (curva || []).map(([x, y]) => ({ x: Number(x), y: Number(y) }));
        const actual = vivo && Number.isFinite(vivo.y) && vivo.x !== null && vivo.x !== undefined ? vivo : null;
        const ordenadas = series.map(s => ({ ...s, orden: [...s.puntos].sort((a, b) => a.x - b.x) }));

        // Dominio de edades: el zoom, o lo que abarcan los datos; sin datos, la curva esperada
        const xsDatos = [...ordenadas.flatMap(s => s.puntos.map(q => q.x)), ...(actual ? [actual.x] : [])];
        let xMin, xMax;
        if (zoom) {
            [xMin, xMax] = zoom;
        } else if (xsDatos.length) {
            xMin = Math.min(0, ...xsDatos);
            xMax = Math.max(...xsDatos);
            xMax = Math.max(xMax + Math.max(6, (xMax - xMin) * 0.06), 24);
        } else if (puntosCurva.length) {
            xMin = Math.min(0, ...puntosCurva.map(q => q.x));
            xMax = Math.max(...puntosCurva.map(q => q.x), 24);
        } else {
            xMin = 0; xMax = 24;
        }
        const dentro = (x) => x >= xMin && x <= xMax;
        const curvaVisible = puntosCurva.filter((q, i) => dentro(q.x)
            || (puntosCurva[i + 1] && puntosCurva[i + 1].x >= xMin && q.x < xMin)
            || (puntosCurva[i - 1] && puntosCurva[i - 1].x <= xMax && q.x > xMax));
        const datosBanda = banda && ordenadas.length >= 3 ? calcularBanda(ordenadas.map(s => s.orden), xMin, xMax) : null;

        // Rango de valores: lo visible (con zoom, solo datos y curva para ver el detalle)
        const ysDatos = [...ordenadas.flatMap(s => s.puntos.filter(q => dentro(q.x)).map(q => q.y)),
                         ...(actual && dentro(actual.x) ? [actual.y] : []), ...curvaVisible.map(q => q.y)];
        const ys = zoom && ysDatos.length ? ysDatos : [...ysDatos, ...lineas.map(l => l.y), ...(esperado !== null ? [esperado] : [])];
        if (!ys.length) {
            contenedor.innerHTML = '<div class="grafica-vacia">Sin datos en este rango de edades.</div>';
            return { curvaVisible: false, rango: [xMin, xMax] };
        }
        let yMin = Math.min(...ys), yMax = Math.max(...ys);
        const holgura = (yMax - yMin) * 0.1 || Math.abs(yMax) * 0.1 || 1;
        yMin -= holgura; yMax += holgura;

        const ancho = Math.max(contenedor.clientWidth || 0, 280);
        const m = { izq: 50, der: 16, arr: 12, aba: 36 };
        const anchoUtil = ancho - m.izq - m.der, altoUtil = alto - m.arr - m.aba;
        const X = (v) => m.izq + (v - xMin) / (xMax - xMin) * anchoUtil;
        const Y = (v) => alto - m.aba - (v - yMin) / (yMax - yMin) * altoUtil;
        const aEdad = (px) => xMin + (px - m.izq) / anchoUtil * (xMax - xMin);
        const el = (tag, attrs, padre) => {
            const nodo = document.createElementNS(SVG, tag);
            Object.entries(attrs).forEach(([k, v]) => nodo.setAttribute(k, v));
            if (padre) padre.appendChild(nodo);
            return nodo;
        };
        const camino = (pts) => pts.map((q, i) => `${i ? 'L' : 'M'}${X(q.x).toFixed(1)},${Y(q.y).toFixed(1)}`).join('');

        const svg = el('svg', { viewBox: `0 0 ${ancho} ${alto}`, width: ancho, height: alto, class: `tg-svg${tema === 'claro' ? ' tg-svg--claro' : ''}`, role: 'img' });
        const uid = Math.random().toString(36).slice(2);
        const defs = el('defs', {}, svg);
        el('rect', { x: m.izq, y: m.arr, width: anchoUtil, height: altoUtil }, el('clipPath', { id: `clip-${uid}` }, defs));
        const brillo = el('filter', { id: `brillo-${uid}`, x: '-20%', y: '-20%', width: '140%', height: '140%' }, defs);
        el('feGaussianBlur', { stdDeviation: 2.2, result: 'b' }, brillo);
        const mezcla = el('feMerge', {}, brillo);
        el('feMergeNode', { in: 'b' }, mezcla);
        el('feMergeNode', { in: 'SourceGraphic' }, mezcla);

        el('rect', { x: m.izq, y: m.arr, width: anchoUtil, height: altoUtil, rx: 6, class: 'tg-fondo' }, svg);

        // Rejilla y ejes (recesivos)
        marcas(yMin, yMax, 5).forEach(v => {
            el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(v), y2: Y(v), class: 'tg-rejilla' }, svg);
            el('text', { x: m.izq - 7, y: Y(v) + 3, class: 'tg-eje', 'text-anchor': 'end' }, svg).textContent = corto(v);
        });
        marcas(xMin, xMax, Math.max(3, Math.floor(anchoUtil / 70))).forEach(v => {
            el('line', { x1: X(v), x2: X(v), y1: m.arr, y2: alto - m.aba, class: 'tg-rejilla tg-rejilla--v' }, svg);
            el('text', { x: X(v), y: alto - m.aba + 15, class: 'tg-eje', 'text-anchor': 'middle' }, svg).textContent = corto(v);
        });
        el('text', { x: m.izq + anchoUtil / 2, y: alto - 4, class: 'tg-eje tg-eje--titulo', 'text-anchor': 'middle' }, svg).textContent = textoX;

        const zona = el('g', { 'clip-path': `url(#clip-${uid})` }, svg);
        lineas.forEach(l => {
            el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(l.y), y2: Y(l.y), class: `tg-limite tg-limite--${l.tipo}` }, zona);
            el('text', { x: ancho - m.der - 4, y: Y(l.y) - 4, class: 'tg-etiqueta', 'text-anchor': 'end' }, zona).textContent = `${l.etiqueta} ${corto(l.y)}`;
        });
        if (esperado !== null) {
            el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(esperado), y2: Y(esperado), class: 'tg-esperado' }, zona);
            el('text', { x: m.izq + 5, y: Y(esperado) - 4, class: 'tg-etiqueta' }, zona).textContent = `Esperado ${corto(esperado)}`;
        }

        // Banda de los lotes (tramos continuos donde hay al menos 3 lotes)
        if (datosBanda) {
            let tramo = [];
            const cerrar = () => {
                if (tramo.length > 1) {
                    const arriba = tramo.map(b => ({ x: b.x, y: b.p90 }));
                    const abajo = [...tramo].reverse().map(b => ({ x: b.x, y: b.p10 }));
                    el('path', { d: `${camino(arriba)}${camino(abajo).replace('M', 'L')}Z`, class: 'tg-banda' }, zona);
                    el('path', { d: camino(tramo.map(b => ({ x: b.x, y: b.p50 }))), class: 'tg-mediana' }, zona);
                }
                tramo = [];
            };
            datosBanda.forEach(b => { if (b) tramo.push(b); else cerrar(); });
            cerrar();
        }
        if (curvaVisible.length > 1) el('path', { d: camino(curvaVisible), class: 'tg-curva' }, zona);

        // Series: primero las de fondo (gris tenue), encima las destacadas (con color y brillo)
        const fondo = el('g', { class: 'tg-capa-fondo' }, zona);
        const frente = el('g', {}, zona);
        const unaSola = ordenadas.filter(s => s.color).length === 1 && !datosBanda && ordenadas.length === 1;
        ordenadas.forEach(s => {
            if (s.orden.length < 2) return;
            if (!s.color) {
                el('path', { d: camino(s.orden), class: 'tg-serie tg-serie--fondo' }, fondo);
                return;
            }
            if (unaSola) {
                const grad = el('linearGradient', { id: `area-${uid}`, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
                el('stop', { offset: '0%', 'stop-color': s.color, 'stop-opacity': 0.28 }, grad);
                el('stop', { offset: '100%', 'stop-color': s.color, 'stop-opacity': 0 }, grad);
                const base = Y(yMin);
                el('path', { d: `${camino(s.orden)}L${X(s.orden[s.orden.length - 1].x)},${base}L${X(s.orden[0].x)},${base}Z`, fill: `url(#area-${uid})` }, frente);
            }
            el('path', { d: camino(s.orden), class: 'tg-serie', style: `stroke:${s.color}`, filter: `url(#brillo-${uid})` }, frente);
        });
        if (actual && ordenadas.length === 1 && ordenadas[0].orden.length) {
            const previos = ordenadas[0].orden.filter(q => q.x <= actual.x);
            const ultimo = previos.length ? previos[previos.length - 1] : ordenadas[0].orden[0];
            el('line', { x1: X(ultimo.x), y1: Y(ultimo.y), x2: X(actual.x), y2: Y(actual.y), class: 'tg-enlace' }, frente);
        }

        // Puntos (las series de fondo solo si se pide) y su posición en pantalla para buscar el más cercano
        const cercanos = [];
        ordenadas.forEach(s => {
            const conPunto = s.color || mostrarPuntos;
            s.puntos.forEach(q => {
                if (!dentro(q.x)) return;
                const px = X(q.x), py = Y(q.y);
                cercanos.push({ px, py, q, s });
                if (!conPunto) return;
                el('circle', {
                    cx: px, cy: py, r: s.color ? 4 : 2.6,
                    class: `tg-punto${s.color ? '' : ' tg-punto--fondo'}${q.estado ? ` tg-punto--${q.estado}` : ''}`,
                    style: s.color ? `fill:${s.color}` : '',
                }, s.color ? frente : fondo);
            });
        });
        // Nombre de cada serie destacada al final de su línea (sin encimarse); el texto va en tinta, el color en la marca
        const etiquetas = ordenadas.filter(s => s.color && s.nombre && ordenadas.length > 1).map(s => {
            const visibles = s.orden.filter(q => dentro(q.x));
            if (!visibles.length) return null;
            const ultimo = visibles[visibles.length - 1];
            return { s, x: X(ultimo.x), y: Y(ultimo.y) };
        }).filter(Boolean).sort((a, b) => a.y - b.y);
        for (let i = 1; i < etiquetas.length; i++) etiquetas[i].y = Math.max(etiquetas[i].y, etiquetas[i - 1].y + 12);
        etiquetas.forEach(e => {
            const derecha = e.x + 70 > ancho - m.der;
            const tx = derecha ? e.x - 9 : e.x + 9;
            el('rect', { x: derecha ? tx - 3 : tx, y: e.y - 3, width: 3, height: 6, rx: 1, fill: e.s.color }, svg);
            el('text', { x: derecha ? tx - 6 : tx + 6, y: e.y + 3.5, class: 'tg-nombre', 'text-anchor': derecha ? 'end' : 'start' }, svg).textContent = e.s.nombre;
        });

        if (actual) {
            el('circle', { cx: X(actual.x), cy: Y(actual.y), r: 6.5, class: 'tg-punto tg-punto--vivo' }, svg);
            cercanos.push({ px: X(actual.x), py: Y(actual.y), q: actual, s: null });
        }

        // Capa de interacción: guía vertical, serie iluminada, ficha, zoom por arrastre
        const guia = el('g', { class: 'tg-guia', visibility: 'hidden' }, svg);
        const guiaLinea = el('line', { y1: m.arr, y2: alto - m.aba, class: 'tg-guia__linea' }, guia);
        const guiaFondo = el('rect', { y: alto - m.aba + 3, height: 16, rx: 8, class: 'tg-guia__fondo' }, guia);
        const guiaTexto = el('text', { y: alto - m.aba + 14.5, class: 'tg-guia__texto', 'text-anchor': 'middle' }, guia);
        const iluminada = el('path', { class: 'tg-iluminada', visibility: 'hidden' }, zona);
        const anillo = el('circle', { r: 7, class: 'tg-anillo', visibility: 'hidden' }, svg);
        const seleccion = el('rect', { y: m.arr, height: altoUtil, class: 'tg-seleccion', visibility: 'hidden' }, svg);
        const capa = el('rect', { x: m.izq, y: m.arr, width: anchoUtil, height: altoUtil, class: `tg-capa${alZoom ? ' tg-capa--zoom' : ''}` }, svg);

        const ficha = document.createElement('div');
        ficha.className = `tg-ayuda${tema === 'claro' ? ' tg-ayuda--claro' : ''}`;
        ficha.hidden = true;

        let arrastre = null, pendiente = null, cercanoActual = null;
        const posicion = (evento) => {
            const caja = svg.getBoundingClientRect();
            return { x: (evento.clientX - caja.left) * (ancho / caja.width), y: (evento.clientY - caja.top) * (alto / caja.height) };
        };
        const buscarCercano = (p) => {
            let mejor = null, distancia = 26 * 26;
            for (const c of cercanos) {
                const d = (c.px - p.x) ** 2 + (c.py - p.y) ** 2;
                if (d < distancia) { distancia = d; mejor = c; }
            }
            return mejor;
        };
        const ocultar = () => {
            [guia, iluminada, anillo].forEach(n => n.setAttribute('visibility', 'hidden'));
            ficha.hidden = true;
            cercanoActual = null;
        };
        const mover = (p) => {
            const px = Math.min(Math.max(p.x, m.izq), m.izq + anchoUtil);
            guia.setAttribute('visibility', 'visible');
            guiaLinea.setAttribute('x1', px); guiaLinea.setAttribute('x2', px);
            guiaTexto.setAttribute('x', px);
            guiaTexto.textContent = `${corto(aEdad(px))} h`;
            const anchoPastilla = guiaTexto.textContent.length * 6 + 14;
            guiaFondo.setAttribute('x', px - anchoPastilla / 2); guiaFondo.setAttribute('width', anchoPastilla);

            if (arrastre) {
                const x0 = Math.min(arrastre, px), x1 = Math.max(arrastre, px);
                seleccion.setAttribute('x', x0); seleccion.setAttribute('width', x1 - x0); seleccion.setAttribute('visibility', 'visible');
                return;
            }
            const c = buscarCercano(p);
            cercanoActual = c;
            if (!c) {
                iluminada.setAttribute('visibility', 'hidden'); anillo.setAttribute('visibility', 'hidden'); ficha.hidden = true;
                return;
            }
            anillo.setAttribute('cx', c.px); anillo.setAttribute('cy', c.py); anillo.setAttribute('visibility', 'visible');
            anillo.style.stroke = c.s && c.s.color ? c.s.color : neutro.anillo;
            if (c.s && c.s.orden.length > 1) {
                iluminada.setAttribute('d', camino(c.s.orden));
                iluminada.style.stroke = c.s.color || neutro.linea;
                iluminada.setAttribute('visibility', 'visible');
            } else {
                iluminada.setAttribute('visibility', 'hidden');
            }
            ficha.innerHTML = (c.q.texto || (textoPunto && c.s ? textoPunto(c.s, c.q) : `${corto(c.q.y)} a ${corto(c.q.x)} h`))
                + (c.s && alElegirSerie ? `<div class="tg-ayuda__pista">${c.s.destacada ? 'Clic para quitar el color' : 'Clic para destacar'}</div>` : '');
            ficha.style.setProperty('--tg-color', c.s && c.s.color ? c.s.color : neutro.ficha);
            ficha.hidden = false;
            const izquierda = c.px + 14 + 220 > ancho ? c.px - 14 - 220 : c.px + 14;
            ficha.style.left = `${Math.max(izquierda, 0) / ancho * 100}%`;
            ficha.style.top = `${Math.max(c.py - 30, 0)}px`;
        };
        capa.addEventListener('pointermove', (e) => {
            pendiente = posicion(e);
            requestAnimationFrame(() => { if (pendiente) { mover(pendiente); pendiente = null; } });
        });
        capa.addEventListener('pointerleave', () => { if (!arrastre) ocultar(); });
        capa.addEventListener('pointerdown', (e) => {
            if (!alZoom || e.button !== 0) return;
            arrastre = Math.min(Math.max(posicion(e).x, m.izq), m.izq + anchoUtil);
            capa.setPointerCapture(e.pointerId);
        });
        capa.addEventListener('pointerup', (e) => {
            const p = posicion(e);
            if (arrastre !== null) {
                const px = Math.min(Math.max(p.x, m.izq), m.izq + anchoUtil);
                const x0 = Math.min(arrastre, px), x1 = Math.max(arrastre, px);
                arrastre = null;
                seleccion.setAttribute('visibility', 'hidden');
                if (x1 - x0 > 12) { alZoom([aEdad(x0), aEdad(x1)]); return; }
            }
            mover(p);   // en pantalla táctil, tocar muestra la ficha
            if (e.pointerType === 'mouse' && cercanoActual && cercanoActual.s && alElegirSerie) alElegirSerie(cercanoActual.s.id);
        });
        capa.addEventListener('dblclick', () => { if (alZoom && zoom) alZoom(null); });

        contenedor.innerHTML = '';
        contenedor.appendChild(svg);
        contenedor.appendChild(ficha);
        return { curvaVisible: curvaVisible.length > 1, rango: [xMin, xMax] };
    };

    // Elementos de leyenda (HTML) para lo que se dibujó
    window.leyendaGrafica = function ({ series = [], fondo = 0, banda = false, vivo = false, curva = false, objetivo = false, limites = null }) {
        const items = series.map(s => `<span><i class="tg-l" style="border-color:${s.color}"></i>${s.etiqueta}</span>`);
        const tipos = new Set(lineasLimite(limites).map(l => l.tipo));
        if (fondo) items.push(`<span><i class="tg-l tg-l--fondo"></i>${fondo} lote${fondo === 1 ? '' : 's'} más</span>`);
        if (banda) items.push('<span><i class="tg-l tg-l--banda"></i>P10–P90 y mediana</span>');
        if (vivo) items.push('<span><i class="tg-l tg-l--vivo"></i>Valor actual</span>');
        if (curva) items.push('<span><i class="tg-l tg-l--curva"></i>Curva esperada</span>');
        if (objetivo) items.push('<span><i class="tg-l tg-l--esperado"></i>Esperado fijo</span>');
        if (tipos.has('fuera')) items.push('<span><i class="tg-l tg-l--fuera"></i>Especificación</span>');
        if (tipos.has('alerta')) items.push('<span><i class="tg-l tg-l--alerta"></i>Alerta</span>');
        return items.join('');
    };
})();
