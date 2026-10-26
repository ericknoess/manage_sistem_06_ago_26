// datos_proceso/static/datos_proceso/js/graficas_proceso.js
// Gráficas de proceso, en tres pestañas:
//   Lotes:       elegir hasta 200 lotes de la receta (búsqueda, estado, fechas, con datos) y destacar hasta 8.
//   Gráficas:    cada parámetro contra la edad; los lotes elegidos van en gris tenue, los destacados con color; banda P10–P90 y
//                mediana, curva esperada y límites. Zoom por arrastre (sincronizado entre gráficas de la misma edad).
//   Indicadores: tabla ordenable por lote con promedio, mínimo y máximo.
// API: /api/analisis-proceso/ (series compactas e indicadores), /api/analisis-proceso/lotes/, /api/indicadores-proceso/.
// La URL acepta ?proceso=<id>&lotes=1,2 (ej. desde Piso de planta). La selección se recuerda por receta en este navegador.

const MAX_DESTACADOS = 8;
let procesos = [];
let infoReceta = null;          // {proceso, etapas, lotes, max_lotes}
let elegidos = new Set();       // lotes que entran a las gráficas
let destacados = [];            // en orden: el orden fija el color
let analisis = null;            // respuesta de /api/analisis-proceso/
let analisisVigente = false;    // false = cambió la selección y hay que volver a pedirlo
let indicadores = [];
let parametrosNumericos = [];
let indicadorEnEdicion = null;
let peticionAnalisis = 0;
let pestana = 'lotes';
let zoomPorEje = { LOTE: null, ETAPA: null };
let parametrosOcultos = new Set();   // códigos de parámetros que el usuario ocultó (se recuerdan)
let ordenIndicadores = { columna: null, sentido: 1 };

const corto = (v) => numeroCorto(v);
const colorDe = (id) => COLORES_SERIES_CLARO[destacados.indexOf(id)] || null;   // gráficas en fondo blanco
const fechaCorta = (iso) => iso ? new Date(iso).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
const EN_CURSO = ['EN_PROGRESO', 'DESVIACION'];

