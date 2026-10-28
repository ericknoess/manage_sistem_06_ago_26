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
//       tipoX: 'numero' | 'fecha',     // fecha: x en segundos epoch; marcas y guía con fecha y hora
//       rangoX: [x0, x1] | null,       // rango fijo (gráficas apiladas alineadas); el zoom lo sustituye
//       grupoGuia: 'nombre',           // las gráficas del mismo grupo mueven juntas su guía vertical
//       animar: false,                 // traza las líneas al dibujar (no en redibujados frecuentes)
//       rangoY: [y0, y1] | null,       // rango de valores fijo y exacto (sin zoom): los datos fuera se marcan ▲/▼ en el borde
//       escalaX / escalaY: { min, max, paso } | null,   // escala manual: cualquiera vacío = automático; `paso` = distancia
//                                      // entre marcas (si da más de 60 marcas se usa la automática). El zoom la sustituye.
//       ejesY: [{ color, titulo, vMin, vMax }] | null,   // ejes múltiples (hasta 4, alternando izquierda y derecha):
//                                      // las series vienen escaladas a 0–100 y cada eje muestra su valor real (vMin → vMax)
//   });
//   Una serie con `tenue: true` y color se dibuja delgada y transparente en su color (gráficas superpuestas).
//   Una serie con `trazo` (stroke-dasharray, ver TRAZOS_SERIES) se dibuja con ese tipo de línea: en las gráficas
//   superpuestas el color es el parámetro y el trazo distingue a cada lote destacado; `marca` (MARCAS_SERIES:
//   circulo, cuadro, triangulo, rombo) da a sus puntos esa figura, con contorno marcado.
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
    // Tipos de trazo en orden fijo (continuo, guiones, puntos, guion-punto); con más de 4 ya no se distinguen
    window.TRAZOS_SERIES = ['', '9 4', '1.5 4', '10 4 1.5 4'];
    // Figura de los puntos, en el mismo orden que los trazos: un lote se reconoce por su línea y por sus puntos.
    // Se alternan rellenas (contorno oscuro) y huecas (borde grueso de color) para separarlas aún más.
    window.MARCAS_SERIES = ['circulo', 'cuadro-hueco', 'triangulo', 'rombo-hueco'];
    // Camino SVG de una figura centrada en (x, y) con "radio" r (misma área visual aproximada)
    window.caminoMarca = function (tipo, x, y, r) {
        const f = (n) => n.toFixed(1);
        tipo = String(tipo).replace('-hueco', '');
        if (tipo === 'cuadro') { const l = r * 0.9; return `M${f(x - l)},${f(y - l)}h${f(2 * l)}v${f(2 * l)}h${f(-2 * l)}Z`; }
        if (tipo === 'triangulo') { const l = r * 1.3; return `M${f(x)},${f(y - l)}L${f(x + l * 0.95)},${f(y + l * 0.7)}L${f(x - l * 0.95)},${f(y + l * 0.7)}Z`; }
        if (tipo === 'rombo') { const l = r * 1.3; return `M${f(x)},${f(y - l)}L${f(x + l)},${f(y)}L${f(x)},${f(y + l)}L${f(x - l)},${f(y)}Z`; }
        return `M${f(x - r)},${f(y)}a${f(r)},${f(r)} 0 1,0 ${f(2 * r)},0a${f(r)},${f(r)} 0 1,0 ${f(-2 * r)},0Z`;
    };
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

    // Fechas (x en segundos epoch): marcas en pasos "redondos" de horas o días
    const fechaCorta = (seg) => {
        const d = new Date(seg * 1000);
        const dos = (n) => String(n).padStart(2, '0');
        return `${dos(d.getDate())}/${dos(d.getMonth() + 1)} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
    };
    function marcasFecha(min, max, cuantas) {
        const H = 3600, D = 86400;
        const pasos = [H, 2 * H, 3 * H, 6 * H, 12 * H, D, 2 * D, 7 * D, 14 * D, 30 * D, 90 * D];
        const paso = pasos.find(p => (max - min) / p <= cuantas) || pasos[pasos.length - 1];
        const desfase = new Date().getTimezoneOffset() * 60;   // marcas en horas locales redondas
        const lista = [];
        for (let v = Math.ceil((min - desfase) / paso) * paso + desfase; v <= max; v += paso) lista.push(v);
        return lista;
    }
    window.fechaCortaGrafica = fechaCorta;

    // Marcas cada `paso` (escala manual); sin paso válido, las automáticas
    function marcasPaso(min, max, paso, cuantas) {
        const p = numero(paso);
        if (p && p > 0 && (max - min) / p <= 60) {
            const lista = [];
            for (let k = Math.ceil(min / p - 1e-9); k * p <= max + p * 1e-9; k++) lista.push(Number((k * p).toFixed(10)));
            return lista;
        }
        return marcas(min, max, cuantas);
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
            tipoX = 'numero', rangoX = null, grupoGuia = null, animar = false, ejesY = null, rangoY = null, escalaX = null, escalaY = null,
        } = opciones;
        const textoEjeX = tipoX === 'fecha' ? fechaCorta : (v) => `${corto(v)} h`;
        const neutro = NEUTRO[tema] || NEUTRO.oscuro;
        const lineas = lineasLimite(limites);
        const esperado = numero(objetivo);
        const puntosCurva = (curva || []).map(([x, y]) => ({ x: Number(x), y: Number(y) }));
        const actual = vivo && Number.isFinite(vivo.y) && vivo.x !== null && vivo.x !== undefined ? vivo : null;
        const ordenadas = series.map(s => ({ ...s, orden: [...s.puntos].sort((a, b) => a.x - b.x) }));

        // Dominio de edades: el zoom, o lo que abarcan los datos; sin datos, la curva esperada
        const xsDatos = [...ordenadas.flatMap(s => s.puntos.map(q => q.x)), ...(actual ? [actual.x] : [])];
        let xMin, xMax;
        if (zoom || rangoX) {
            [xMin, xMax] = zoom || rangoX;
        } else if (xsDatos.length && tipoX === 'fecha') {
            xMin = Math.min(...xsDatos);
            xMax = Math.max(...xsDatos);
            const margen = Math.max(1800, (xMax - xMin) * 0.04);
            xMin -= margen; xMax += margen;
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
        if (escalaX && !zoom && tipoX !== 'fecha') {
            const a = numero(escalaX.min), b = numero(escalaX.max);
            if ((b ?? xMax) > (a ?? xMin)) { xMin = a ?? xMin; xMax = b ?? xMax; }
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
        // Con muchos lotes, un valor atípico de un lote en gris no aplasta a los demás: la escala llega hasta un margen
        // sobre el P2–P98 y ese dato queda marcado en el borde (▲/▼). Destacados, límites, curva y valor actual siempre caben.
        let recorte = null;
        const ejes = (ejesY || []).slice(0, 4);
        if (!zoom && !ejes.length && ordenadas.length >= 5 && ysDatos.length >= 30) {
            const orden = [...ysDatos].sort((a, b) => a - b);
            const p02 = cuantil(orden, 0.02), p98 = cuantil(orden, 0.98);
            const ancho98 = (p98 - p02) || Math.abs(p98) * 0.1 || 1;
            const fijos = [...ordenadas.filter(s => s.color && !s.tenue).flatMap(s => s.puntos.filter(q => dentro(q.x)).map(q => q.y)),
                           ...(actual ? [actual.y] : []), ...curvaVisible.map(q => q.y), ...lineas.map(l => l.y),
                           ...(esperado !== null ? [esperado] : [])];
            const techo = Math.max(p98 + ancho98 * 0.6, ...fijos), piso = Math.min(p02 - ancho98 * 0.6, ...fijos);
            if (yMax > techo || yMin < piso) {
                recorte = { arriba: yMax > techo, abajo: yMin < piso };
                yMax = Math.min(yMax, techo); yMin = Math.max(yMin, piso);
            }
        }
        if (rangoY && !zoom) {
            const [y0, y1] = rangoY;
            if (yMax > y1 || yMin < y0) recorte = { arriba: yMax > y1, abajo: yMin < y0 };
            yMin = y0; yMax = y1;
        } else {
            const holgura = (yMax - yMin) * 0.1 || Math.abs(yMax) * 0.1 || 1;
            yMin -= holgura; yMax += holgura;
        }
        if (escalaY && !zoom) {   // escala manual: los datos fuera del rango se marcan en el borde
            const a = numero(escalaY.min), b = numero(escalaY.max);
            const nMin = a ?? yMin, nMax = b ?? yMax;
            if (nMax > nMin && (a !== null || b !== null)) {
                if (ysDatos.some(v => v > nMax || v < nMin)) recorte = recorte || { arriba: true, abajo: true };
                yMin = nMin; yMax = nMax;
            }
        }

        const ancho = Math.max(contenedor.clientWidth || 0, 280);
        const ANCHO_EJE = 60;   // cada eje adicional ocupa esta franja a su lado
        const m = ejes.length
            ? { izq: 6 + Math.ceil(ejes.length / 2) * ANCHO_EJE, der: 6 + Math.max(Math.floor(ejes.length / 2) * ANCHO_EJE, 10), arr: ejes.length > 2 ? 40 : 28, aba: 36 }
            : { izq: 50, der: 16, arr: 12, aba: 36 };
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
        // Línea suave que pasa por cada dato sin inventar picos ni valles (interpolación monótona, Fritsch–Butland)
        const suave = (pts) => {
            const p = pts.map(q => [X(q.x), Y(q.y)]);
            if (p.length < 3) return camino(pts);
            const n = p.length;
            const d = [];   // pendiente de cada tramo; null si es un salto vertical (misma edad)
            for (let i = 0; i < n - 1; i++) {
                const dx = p[i + 1][0] - p[i][0];
                d.push(dx > 0.01 ? (p[i + 1][1] - p[i][1]) / dx : null);
            }
            const t = p.map((_, i) => {
                const a = i ? d[i - 1] : null, b = i < n - 1 ? d[i] : null;
                if (a === null || b === null) return a ?? b ?? 0;
                return a * b > 0 ? 2 * a * b / (a + b) : 0;
            });
            let ruta = `M${p[0][0].toFixed(1)},${p[0][1].toFixed(1)}`;
            for (let i = 0; i < n - 1; i++) {
                const [x0, y0] = p[i], [x1, y1] = p[i + 1];
                if (d[i] === null) { ruta += `L${x1.toFixed(1)},${y1.toFixed(1)}`; continue; }
                const h = (x1 - x0) / 3;
                ruta += `C${(x0 + h).toFixed(1)},${(y0 + t[i] * h).toFixed(1)} ${(x1 - h).toFixed(1)},${(y1 - t[i + 1] * h).toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
            }
            return ruta;
        };

        const svg = el('svg', { viewBox: `0 0 ${ancho} ${alto}`, width: ancho, height: alto, class: `tg-svg${tema === 'claro' ? ' tg-svg--claro' : ''}${animar ? ' tg-svg--anima' : ''}`, role: 'img' });
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
        if (ejes.length) {
            // Ejes múltiples: el 1.º a la izquierda, el 2.º a la derecha, el 3.º afuera del 1.º…; la rejilla sigue al primero
            ejes.forEach((e, i) => {
                const izq = i % 2 === 0, nivel = Math.floor(i / 2);
                const xEje = izq ? m.izq - nivel * ANCHO_EJE : ancho - m.der + nivel * ANCHO_EJE;
                const lado = izq ? -1 : 1;
                const real = (v) => e.vMin + v / 100 * (e.vMax - e.vMin);
                const norma = (r) => e.vMax > e.vMin ? (r - e.vMin) / (e.vMax - e.vMin) * 100 : 50;
                el('line', { x1: xEje, x2: xEje, y1: m.arr, y2: alto - m.aba, class: 'tg-eje-y', style: `stroke:${e.color}` }, svg);
                (e.vMax > e.vMin ? marcasPaso(real(yMin), real(yMax), e.paso, 5) : [e.vMin]).forEach(r => {
                    const y = Y(norma(r));
                    if (y < m.arr - 0.5 || y > alto - m.aba + 0.5) return;
                    if (i === 0) el('line', { x1: m.izq, x2: ancho - m.der, y1: y, y2: y, class: 'tg-rejilla' }, svg);
                    el('line', { x1: xEje, x2: xEje + lado * 4, y1: y, y2: y, class: 'tg-eje-y', style: `stroke:${e.color}` }, svg);
                    el('text', { x: xEje + lado * 6, y: y + 3, class: 'tg-eje', 'text-anchor': izq ? 'end' : 'start' }, svg).textContent = corto(r);
                });
                // Título corto arriba del eje, con un punto de su color (el nombre completo va en la leyenda)
                // (los ejes exteriores, un renglón más arriba para no encimarse con los interiores)
                const centro = xEje + lado * (ANCHO_EJE / 2 - 2), yTitulo = m.arr - 9.5 - nivel * 13;
                el('circle', { cx: centro - (e.titulo.length * 2.9) - 6, cy: yTitulo - 4, r: 3.5, fill: e.color }, svg);
                el('text', { x: centro, y: yTitulo, class: 'tg-eje tg-eje--titulo', 'text-anchor': 'middle' }, svg).textContent = e.titulo;
                if (nivel) el('line', { x1: xEje, x2: xEje, y1: yTitulo + 3, y2: m.arr, class: 'tg-eje-y', style: `stroke:${e.color}`, opacity: 0.5 }, svg);
            });
        } else {
            marcasPaso(yMin, yMax, escalaY && escalaY.paso, 5).forEach(v => {
                el('line', { x1: m.izq, x2: ancho - m.der, y1: Y(v), y2: Y(v), class: 'tg-rejilla' }, svg);
                el('text', { x: m.izq - 7, y: Y(v) + 3, class: 'tg-eje', 'text-anchor': 'end' }, svg).textContent = corto(v);
            });
        }
        (tipoX === 'fecha' ? marcasFecha(xMin, xMax, Math.max(3, Math.floor(anchoUtil / 95))) : marcasPaso(xMin, xMax, escalaX && escalaX.paso, Math.max(3, Math.floor(anchoUtil / 70)))).forEach(v => {
            el('line', { x1: X(v), x2: X(v), y1: m.arr, y2: alto - m.aba, class: 'tg-rejilla tg-rejilla--v' }, svg);
            el('text', { x: X(v), y: alto - m.aba + 15, class: 'tg-eje', 'text-anchor': 'middle' }, svg).textContent = tipoX === 'fecha' ? fechaCorta(v) : corto(v);
        });
        el('text', { x: m.izq + anchoUtil / 2, y: alto - 4, class: 'tg-eje tg-eje--titulo', 'text-anchor': 'middle' }, svg).textContent = textoX;

        const zona = el('g', { 'clip-path': `url(#clip-${uid})` }, svg);
        // Zonas de color detrás de los datos: en especificación (verde), entre alerta y especificación (ámbar), fuera (rojo)
        const lim = limites || {};
        const eMin = numero(lim.especificacion_min), eMax = numero(lim.especificacion_max);
        const aMin = numero(lim.alerta_min), aMax = numero(lim.alerta_max);
        const arriba = m.arr, abajo = alto - m.aba;
        const franja = (yA, yB, tipo) => {   // yA, yB en pixeles
            const y0 = Math.max(Math.min(yA, yB), arriba), y1 = Math.min(Math.max(yA, yB), abajo);
            if (y1 - y0 > 0.5) el('rect', { x: m.izq, y: y0, width: anchoUtil, height: y1 - y0, class: `tg-zona tg-zona--${tipo}` }, zona);
        };
        if (lineas.length) {
            const okArriba = aMax ?? eMax, okAbajo = aMin ?? eMin;
            franja(okArriba !== null ? Y(okArriba) : arriba, okAbajo !== null ? Y(okAbajo) : abajo, 'ok');
            if (aMax !== null) franja(Y(aMax), eMax !== null ? Y(eMax) : arriba, 'alerta');
            if (aMin !== null) franja(Y(aMin), eMin !== null ? Y(eMin) : abajo, 'alerta');
            if (eMax !== null) franja(arriba, Y(eMax), 'fuera');
            if (eMin !== null) franja(Y(eMin), abajo, 'fuera');
        }
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
                    el('path', { d: suave(tramo.map(b => ({ x: b.x, y: b.p50 }))), class: 'tg-mediana' }, zona);
                }
                tramo = [];
            };
            datosBanda.forEach(b => { if (b) tramo.push(b); else cerrar(); });
            cerrar();
        }
        if (curvaVisible.length > 1) el('path', { d: suave(curvaVisible), class: 'tg-curva' }, zona);

        // Series: primero las de fondo (gris tenue), encima las destacadas (con color y brillo)
        const fondo = el('g', { class: 'tg-capa-fondo' }, zona);
        const frente = el('g', {}, zona);
        // Área con degradado bajo la línea cuando hay pocas series con color (no con banda, ni con escalas por parámetro)
        const conArea = ordenadas.filter(s => s.color && !s.tenue).length <= 2 && !datosBanda && !ejes.length && !ordenadas.some(s => s.tenue);
        ordenadas.forEach(s => {
            if (s.orden.length < 2) return;
            if (!s.color) {
                el('path', { d: suave(s.orden), class: 'tg-serie tg-serie--fondo' }, fondo);
                return;
            }
            if (s.tenue) {
                el('path', { d: suave(s.orden), class: 'tg-serie tg-serie--tenue', style: `stroke:${s.color}` }, fondo);
                return;
            }
            if (conArea) {
                const idArea = `area-${uid}-${s.id}`;
                const grad = el('linearGradient', { id: idArea, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
                el('stop', { offset: '0%', 'stop-color': s.color, 'stop-opacity': 0.22 }, grad);
                el('stop', { offset: '100%', 'stop-color': s.color, 'stop-opacity': 0 }, grad);
                const base = Y(yMin);
                el('path', { d: `${suave(s.orden)}L${X(s.orden[s.orden.length - 1].x)},${base}L${X(s.orden[0].x)},${base}Z`, fill: `url(#${idArea})`, class: 'tg-area' }, frente);
            }
            el('path', s.trazo
                ? { d: suave(s.orden), class: 'tg-serie', 'stroke-dasharray': s.trazo, style: `stroke:${s.color}`, filter: `url(#brillo-${uid})` }
                : { d: suave(s.orden), class: 'tg-serie tg-trazo', pathLength: 1, style: `stroke:${s.color}`, filter: `url(#brillo-${uid})` }, frente);
        });
        if (actual && ordenadas.length === 1 && ordenadas[0].orden.length) {
            const previos = ordenadas[0].orden.filter(q => q.x <= actual.x);
            const ultimo = previos.length ? previos[previos.length - 1] : ordenadas[0].orden[0];
            el('line', { x1: X(ultimo.x), y1: Y(ultimo.y), x2: X(actual.x), y2: Y(actual.y), class: 'tg-enlace' }, frente);
        }

        // Puntos (las series de fondo solo si se pide) y su posición en pantalla para buscar el más cercano
        const cercanos = [];
        const marcasFuera = new Map();   // datos fuera de la escala: una marca por columna de 6 px en el borde
        let fueraEscala = 0;
        ordenadas.forEach(s => {
            const conPunto = (s.color && !s.tenue) || mostrarPuntos;
            s.puntos.forEach(q => {
                if (!dentro(q.x)) return;
                const px = X(q.x);
                if (recorte && (q.y > yMax || q.y < yMin)) {
                    const lado = q.y > yMax ? 'arriba' : 'abajo';
                    const py = lado === 'arriba' ? arriba + 6 : abajo - 6;
                    fueraEscala++;
                    marcasFuera.set(`${lado}-${Math.round(px / 6)}`, { px, py, lado });
                    cercanos.push({ px, py, q, s });
                    return;
                }
                const py = Y(q.y);
                cercanos.push({ px, py, q, s });
                if (!conPunto) return;
                const fuerte = s.color && !s.tenue;
                if (q.estado && fuerte) el('circle', { cx: px, cy: py, r: 8.5, class: `tg-halo tg-halo--${q.estado}` }, frente);
                if (fuerte && s.marca) {
                    const hueca = s.marca.endsWith('-hueco');
                    el('path', {
                        d: caminoMarca(s.marca, px, py, 4.6),
                        class: `tg-punto tg-punto--marca${hueca ? ' tg-punto--hueca' : ''}${q.estado ? ` tg-punto--${q.estado}` : ''}`,
                        style: hueca ? `stroke:${s.color}` : `fill:${s.color}`,
                    }, frente);
                    return;
                }
                el('circle', {
                    cx: px, cy: py, r: fuerte ? 4 : 2.6,
                    class: `tg-punto${fuerte ? '' : ' tg-punto--fondo'}${q.estado ? ` tg-punto--${q.estado}` : ''}`,
                    style: s.color ? `fill:${s.color}` : '',
                }, fuerte ? frente : fondo);
            });
        });
        marcasFuera.forEach(({ px, py, lado }) => {
            const p = lado === 'arriba' ? `M${px - 4},${py + 2}L${px},${py - 4}L${px + 4},${py + 2}Z` : `M${px - 4},${py - 2}L${px},${py + 4}L${px + 4},${py - 2}Z`;
            el('path', { d: p, class: 'tg-fuera-escala' }, svg);
        });

        // Nombre de cada serie destacada al final de su línea (sin encimarse); el texto va en tinta, el color en la marca
        const etiquetas = ordenadas.filter(s => s.color && !s.tenue && s.nombre && ordenadas.length > 1).map(s => {
            const visibles = s.orden.filter(q => dentro(q.x));
            if (!visibles.length) return null;
            const ultimo = visibles[visibles.length - 1];
            return { s, x: X(ultimo.x), y: Y(ultimo.y) };
        }).filter(Boolean).sort((a, b) => a.y - b.y);
        // Se reparten hacia abajo sin encimarse y, si se salen por abajo, se empujan hacia arriba (siempre dentro del área)
        const sep = 16, techoE = arriba + 9, pisoE = abajo - 9;
        etiquetas.forEach((e, i) => { e.y = Math.max(e.y, techoE, i ? etiquetas[i - 1].y + sep : -Infinity); });
        for (let i = etiquetas.length - 1; i >= 0; i--) {
            etiquetas[i].y = Math.min(etiquetas[i].y, i < etiquetas.length - 1 ? etiquetas[i + 1].y - sep : pisoE);
        }
        etiquetas.forEach(e => {
            const anchoE = e.s.nombre.length * 6 + (e.s.trazo !== undefined ? 29 : 18);
            const derecha = e.x + 10 + anchoE > ancho - m.der;
            const x0 = derecha ? e.x - 10 - anchoE : e.x + 10;
            const g = el('g', { class: 'tg-pastilla' }, svg);
            el('rect', { x: x0, y: e.y - 7.5, width: anchoE, height: 15, rx: 7.5, style: `stroke:${e.s.color}` }, g);
            if (e.s.trazo !== undefined) {
                el('line', { x1: x0 + 5, x2: x0 + 21, y1: e.y, y2: e.y, 'stroke-dasharray': e.s.trazo, class: 'tg-pastilla__trazo', style: `stroke:${e.s.color}` }, g);
                if (e.s.marca) {
                    const hueca = e.s.marca.endsWith('-hueco');
                    el('path', { d: caminoMarca(e.s.marca, x0 + 13, e.y, 3.2), class: `tg-punto tg-punto--marca${hueca ? ' tg-punto--hueca' : ''}`,
                                 style: hueca ? `stroke:${e.s.color}` : `fill:${e.s.color}` }, g);
                }
                el('text', { x: x0 + 25, y: e.y + 3.5, class: 'tg-nombre' }, g).textContent = e.s.nombre;
            } else {
                el('circle', { cx: x0 + 8, cy: e.y, r: 3.2, fill: e.s.color }, g);
                el('text', { x: x0 + 14, y: e.y + 3.5, class: 'tg-nombre' }, g).textContent = e.s.nombre;
            }
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
        const ponerGuia = (px) => {
            guia.setAttribute('visibility', 'visible');
            guiaLinea.setAttribute('x1', px); guiaLinea.setAttribute('x2', px);
            guiaTexto.setAttribute('x', px);
            guiaTexto.textContent = textoEjeX(aEdad(px));
            const anchoPastilla = guiaTexto.textContent.length * 6 + 14;
            guiaFondo.setAttribute('x', px - anchoPastilla / 2); guiaFondo.setAttribute('width', anchoPastilla);
        };
        const ocultar = () => {
            [guia, iluminada, anillo].forEach(n => n.setAttribute('visibility', 'hidden'));
            ficha.hidden = true;
            cercanoActual = null;
            if (grupoGuia) document.dispatchEvent(new CustomEvent('tg-guia', { detail: { grupo: grupoGuia, x: null, origen: svg } }));
        };
        // Guía sincronizada: otra gráfica del grupo movió su guía (se quita al redibujar este contenedor)
        if (contenedor._quitarGuia) contenedor._quitarGuia();
        if (grupoGuia) {
            const alGuia = (e) => {
                if (e.detail.grupo !== grupoGuia || e.detail.origen === svg) return;
                if (e.detail.x === null || e.detail.x < xMin || e.detail.x > xMax) { guia.setAttribute('visibility', 'hidden'); return; }
                ponerGuia(X(e.detail.x));
            };
            document.addEventListener('tg-guia', alGuia);
            contenedor._quitarGuia = () => document.removeEventListener('tg-guia', alGuia);
        } else {
            contenedor._quitarGuia = null;
        }
        const mover = (p) => {
            const px = Math.min(Math.max(p.x, m.izq), m.izq + anchoUtil);
            guia.setAttribute('visibility', 'visible');
            guiaLinea.setAttribute('x1', px); guiaLinea.setAttribute('x2', px);
            guiaTexto.setAttribute('x', px);
            ponerGuia(px);
            if (grupoGuia) document.dispatchEvent(new CustomEvent('tg-guia', { detail: { grupo: grupoGuia, x: aEdad(px), origen: svg } }));

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
                iluminada.setAttribute('d', suave(c.s.orden));
                iluminada.style.stroke = c.s.color || neutro.linea;
                iluminada.style.strokeDasharray = c.s.trazo || '';
                iluminada.setAttribute('visibility', 'visible');
            } else {
                iluminada.setAttribute('visibility', 'hidden');
            }
            ficha.innerHTML = (c.q.texto || (textoPunto && c.s ? textoPunto(c.s, c.q) : `${corto(c.q.y)} · ${textoEjeX(c.q.x)}`))
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
        return { curvaVisible: curvaVisible.length > 1, rango: [xMin, xMax], rangoY: [yMin, yMax], fueraEscala };
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
        if (tipos.size) items.push('<span><i class="tg-l tg-l--zona"></i>Dentro de límites</span>');
        if (tipos.has('fuera')) items.push('<span><i class="tg-l tg-l--fuera"></i>Especificación</span>');
        if (tipos.has('alerta')) items.push('<span><i class="tg-l tg-l--alerta"></i>Alerta</span>');
        return items.join('');
    };
})();