// ------------------------------------------------------------------
// Preferencias (por receta, en este navegador) y URL
// ------------------------------------------------------------------
function leerPreferencia(clave) {
    try { return JSON.parse(localStorage.getItem(`graficas-proceso:${clave}`)); } catch (e) { return null; }
}
function guardarPreferencia(clave, valor) {
    try { localStorage.setItem(`graficas-proceso:${clave}`, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ }
}
function guardarSeleccion() {
    const proceso = document.getElementById('filtroProceso').value;
    if (!proceso) return;
    guardarPreferencia(`seleccion-${proceso}`, {
        elegidos: [...elegidos], destacados, etapa: document.getElementById('filtroEtapa').value,
        banda: document.getElementById('opcionBanda').checked, puntos: document.getElementById('opcionPuntos').checked,
    });
    const params = new URLSearchParams({ proceso });
    history.replaceState(null, '', `${location.pathname}?${params}`);
}

// ------------------------------------------------------------------
// Pestañas
// ------------------------------------------------------------------
function mostrarPestana(nombre) {
    pestana = nombre;
    document.querySelectorAll('.pestana').forEach(b => {
        const activa = b.dataset.pestana === nombre;
        b.classList.toggle('pestana--activa', activa);
        b.setAttribute('aria-selected', activa);
    });
    document.querySelectorAll('.panel-pestana').forEach(p => { p.hidden = p.dataset.panel !== nombre; });
    guardarPreferencia('pestana', nombre);
    if (nombre !== 'lotes' && !analisisVigente) cargarAnalisis();
    else if (nombre === 'graficas') pintarGraficas();
    else if (nombre === 'indicadores') pintarIndicadores();
}

// ------------------------------------------------------------------
// Carga
// ------------------------------------------------------------------
async function iniciar() {
    const url = new URLSearchParams(location.search);
    parametrosOcultos = new Set(leerPreferencia('ocultos') || []);
    try {
        procesos = await fetch('/api/procesos-maestros/').then(r => r.json());
    } catch (e) {
        document.getElementById('filtroProceso').innerHTML = '<option value="">⚠️ No se pudieron cargar las recetas</option>';
        return;
    }
    procesos.sort((a, b) => (b.activo - a.activo) || a.nombre.localeCompare(b.nombre));
    const select = document.getElementById('filtroProceso');
    select.innerHTML = '<option value="">— Elige una receta —</option>' + procesos.map(p =>
        `<option value="${p.id}">${escaparHtml(p.nombre)}${p.activo === false ? ' (archivada)' : ''}</option>`).join('');
    fetch('/api/parametros-proceso/?activo=true').then(r => r.json())
        .then(lista => { parametrosNumericos = lista.filter(p => p.tipo_dato === 'NUMERO'); }).catch(() => {});

    const inicial = url.get('proceso') || leerPreferencia('proceso');
    const lotesUrl = url.get('lotes') ? url.get('lotes').split(',').map(Number).filter(Boolean) : null;
    mostrarPestana(lotesUrl ? 'graficas' : (leerPreferencia('pestana') || 'lotes'));
    if (inicial && procesos.some(p => String(p.id) === String(inicial))) {
        select.value = inicial;
        await cambiarProceso({ lotesUrl });
    }
}

async function cambiarProceso({ lotesUrl = null } = {}) {
    const proceso = document.getElementById('filtroProceso').value;
    document.getElementById('btnIndicadores').disabled = !proceso;
    infoReceta = null; analisis = null; analisisVigente = false;
    elegidos = new Set(); destacados = [];
    zoomPorEje = { LOTE: null, ETAPA: null };
    if (!proceso) {
        pintarTablaLotes(); pintarGraficas(); pintarIndicadores();
        return;
    }
    guardarPreferencia('proceso', proceso);
    document.getElementById('cuerpoLotes').innerHTML = '<tr><td colspan="6" class="estado-vacio">Cargando lotes…</td></tr>';
    infoReceta = await fetch(`/api/analisis-proceso/lotes/?proceso=${proceso}`).then(r => r.json());
    const guardada = leerPreferencia(`seleccion-${proceso}`) || {};
    document.getElementById('filtroEtapa').innerHTML = '<option value="">Todo el lote</option>'
        + infoReceta.etapas.map(e => `<option value="${e.id}">${escaparHtml(e.nombre)}</option>`).join('');
    if (infoReceta.etapas.some(e => String(e.id) === String(guardada.etapa))) document.getElementById('filtroEtapa').value = guardada.etapa;

    const existentes = new Set(infoReceta.lotes.map(l => l.id));
    if (lotesUrl) {
        elegidos = new Set(lotesUrl.filter(id => existentes.has(id)));
        destacados = [...elegidos].slice(0, MAX_DESTACADOS);
    } else if (guardada.elegidos) {
        elegidos = new Set(guardada.elegidos.filter(id => existentes.has(id)));
        destacados = (guardada.destacados || []).filter(id => elegidos.has(id)).slice(0, MAX_DESTACADOS);
    } else {
        // Primera vez: los 30 lotes más recientes con datos; se destacan los que siguen en curso
        const conDatos = infoReceta.lotes.filter(l => l.tomas > 0 && !l.archivado).slice(0, 30);
        elegidos = new Set(conDatos.map(l => l.id));
        destacados = conDatos.filter(l => EN_CURSO.includes(l.estado)).slice(0, 3).map(l => l.id);
    }
    document.getElementById('opcionBanda').checked = guardada.banda ?? elegidos.size >= 6;
    document.getElementById('opcionPuntos').checked = guardada.puntos ?? elegidos.size <= 12;
    pintarTablaLotes();
    await cargarIndicadores();
    if (pestana !== 'lotes') await cargarAnalisis();
}

function cambiarEtapa() {
    zoomPorEje = { LOTE: null, ETAPA: null };
    guardarSeleccion();
    cargarAnalisis();
}

async function cargarAnalisis() {
    const proceso = document.getElementById('filtroProceso').value;
    analisisVigente = true;
    if (!proceso || !elegidos.size) {
        analisis = null;
        pintarGraficas(); pintarIndicadores();
        return;
    }
    const numero = ++peticionAnalisis;
    const rejilla = document.getElementById('rejillaGraficas');
    rejilla.classList.add('cargando');
    if (!analisis) rejilla.innerHTML = '<div class="panel estado-vacio">Cargando datos de los lotes…</div>';
    const etapa = document.getElementById('filtroEtapa').value;
    try {
        const res = await fetch(`/api/analisis-proceso/?proceso=${proceso}&lotes=${[...elegidos].join(',')}${etapa ? `&etapa=${etapa}` : ''}`);
        const data = await res.json();
        if (numero !== peticionAnalisis) return;  // llegó una respuesta más nueva
        if (!res.ok) throw new Error(data.error || data.detail || 'No se pudo cargar el análisis.');
        analisis = data;
        pintarGraficas(); pintarIndicadores();
    } catch (err) {
        if (numero !== peticionAnalisis) return;
        analisisVigente = false;
        rejilla.innerHTML = `<div class="panel estado-vacio">⚠️ ${escaparHtml(err.message)}</div>`;
    } finally {
        if (numero === peticionAnalisis) rejilla.classList.remove('cargando');
    }
}

// ------------------------------------------------------------------
// Pestaña Lotes: elegir y destacar
// ------------------------------------------------------------------
function lotesFiltrados() {
    if (!infoReceta) return [];
    const texto = normalizarBusqueda(document.getElementById('buscarLote').value);
    const estado = document.getElementById('filtroEstadoLote').value;
    const desde = document.getElementById('filtroDesde').value;
    const hasta = document.getElementById('filtroHasta').value;
    const conDatos = document.getElementById('filtroConDatos').checked;
    const archivados = document.getElementById('filtroArchivados').checked;
    return infoReceta.lotes.filter(l => {
        const dia = l.inicio ? l.inicio.slice(0, 10) : '';
        return (!texto || normalizarBusqueda(l.identificador).includes(texto))
            && (!estado || (estado === 'EN_CURSO' ? EN_CURSO.includes(l.estado) : l.estado === estado))
            && (!desde || dia >= desde) && (!hasta || dia <= hasta)
            && (!conDatos || l.tomas > 0) && (archivados || !l.archivado);
    });
}

function seleccionCambio() {
    analisisVigente = false;
    guardarSeleccion();
    pintarTablaLotes();
    if (pestana !== 'lotes') cargarAnalisis();
}

function alternarElegido(id, valor) {
    if (valor) {
        if (elegidos.size >= infoReceta.max_lotes) { alert(`Puedes elegir hasta ${infoReceta.max_lotes} lotes.`); pintarTablaLotes(); return; }
        elegidos.add(id);
    } else {
        elegidos.delete(id);
        destacados = destacados.filter(d => d !== id);
    }
    seleccionCambio();
}

function elegirFiltrados(valor) {
    const filtrados = lotesFiltrados();
    if (valor) {
        const libres = infoReceta.max_lotes - elegidos.size;
        const nuevos = filtrados.filter(l => !elegidos.has(l.id));
        if (nuevos.length > libres) alert(`Solo caben ${libres} lotes más (máximo ${infoReceta.max_lotes}); se eligen los primeros ${libres} de la lista.`);
        nuevos.slice(0, Math.max(libres, 0)).forEach(l => elegidos.add(l.id));
    } else {
        filtrados.forEach(l => elegidos.delete(l.id));
        destacados = destacados.filter(d => elegidos.has(d));
    }
    seleccionCambio();
}

// Destacar: entra a la selección si no estaba; máximo 8 con color
function alternarDestacado(id) {
    if (destacados.includes(id)) {
        destacados = destacados.filter(d => d !== id);
    } else {
        if (destacados.length >= MAX_DESTACADOS) {
            alert(`Puedes destacar hasta ${MAX_DESTACADOS} lotes: quita uno para destacar otro.`);
            return;
        }
        destacados.push(id);
        if (!elegidos.has(id)) { elegidos.add(id); analisisVigente = false; }
    }
    guardarSeleccion();
    pintarTablaLotes();
    if (!analisisVigente && pestana !== 'lotes') cargarAnalisis();
    else { pintarGraficas(); pintarIndicadores(); }
}

function pintarTablaLotes() {
    document.getElementById('conteoPestanaLotes').textContent = elegidos.size;
    const cuerpo = document.getElementById('cuerpoLotes');
    if (!infoReceta) {
        cuerpo.innerHTML = '<tr><td colspan="6" class="estado-vacio">Elige una receta.</td></tr>';
        document.getElementById('resumenLotes').textContent = '';
        return;
    }
    const filtrados = lotesFiltrados();
    const elegidosFiltrados = filtrados.filter(l => elegidos.has(l.id)).length;
    const todos = document.getElementById('checkTodos');
    todos.checked = filtrados.length > 0 && elegidosFiltrados === filtrados.length;
    todos.indeterminate = elegidosFiltrados > 0 && elegidosFiltrados < filtrados.length;
    document.getElementById('resumenLotes').innerHTML = `<strong>${elegidos.size}</strong> de ${infoReceta.lotes.length} lotes elegidos
        (máximo ${infoReceta.max_lotes}) · <strong>${destacados.length}</strong> destacados con color (máximo ${MAX_DESTACADOS})
        · mostrando ${filtrados.length}`;
    cuerpo.innerHTML = filtrados.length ? filtrados.map(l => {
        const elegido = elegidos.has(l.id), color = colorDe(l.id);
        return `<tr class="${elegido ? 'fila-elegida' : ''}">
            <td class="col-check"><input type="checkbox" ${elegido ? 'checked' : ''} onchange="alternarElegido(${l.id}, this.checked)" aria-label="Elegir ${escaparHtml(l.identificador)}"></td>
            <td><strong>${escaparHtml(l.identificador)}</strong>${l.archivado ? ' <small class="sin-dato">archivado</small>' : ''}</td>
            <td><span class="estado-lote estado-lote--${l.estado.toLowerCase()}">${escaparHtml(l.estado_display)}</span></td>
            <td>${fechaCorta(l.inicio)}</td>
            <td>${l.tomas || '<span class="sin-dato">0</span>'}</td>
            <td><button type="button" class="btn-destacar ${color ? 'btn-destacar--activo' : ''}" onclick="alternarDestacado(${l.id})"
                    title="${color ? 'Quitar el color' : 'Destacar con color en las gráficas'}">
                <i class="chip-lote__color" style="${color ? `background:${color}` : ''}"></i>${color ? 'Destacado' : 'Destacar'}</button></td>
        </tr>`;
    }).join('') : '<tr><td colspan="6" class="estado-vacio">Ningún lote coincide con los filtros.</td></tr>';
}

// ------------------------------------------------------------------
// Pestaña Gráficas
// ------------------------------------------------------------------
function cambiarOpcion() {
    guardarSeleccion();
    pintarGraficas();
}

function restablecerZoom() {
    zoomPorEje = { LOTE: null, ETAPA: null };
    pintarGraficas();
}

function destacarPorNombre(input) {
    const lote = analisis && analisis.lotes.find(l => l.identificador.toLowerCase() === input.value.trim().toLowerCase());
    input.value = '';
    if (lote && !destacados.includes(lote.id)) alternarDestacado(lote.id);
}

function pintarBarraGraficas() {
    const lotesPorId = Object.fromEntries((analisis ? analisis.lotes : []).map(l => [l.id, l]));
    document.getElementById('chipsDestacados').innerHTML = destacados.length ? destacados.map(id => `
        <button type="button" class="chip-lote chip-lote--elegido" onclick="alternarDestacado(${id})" title="Quitar el color">
            <i class="chip-lote__color" style="background:${colorDe(id)}"></i><strong>${escaparHtml(lotesPorId[id] ? lotesPorId[id].identificador : `#${id}`)}</strong> ✕
        </button>`).join('') : '<span class="sin-dato">Ninguno: clic en una línea para destacarla.</span>';
    document.getElementById('listaDestacar').innerHTML = (analisis ? analisis.lotes : [])
        .filter(l => !destacados.includes(l.id)).map(l => `<option value="${escaparHtml(l.identificador)}">`).join('');
    document.getElementById('btnRestablecerZoom').hidden = !(zoomPorEje.LOTE || zoomPorEje.ETAPA);

    const parametros = analisis ? analisis.parametros.filter(p => Object.keys(p.series).length) : [];
    document.getElementById('filtroParametros').innerHTML = parametros.length ? '<span class="destacados__titulo">Parámetros</span>' + parametros.map(p => `
        <button type="button" class="chip-parametro ${parametrosOcultos.has(p.codigo) ? '' : 'chip-parametro--activo'}"
                onclick="alternarParametro('${escaparHtml(p.codigo)}')">${escaparHtml(p.nombre)}</button>`).join('') : '';
}

function alternarParametro(codigo) {
    if (parametrosOcultos.has(codigo)) parametrosOcultos.delete(codigo);
    else parametrosOcultos.add(codigo);
    guardarPreferencia('ocultos', [...parametrosOcultos]);
    pintarGraficas();
}

function textoPunto(p, serie, q) {
    const [, , valor, estado, adicional, momento, tarea] = q.crudo;
    const ejeTexto = q.x;
    return `<strong>${escaparHtml(serie.nombre)}</strong><br>
        <strong>${corto(valor)}</strong>${p.unidad ? ' ' + escaparHtml(p.unidad) : ''} a ${corto(ejeTexto)} h<br>
        <span class="tg-ayuda__tenue">${escaparHtml(analisis.tareas[tarea] || '')}${adicional ? ' · adicional' : ''}<br>
        ${new Date(momento * 1000).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })}</span>
        ${estado === 2 ? '<br>🚨 Fuera de especificación' : estado === 1 ? '<br>⚠️ Fuera de alerta' : ''}`;
}

function htmlTarjeta(p, ampliada = false) {
    return `
        <header class="tarjeta-grafica__titulo">
            <span class="tarjeta-grafica__nombre" ${ampliada ? '' : `onclick="abrirGraficaGrande(${p.parametro})" title="Ampliar"`}>
                ${escaparHtml(p.nombre)} ${p.unidad ? `<small>${escaparHtml(p.unidad)}</small>` : ''}
                ${p.calculado ? '<span class="etiqueta-calculado" title="Calculado con su fórmula">ƒ</span>' : ''}</span>
            <span class="tarjeta-grafica__acciones">
                <span class="tarjeta-grafica__resumen"></span>
                ${ampliada ? '' : `<button type="button" class="btn-ampliar" onclick="abrirGraficaGrande(${p.parametro})" title="Abrir en grande">⤢ Ampliar</button>`}
            </span>
        </header>
        <div class="tg-leyenda tg-leyenda--claro"></div>
        <div class="tarjeta-grafica__lienzo"></div>
        <div class="tarjeta-grafica__nota"></div>`;
}

// Dibuja un parámetro en una tarjeta (de la rejilla o del modal ampliado)
function dibujarTarjeta(tarjeta, p, alto) {
    const banda = document.getElementById('opcionBanda').checked;
    const mostrarPuntos = document.getElementById('opcionPuntos').checked;
    const lotesPorId = Object.fromEntries(analisis.lotes.map(l => [String(l.id), l]));
    const ref = p.referencia || {};
    const ejeClave = ref.eje_edad === 'ETAPA' ? 'ETAPA' : 'LOTE';
    const indice = ejeClave === 'ETAPA' ? 1 : 0;
    let sinEdad = 0;
    const series = Object.entries(p.series).map(([id, puntos]) => {
        const lote = lotesPorId[id];
        sinEdad += puntos.filter(q => q[indice] === null).length;
        const color = colorDe(Number(id));
        return {
            id: Number(id), nombre: lote ? lote.identificador : id, color, destacada: !!color,
            puntos: puntos.filter(q => q[indice] !== null).map(q => ({
                x: q[indice], y: q[2], estado: q[3] === 2 ? 'fuera' : q[3] === 1 ? 'alerta' : '', crudo: q,
            })),
        };
    });
    // Las destacadas se dibujan al final (encima) en el orden en que se destacaron
    series.sort((a, b) => (a.destacada - b.destacada) || (destacados.indexOf(a.id) - destacados.indexOf(b.id)));
    const conColor = series.filter(s => s.destacada);
    const r = graficaLineas(tarjeta.querySelector('.tarjeta-grafica__lienzo'), {
        series, curva: ref.curva || [], objetivo: ref.objetivo, limites: p.limites, alto,
        banda, mostrarPuntos, zoom: zoomPorEje[ejeClave],
        alZoom: (rango) => { zoomPorEje[ejeClave] = rango; pintarGraficas(); },
        alElegirSerie: (id) => alternarDestacado(id),
        textoPunto: (serie, q) => textoPunto(p, serie, q), tema: 'claro',
        textoX: ejeClave === 'ETAPA' ? 'Edad de la etapa (h)' : 'Edad del lote (h)',
    });
    tarjeta.querySelector('.tg-leyenda').innerHTML = leyendaGrafica({
        series: conColor.map(s => ({ color: s.color, etiqueta: escaparHtml(s.nombre) })),
        fondo: series.length - conColor.length, banda: banda && series.length >= 3,
        curva: r.curvaVisible, objetivo: ref.objetivo !== null && ref.objetivo !== undefined, limites: p.limites,
    });
    const fuera = series.reduce((n, s) => n + s.puntos.filter(q => q.estado === 'fuera').length, 0);
    tarjeta.querySelector('.tarjeta-grafica__resumen').innerHTML = `${series.length} lote${series.length === 1 ? '' : 's'}`
        + (fuera ? ` · <span class="valor-fuera">${fuera} fuera de esp.</span>` : '')
        + (zoomPorEje[ejeClave] ? ` · 🔍 ${zoomPorEje[ejeClave][0].toFixed(1)}–${zoomPorEje[ejeClave][1].toFixed(1)} h` : '');
    const notas = [];
    if (sinEdad) notas.push(`${sinEdad} dato(s) sin edad (a su lote le falta la edad 0) no se grafican.`);
    if (banda && series.length < 3) notas.push('La banda necesita al menos 3 lotes con datos.');
    tarjeta.querySelector('.tarjeta-grafica__nota').textContent = notas.join(' ');
}

function parametrosVisibles() {
    if (!analisis) return [];
    return analisis.parametros.filter(p => Object.keys(p.series).length && !parametrosOcultos.has(p.codigo));
}

function pintarGraficas() {
    if (pestana !== 'graficas') return;
    pintarBarraGraficas();
    const rejilla = document.getElementById('rejillaGraficas');
    if (!document.getElementById('filtroProceso').value) {
        rejilla.innerHTML = '<div class="panel estado-vacio">Elige una receta.</div>';
        return;
    }
    if (!elegidos.size) {
        rejilla.innerHTML = '<div class="panel estado-vacio">No hay lotes elegidos: elígelos en la pestaña 🧪 Lotes.</div>';
        return;
    }
    if (!analisis) return;
    const parametros = parametrosVisibles();
    if (!parametros.length) {
        const conDatos = analisis.parametros.some(p => Object.keys(p.series).length);
        rejilla.innerHTML = `<div class="panel estado-vacio">${conDatos ? 'Todos los parámetros están ocultos: actívalos arriba.'
            : 'Los lotes elegidos no tienen datos en esta receta o etapa.'}</div>`;
        return;
    }
    rejilla.innerHTML = parametros.map(p => `<article class="tarjeta-grafica" data-parametro="${p.parametro}">${htmlTarjeta(p)}</article>`).join('');
    parametros.forEach(p => dibujarTarjeta(rejilla.querySelector(`[data-parametro="${p.parametro}"]`), p, 290));
    pintarGraficaGrande();
}

// ------------------------------------------------------------------
// Gráfica ampliada (modal)
// ------------------------------------------------------------------
let parametroAmpliado = null;

function abrirGraficaGrande(parametroId) {
    parametroAmpliado = parametroId;
    document.getElementById('modalGrafica').style.display = 'flex';
    document.body.classList.add('sin-desplazamiento');
    pintarGraficaGrande();
}

function cerrarGraficaGrande() {
    if (parametroAmpliado === null) return;
    parametroAmpliado = null;
    document.getElementById('modalGrafica').style.display = 'none';
    document.body.classList.remove('sin-desplazamiento');
}

function moverGraficaGrande(delta) {
    const lista = parametrosVisibles();
    const i = lista.findIndex(p => p.parametro === parametroAmpliado);
    if (i < 0 || lista.length < 2) return;
    parametroAmpliado = lista[(i + delta + lista.length) % lista.length].parametro;
    pintarGraficaGrande();
}

function pintarGraficaGrande() {
    if (parametroAmpliado === null) return;
    const lista = parametrosVisibles();
    const i = lista.findIndex(p => p.parametro === parametroAmpliado);
    if (i < 0) { cerrarGraficaGrande(); return; }
    const p = lista[i];
    const tarjeta = document.getElementById('tarjetaGrande');
    tarjeta.innerHTML = htmlTarjeta(p, true);
    document.getElementById('posicionGrafica').textContent = `${i + 1} de ${lista.length}`;
    // Alto según la ventana: lo que queda después del encabezado, la leyenda y la nota
    const alto = Math.max(320, Math.min(window.innerHeight - 230, 900));
    dibujarTarjeta(tarjeta, p, alto);
}

let temporizadorAncho = null;
window.addEventListener('resize', () => {
    clearTimeout(temporizadorAncho);
    temporizadorAncho = setTimeout(pintarGraficas, 200);   // también redibuja la ampliada
});

// ------------------------------------------------------------------
// Pestaña Indicadores
// ------------------------------------------------------------------
function estadoMeta(ind, valor) {
    if (valor === null || valor === undefined) return '';
    const min = ind.meta_min === null ? null : Number(ind.meta_min);
    const max = ind.meta_max === null ? null : Number(ind.meta_max);
    if (min !== null && valor < min) return 'bajo';
    if (max !== null && valor > max) return 'sobre';
    return (min !== null || max !== null) ? 'ok' : '';
}

function textoMeta(ind) {
    if (ind.meta_min === null && ind.meta_max === null) return '';
    return `Meta ${ind.meta_min !== null ? corto(Number(ind.meta_min)) : '−∞'} – ${ind.meta_max !== null ? corto(Number(ind.meta_max)) : '∞'}`;
}

function ordenarIndicadores(columna) {
    ordenIndicadores = { columna, sentido: ordenIndicadores.columna === columna ? -ordenIndicadores.sentido : (columna === 'lote' ? 1 : -1) };
    pintarIndicadores();
}

function pintarIndicadores() {
    if (pestana !== 'indicadores') return;
    const tabla = document.getElementById('tablaIndicadores');
    if (!analisis || !analisis.lotes.length) {
        tabla.innerHTML = '<tbody><tr><td class="estado-vacio">Elige una receta y al menos un lote (pestaña 🧪 Lotes).</td></tr></tbody>';
        return;
    }
    const inds = analisis.indicadores;
    if (!inds.length) {
        tabla.innerHTML = `<tbody><tr><td class="estado-vacio">Esta receta no tiene indicadores.
            <span data-permiso="editar_receta">Agrégalos con <strong>⚙️ Indicadores de la receta</strong> (ej. ABC de células y gramos estimados).</span></td></tr></tbody>`;
        return;
    }
    const valor = (lote, codigo) => ((analisis.valores_indicadores[String(lote.id)] || {})[codigo] || { valor: null, nota: '' });
    const flecha = (col) => ordenIndicadores.columna === col ? (ordenIndicadores.sentido > 0 ? ' ▲' : ' ▼') : '';
    const lotes = [...analisis.lotes];
    const { columna, sentido } = ordenIndicadores;
    if (columna === 'lote') lotes.sort((a, b) => sentido * a.identificador.localeCompare(b.identificador, 'es', { numeric: true }));
    else if (columna) lotes.sort((a, b) => {
        const va = valor(a, columna).valor, vb = valor(b, columna).valor;
        if (va === null) return 1;
        if (vb === null) return -1;
        return sentido * (va - vb);
    });

    const resumen = inds.map(i => {
        const vs = analisis.lotes.map(l => valor(l, i.codigo).valor).filter(v => v !== null);
        return vs.length ? { n: vs.length, prom: vs.reduce((a, b) => a + b, 0) / vs.length, min: Math.min(...vs), max: Math.max(...vs),
            enMeta: vs.filter(v => estadoMeta(i, v) === 'ok').length, conMeta: i.meta_min !== null || i.meta_max !== null } : null;
    });
    const filaResumen = (titulo, f) => `<tr class="fila-resumen"><th scope="row">${titulo}</th>${resumen.map(r => `<td>${r ? f(r) : '—'}</td>`).join('')}</tr>`;
    const cabecera = inds.map(i => `<th class="ordenable" onclick="ordenarIndicadores('${escaparHtml(i.codigo)}')" title="${escaparHtml(i.tipo_display)}">
        ${escaparHtml(i.nombre)}${flecha(i.codigo)}${i.unidad ? `<small>${escaparHtml(i.unidad)}</small>` : ''}${textoMeta(i) ? `<small class="meta">${textoMeta(i)}</small>` : ''}</th>`).join('');
    const filas = lotes.map(l => {
        const color = colorDe(l.id);
        const celdas = inds.map(i => {
            const r = valor(l, i.codigo);
            const estado = estadoMeta(i, r.valor);
            const marca = estado === 'bajo' ? '<span class="marca-meta marca-meta--fuera">▼ bajo meta</span>'
                : estado === 'sobre' ? '<span class="marca-meta marca-meta--fuera">▲ sobre meta</span>'
                : estado === 'ok' ? '<span class="marca-meta marca-meta--ok">✓ en meta</span>' : '';
            return `<td class="celda-indicador">${r.valor === null ? '<span class="sin-dato">—</span>' : `<strong>${corto(r.valor)}</strong>`}
                ${marca}${r.nota ? `<small class="nota-indicador">${escaparHtml(r.nota)}</small>` : ''}</td>`;
        }).join('');
        return `<tr class="fila-lote ${color ? 'fila-destacada' : ''}" onclick="alternarDestacado(${l.id})" title="${color ? 'Quitar el color' : 'Destacar en las gráficas'}">
            <th scope="row" class="celda-lote"><i class="chip-lote__color" style="${color ? `background:${color}` : ''}"></i>${escaparHtml(l.identificador)}
            <small>${escaparHtml(l.estado_display)}${l.edad_actual_h !== null ? ` · ${corto(l.edad_actual_h)} h` : ''}</small></th>${celdas}</tr>`;
    }).join('');
    tabla.innerHTML = `<thead><tr><th class="ordenable" onclick="ordenarIndicadores('lote')">Lote${flecha('lote')}</th>${cabecera}</tr></thead>
        <tbody class="cuerpo-resumen">
            ${filaResumen('Promedio', r => `<strong>${corto(r.prom)}</strong> <small class="nota-indicador">${r.n} lote${r.n === 1 ? '' : 's'}</small>`)}
            ${filaResumen('Mín – máx', r => `${corto(r.min)} – ${corto(r.max)}`)}
            ${filaResumen('En meta', r => r.conMeta ? `${r.enMeta} de ${r.n} (${Math.round(r.enMeta / r.n * 100)} %)` : '<span class="sin-dato">sin meta</span>')}
        </tbody>
        <tbody>${filas}</tbody>`;
}

// ------------------------------------------------------------------
// Configuración de indicadores de la receta
// ------------------------------------------------------------------
async function cargarIndicadores() {
    const proceso = document.getElementById('filtroProceso').value;
    if (!proceso) return;
    try {
        indicadores = await fetch(`/api/indicadores-proceso/?proceso=${proceso}`).then(r => r.json());
    } catch (e) {
        indicadores = [];
    }
    pintarListaIndicadores();
}

function descripcionCalculo(i) {
    if (i.tipo === 'FORMULA') return `<code>${escaparHtml(i.formula)}</code>`;
    const etapa = i.etapa_nombre ? ` · etapa ${escaparHtml(i.etapa_nombre)}` : ' · todo el lote';
    const eje = i.tipo === 'AREA' ? ` · contra ${i.eje_edad === 'ETAPA' ? 'edad de la etapa' : 'edad del lote'}`
        : i.tipo === 'APEGO' ? ' · contra la edad de su curva' : '';
    return `${escaparHtml(i.parametro_nombre)}${etapa}${eje}`;
}

function pintarListaIndicadores() {
    const cuerpo = document.getElementById('cuerpoIndicadores');
    cuerpo.innerHTML = indicadores.length ? indicadores.map(i => `
        <tr class="${i.activo ? '' : 'fila-inactiva'}">
            <td class="col-codigo">${escaparHtml(i.codigo)}</td>
            <td>${escaparHtml(i.nombre)}${i.unidad ? ` <small class="unidad-indicador">${escaparHtml(i.unidad)}</small>` : ''}</td>
            <td>${escaparHtml(i.tipo_display)}</td>
            <td>${descripcionCalculo(i)}</td>
            <td>${textoMeta(i) || '<span class="sin-dato">—</span>'}</td>
            <td><span class="estado ${i.activo ? 'estado--activo' : 'estado--inactivo'}">${i.activo ? 'Activo' : 'Inactivo'}</span></td>
            <td class="col-acciones"><button type="button" class="btn-icono" data-permiso="editar_receta" title="Editar" onclick="editarIndicador(${i.id})">✏️</button></td>
        </tr>`).join('') : '<tr><td colspan="7" class="estado-vacio">Sin indicadores todavía.</td></tr>';
    document.getElementById('ayudaCodigosIndicador').textContent = indicadores.length
        ? `Códigos disponibles: ${indicadores.filter(i => i.id !== indicadorEnEdicion).map(i => i.codigo).join(', ')}` : 'Primero crea los indicadores que usará la fórmula.';
}

function abrirIndicadores() {
    const proceso = procesos.find(p => String(p.id) === document.getElementById('filtroProceso').value);
    if (!proceso) return;
    document.getElementById('indicadoresReceta').textContent = proceso.nombre;
    document.getElementById('modalIndicadores').style.display = 'flex';
    nuevoIndicador();
    pintarListaIndicadores();
}

function cerrarIndicadores() {
    document.getElementById('modalIndicadores').style.display = 'none';
}

function llenarSelectsIndicador(valorParametro, valorEtapa) {
    document.getElementById('indParametro').innerHTML = '<option value="">— Elige —</option>' + parametrosNumericos.map(p =>
        `<option value="${p.id}">${escaparHtml(p.nombre)} (${escaparHtml(p.codigo)})</option>`).join('');
    document.getElementById('indEtapa').innerHTML = '<option value="">Todo el lote</option>' + (infoReceta ? infoReceta.etapas : []).map(e =>
        `<option value="${e.id}">${escaparHtml(e.nombre)}</option>`).join('');
    document.getElementById('indParametro').value = valorParametro || '';
    document.getElementById('indEtapa').value = valorEtapa || '';
}

function actualizarFormIndicador() {
    const tipo = document.getElementById('indTipo').value;
    document.querySelectorAll('#formIndicador [data-segun]').forEach(el => {
        const segun = el.dataset.segun;
        el.hidden = segun === 'formula' ? tipo !== 'FORMULA'
            : segun === 'area' ? tipo !== 'AREA'
            : tipo === 'FORMULA';
    });
    if (tipo === 'APEGO' && !document.getElementById('indUnidad').value) document.getElementById('indUnidad').value = '%';
}

function nuevoIndicador() {
    indicadorEnEdicion = null;
    const form = document.getElementById('formIndicador');
    form.reset();
    document.getElementById('indCodigo').disabled = false;
    document.getElementById('tituloFormIndicador').textContent = '➕ Nuevo indicador';
    document.getElementById('errorIndicador').hidden = true;
    llenarSelectsIndicador();
    actualizarFormIndicador();
    pintarListaIndicadores();
}

function editarIndicador(id) {
    const i = indicadores.find(x => x.id === id);
    if (!i) return;
    indicadorEnEdicion = id;
    document.getElementById('tituloFormIndicador').textContent = `✏️ Editar ${i.nombre}`;
    document.getElementById('indCodigo').value = i.codigo;
    document.getElementById('indCodigo').disabled = true;
    document.getElementById('indNombre').value = i.nombre;
    document.getElementById('indTipo').value = i.tipo;
    document.getElementById('indUnidad').value = i.unidad;
    document.getElementById('indEje').value = i.eje_edad;
    document.getElementById('indFormula').value = i.formula;
    document.getElementById('indDecimales').value = i.decimales;
    document.getElementById('indMetaMin').value = i.meta_min === null ? '' : Number(i.meta_min);
    document.getElementById('indMetaMax').value = i.meta_max === null ? '' : Number(i.meta_max);
    document.getElementById('indActivo').checked = i.activo;
    document.getElementById('errorIndicador').hidden = true;
    llenarSelectsIndicador(i.parametro, i.etapa);
    actualizarFormIndicador();
    pintarListaIndicadores();
    document.getElementById('indNombre').focus();
}

function textoError(data) {
    if (!data || typeof data !== 'object') return 'No se pudo guardar.';
    const aplanar = (v) => typeof v === 'string' ? [v] : Array.isArray(v) ? v.flatMap(aplanar) : (v && typeof v === 'object') ? Object.values(v).flatMap(aplanar) : [];
    return aplanar(data).join(' ') || 'No se pudo guardar.';
}

async function guardarIndicador(evento) {
    evento.preventDefault();
    const error = document.getElementById('errorIndicador');
    error.hidden = true;
    const tipo = document.getElementById('indTipo').value;
    const vacioANull = (id) => document.getElementById(id).value === '' ? null : document.getElementById(id).value;
    const cuerpo = {
        proceso: Number(document.getElementById('filtroProceso').value),
        codigo: document.getElementById('indCodigo').value.trim(),
        nombre: document.getElementById('indNombre').value.trim(),
        tipo, unidad: document.getElementById('indUnidad').value.trim(),
        decimales: Number(document.getElementById('indDecimales').value || 0),
        parametro: tipo === 'FORMULA' ? null : (Number(document.getElementById('indParametro').value) || null),
        etapa: tipo === 'FORMULA' ? null : (Number(document.getElementById('indEtapa').value) || null),
        eje_edad: document.getElementById('indEje').value,
        formula: tipo === 'FORMULA' ? document.getElementById('indFormula').value.trim() : '',
        meta_min: vacioANull('indMetaMin'), meta_max: vacioANull('indMetaMax'),
        activo: document.getElementById('indActivo').checked,
    };
    if (indicadorEnEdicion) delete cuerpo.codigo;
    try {
        const res = await fetch(indicadorEnEdicion ? `/api/indicadores-proceso/${indicadorEnEdicion}/` : '/api/indicadores-proceso/', {
            method: indicadorEnEdicion ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify(cuerpo),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            error.textContent = textoError(data);
            error.hidden = false;
            return;
        }
        await cargarIndicadores();
        nuevoIndicador();
        cargarAnalisis();
    } catch (e) {
        error.textContent = 'Error de red. Intenta de nuevo.';
        error.hidden = false;
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { cerrarIndicadores(); cerrarGraficaGrande(); }
    if (parametroAmpliado !== null && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        if (e.key === 'ArrowRight') moverGraficaGrande(1);
        if (e.key === 'ArrowLeft') moverGraficaGrande(-1);
    }
});
document.addEventListener('DOMContentLoaded', iniciar);
