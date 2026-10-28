// datos_proceso/static/datos_proceso/js/graficas_proceso.js
// Gráficas de proceso. A la izquierda, las plantillas (recetas) como en el diseñador; a la derecha, tres pestañas:
//   Lotes:       elegir hasta 200 lotes de la receta (búsqueda, estado, fechas, con datos) y destacar hasta 8.
//   Gráficas:    por etapa de la receta y, dentro, por actividad · sección (como en el diseñador); cada parámetro contra la edad:
//                los lotes elegidos van en gris tenue, los destacados con color; banda P10–P90 y
//                mediana, curva esperada y límites. Zoom por arrastre (sincronizado entre gráficas de la misma edad).
//   Comparar:    varios parámetros a la vez (ej. flujo y temperatura): apilados con el mismo eje X y guía sincronizada,
//                superpuestos en una gráfica escalando cada uno de 0 a 100 %, o con ejes múltiples (cada uno en sus unidades, hasta 4).
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
let zoomPorEje = {};             // {'LOTE': [x0, x1], 'ETAPA-<id>': …}: zoom compartido por las gráficas con la misma edad
let parametrosOcultos = new Set();   // códigos de parámetros que el usuario ocultó (se recuerdan)
let ordenIndicadores = { columna: null, sentido: 1 };
let escalasGraficas = { x: {}, y: {} };   // pestaña Gráficas: escala manual del eje X (por edad: 'LOTE' o 'ETAPA-<id>') y Y (por parámetro)
let tarjetasConEscalas = new Set();        // claves de las tarjetas con el panel de escalas abierto
let vistaAnimada = '';            // receta|etapa|lotes ya dibujados: las líneas se trazan animadas solo al cambiar de vista

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
    else if (nombre === 'comparar') pintarComparar();
}

// ------------------------------------------------------------------
// Carga
// ------------------------------------------------------------------
async function iniciar() {
    const url = new URLSearchParams(location.search);
    parametrosOcultos = new Set(leerPreferencia('ocultos') || []);
    try {
        procesos = await fetch('/api/analisis-proceso/recetas/').then(r => r.json());
    } catch (e) {
        document.getElementById('listaPlantillas').innerHTML = '<span class="estado-vacio">⚠️ No se pudieron cargar las plantillas.</span>';
        return;
    }
    const select = document.getElementById('filtroProceso');
    select.innerHTML = '<option value=""></option>' + procesos.map(p => `<option value="${p.id}">${escaparHtml(p.nombre)}</option>`).join('');
    fetch('/api/parametros-proceso/?activo=true').then(r => r.json())
        .then(lista => { parametrosNumericos = lista.filter(p => p.tipo_dato === 'NUMERO'); }).catch(() => {});

    const inicial = url.get('proceso') || leerPreferencia('proceso');
    const lotesUrl = url.get('lotes') ? url.get('lotes').split(',').map(Number).filter(Boolean) : null;
    mostrarPestana(lotesUrl ? 'graficas' : (leerPreferencia('pestana') || 'lotes'));
    const receta = procesos.find(p => String(p.id) === String(inicial));
    if (receta && !receta.activo) document.getElementById('verArchivadas').checked = true;
    pintarPlantillas();
    if (receta) {
        select.value = inicial;
        await cambiarProceso({ lotesUrl });
    }
}

// Barra de plantillas (recetas), como en el diseñador de procesos
function pintarPlantillas() {
    const archivadas = document.getElementById('verArchivadas').checked;
    const actual = document.getElementById('filtroProceso').value;
    const lista = procesos.filter(p => archivadas || p.activo || String(p.id) === actual);
    document.getElementById('listaPlantillas').innerHTML = lista.length ? lista.map(p => `
        <button type="button" class="plantilla ${String(p.id) === actual ? 'plantilla--activa' : ''} ${p.activo ? '' : 'plantilla--archivada'}"
                onclick="elegirPlantilla(${p.id})" aria-pressed="${String(p.id) === actual}">
            <span class="plantilla__nombre">${escaparHtml(p.nombre)}${p.activo ? '' : ' <small>📦 archivada</small>'}</span>
            <span class="plantilla__detalle">${p.etapas} etapa${p.etapas === 1 ? '' : 's'} · ${p.actividades} actividad${p.actividades === 1 ? '' : 'es'}</span>
            <span class="plantilla__detalle">${p.lotes_con_datos} de ${p.lotes} lote${p.lotes === 1 ? '' : 's'} con datos</span>
        </button>`).join('') : '<span class="estado-vacio">No hay plantillas.</span>';
}

function elegirPlantilla(id) {
    const select = document.getElementById('filtroProceso');
    if (select.value === String(id)) return;
    select.value = String(id);
    cambiarProceso();
}

async function cambiarProceso({ lotesUrl = null } = {}) {
    const proceso = document.getElementById('filtroProceso').value;
    document.getElementById('btnIndicadores').disabled = !proceso;
    pintarPlantillas();
    const receta = procesos.find(p => String(p.id) === proceso);
    document.getElementById('recetaElegida').innerHTML = receta
        ? `<span class="receta-elegida__eyebrow">Plantilla</span> <strong>${escaparHtml(receta.nombre)}</strong>
           <small>${receta.etapas} etapa${receta.etapas === 1 ? '' : 's'} · ${receta.actividades} actividad${receta.actividades === 1 ? '' : 'es'}</small>`
        : 'Elige una plantilla a la izquierda.';
    infoReceta = null; analisis = null; analisisVigente = false;
    elegidos = new Set(); destacados = [];
    zoomPorEje = {};
    if (!proceso) {
        pintarTablaLotes(); pintarGraficas(); pintarIndicadores(); pintarComparar();
        return;
    }
    guardarPreferencia('proceso', proceso);
    document.getElementById('cuerpoLotes').innerHTML = '<tr><td colspan="7" class="estado-vacio">Cargando lotes…</td></tr>';
    infoReceta = await fetch(`/api/analisis-proceso/lotes/?proceso=${proceso}`).then(r => r.json());
    const guardada = leerPreferencia(`seleccion-${proceso}`) || {};
    document.getElementById('filtroEtapa').innerHTML = '<option value="">Todas las etapas</option>'
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
    leerComparar();
    leerEscalasGraficas();
    pintarTablaLotes();
    await cargarIndicadores();
    if (pestana !== 'lotes') await cargarAnalisis();
}

function cambiarEtapa() {
    zoomPorEje = {};
    guardarSeleccion();
    cargarAnalisis();
}

async function cargarAnalisis() {
    const proceso = document.getElementById('filtroProceso').value;
    analisisVigente = true;
    if (!proceso || !elegidos.size) {
        analisis = null;
        pintarGraficas(); pintarIndicadores(); pintarComparar();
        return;
    }
    const numero = ++peticionAnalisis;
    const rejilla = document.getElementById('rejillaGraficas');
    rejilla.classList.add('cargando');
    if (!analisis) rejilla.innerHTML = '<div class="panel estado-vacio">Cargando datos de los lotes…</div>';
    const etapa = document.getElementById('filtroEtapa').value;
    try {
        // Los destacados van completos; con muchos lotes, el resto llega reducido (misma forma, menos puntos)
        const res = await fetch(`/api/analisis-proceso/?proceso=${proceso}&lotes=${[...elegidos].join(',')}`
            + `&completos=${destacados.join(',')}${etapa ? `&etapa=${etapa}` : ''}`);
        const data = await res.json();
        if (numero !== peticionAnalisis) return;  // llegó una respuesta más nueva
        if (!res.ok) throw new Error(data.error || data.detail || 'No se pudo cargar el análisis.');
        analisis = data;
        pintarGraficas(); pintarIndicadores(); pintarComparar();
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
    else {
        pintarGraficas(); pintarIndicadores(); pintarComparar();
        if (destacados.includes(id)) completarLote(id);
    }
}

// Un lote que llegó reducido y ahora se destaca: se piden solo sus datos completos y se mezclan
async function completarLote(id) {
    const info = analisis && analisis.lotes.find(l => l.id === id);
    if (!info || !info.reducido) return;
    const proceso = document.getElementById('filtroProceso').value;
    const etapa = document.getElementById('filtroEtapa').value;
    const numero = peticionAnalisis;
    try {
        const res = await fetch(`/api/analisis-proceso/?proceso=${proceso}&lotes=${id}&completos=${id}${etapa ? `&etapa=${etapa}` : ''}`);
        if (!res.ok) return;
        const data = await res.json();
        if (numero !== peticionAnalisis || !analisis) return;  // mientras tanto se recargó todo
        // Los puntos traen el índice de su tarea en la lista de la respuesta: se pasa a la lista vigente
        const indice = new Map(analisis.tareas.map((t, i) => [t, i]));
        const mapa = data.tareas.map(t => {
            if (!indice.has(t)) { indice.set(t, analisis.tareas.length); analisis.tareas.push(t); }
            return indice.get(t);
        });
        const porClave = new Map(analisis.parametros.map(p => [p.clave, p]));
        for (const p of data.parametros) {
            const destino = porClave.get(p.clave);
            const serie = p.series[String(id)];
            if (destino && serie) destino.series[String(id)] = serie.map(pt => { const c = pt.slice(); c[6] = mapa[pt[6]]; return c; });
        }
        info.reducido = false;
        pintarGraficas(); pintarComparar();
    } catch (err) {
        console.warn('No se pudieron traer los datos completos del lote', err);
    }
}

function pintarTablaLotes() {
    document.getElementById('conteoPestanaLotes').textContent = elegidos.size;
    const cuerpo = document.getElementById('cuerpoLotes');
    if (!infoReceta) {
        cuerpo.innerHTML = '<tr><td colspan="7" class="estado-vacio">Elige una receta.</td></tr>';
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
            <td><button type="button" class="btn-destacar" title="Informe del lote en PDF o Excel"
                    onclick="abrirInformeLote({ loteId: ${l.id}, procesoId: ${infoReceta.proceso.id}, identificador: '${escaparHtml(l.identificador).replace(/'/g, '&#39;')}' })">🧾 Informe</button></td>
        </tr>`;
    }).join('') : '<tr><td colspan="7" class="estado-vacio">Ningún lote coincide con los filtros.</td></tr>';
}

// ------------------------------------------------------------------
// Pestaña Gráficas
// ------------------------------------------------------------------
async function exportarExcelElegidos(boton) {
    const proceso = document.getElementById('filtroProceso').value;
    if (!proceso || !elegidos.size) { alert('Elige una receta y al menos un lote.'); return; }
    const etapa = document.getElementById('filtroEtapa').value;
    const texto = boton.textContent;
    boton.disabled = true;
    boton.textContent = '⏳ Generando…';
    try {
        await descargarArchivo(`/api/informes-proceso/lotes/?proceso=${proceso}&lotes=${[...elegidos].join(',')}${etapa ? `&etapa=${etapa}` : ''}`, 'datos.xlsx');
    } catch (err) {
        alert(err.message);
    } finally {
        boton.disabled = false;
        boton.textContent = texto;
    }
}

function cambiarOpcion() {
    guardarSeleccion();
    pintarGraficas();
    pintarComparar();
}

function restablecerZoom() {
    zoomPorEje = {};
    pintarGraficas();
}

function destacarPorNombre(input) {
    const lote = analisis && analisis.lotes.find(l => l.identificador.toLowerCase() === input.value.trim().toLowerCase());
    input.value = '';
    if (lote && !destacados.includes(lote.id)) alternarDestacado(lote.id);
}

function elegirEtapa(id) {
    document.getElementById('filtroEtapa').value = id ? String(id) : '';
    cambiarEtapa();
    pintarBarraGraficas();
}

function pintarBarraGraficas() {
    const etapaActual = document.getElementById('filtroEtapa').value;
    const etapas = infoReceta ? infoReceta.etapas : [];
    document.getElementById('filtroEtapas').innerHTML = etapas.length > 1 ? '<span class="destacados__titulo">Etapas</span>'
        + [{ id: '', nombre: 'Todas' }, ...etapas].map(e => `
            <button type="button" role="tab" class="chip-etapa ${String(e.id) === etapaActual ? 'chip-etapa--activa' : ''}"
                    aria-selected="${String(e.id) === etapaActual}" onclick="elegirEtapa('${e.id}')">${escaparHtml(e.nombre)}</button>`).join('') : '';
    const lotesPorId = Object.fromEntries((analisis ? analisis.lotes : []).map(l => [l.id, l]));
    document.getElementById('chipsDestacados').innerHTML = destacados.length ? destacados.map(id => `
        <button type="button" class="chip-lote chip-lote--elegido" onclick="alternarDestacado(${id})" title="Quitar el color">
            <i class="chip-lote__color" style="background:${colorDe(id)}"></i><strong>${escaparHtml(lotesPorId[id] ? lotesPorId[id].identificador : `#${id}`)}</strong> ✕
        </button>`).join('') : '<span class="sin-dato">Ninguno: clic en una línea para destacarla.</span>';
    document.getElementById('listaDestacar').innerHTML = (analisis ? analisis.lotes : [])
        .filter(l => !destacados.includes(l.id)).map(l => `<option value="${escaparHtml(l.identificador)}">`).join('');
    document.getElementById('btnRestablecerZoom').hidden = !Object.values(zoomPorEje).some(Boolean);

    const codigos = new Set();
    const parametros = analisis ? analisis.parametros.filter(p => Object.keys(p.series).length && !codigos.has(p.codigo) && codigos.add(p.codigo)) : [];
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
            <span class="tarjeta-grafica__nombre" ${ampliada ? '' : `onclick="abrirGraficaGrande('${p.clave}')" title="Ampliar"`}>
                ${escaparHtml(p.nombre)} ${p.unidad ? `<small>${escaparHtml(p.unidad)}</small>` : ''}
                ${p.calculado ? '<span class="etiqueta-calculado" title="Calculado con su fórmula">ƒ</span>' : ''}</span>
            <span class="tarjeta-grafica__acciones">
                <span class="tarjeta-grafica__resumen"></span>
                <button type="button" class="btn-ampliar btn-escalas-tarjeta" onclick="alternarEscalasTarjeta('${p.clave}')"
                        title="Fijar mínimo, máximo e incremento de los ejes">⚙ Escalas</button>
                ${ampliada ? '' : `<button type="button" class="btn-ampliar" onclick="abrirGraficaGrande('${p.clave}')" title="Abrir en grande">⤢ Ampliar</button>`}
            </span>
        </header>
        ${ampliada ? `<div class="tarjeta-grafica__ubicacion">Etapa ${escaparHtml(p.etapa)} · ${escaparHtml(p.bloque)}</div>` : ''}
        <div class="tg-leyenda tg-leyenda--claro"></div>
        <div class="tarjeta-grafica__escalas"></div>
        <div class="tarjeta-grafica__lienzo"></div>
        <div class="tarjeta-grafica__nota"></div>`;
}

// Dibuja un parámetro en una tarjeta (de la rejilla o del modal ampliado)
function dibujarTarjeta(tarjeta, p, alto, animar = false) {
    const banda = document.getElementById('opcionBanda').checked;
    const mostrarPuntos = document.getElementById('opcionPuntos').checked;
    const lotesPorId = Object.fromEntries(analisis.lotes.map(l => [String(l.id), l]));
    const ref = p.referencia || {};
    const porEtapa = ref.eje_edad === 'ETAPA';
    const ejeClave = porEtapa ? `ETAPA-${p.etapa_id}` : 'LOTE';   // la edad de cada etapa es distinta: zoom propio
    const indice = porEtapa ? 1 : 0;
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
        textoPunto: (serie, q) => textoPunto(p, serie, q), tema: 'claro', animar,
        escalaX: escalasGraficas.x[ejeClave] || null, escalaY: escalasGraficas.y[p.clave] || null,
        textoX: porEtapa ? `Edad de la etapa ${p.etapa} (h)` : 'Edad del lote (h)',
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
    // Botón y panel de escalas de esta tarjeta
    const conEscala = Object.keys(escalasGraficas.y[p.clave] || {}).length || Object.keys(escalasGraficas.x[ejeClave] || {}).length;
    const boton = tarjeta.querySelector('.btn-escalas-tarjeta');
    boton.textContent = `⚙ Escalas${conEscala ? ' ●' : ''}`;
    boton.classList.toggle('btn-ampliar--activo', tarjetasConEscalas.has(p.clave));
    boton.setAttribute('aria-expanded', tarjetasConEscalas.has(p.clave));
    tarjeta.querySelector('.tarjeta-grafica__escalas').innerHTML = tarjetasConEscalas.has(p.clave)
        ? htmlEscalasTarjeta(p, ejeClave, porEtapa, r.rango, r.rangoY || [null, null], alto > 300) : '';
    const notas = [];
    if (sinEdad) notas.push(`${sinEdad} dato(s) sin edad (a su lote le falta la edad 0) no se grafican.`);
    if (banda && series.length < 3) notas.push('La banda necesita al menos 3 lotes con datos.');
    if (r.fueraEscala) notas.push(`▲▼ ${r.fueraEscala} dato(s) atípicos de lotes en gris quedan fuera de la escala `
        + '(marcados en el borde; pasa el cursor para ver su valor o acerca la gráfica).');
    tarjeta.querySelector('.tarjeta-grafica__nota').textContent = notas.join(' ');
}

// ------------------------------------------------------------------
// Pestaña Gráficas: escalas manuales por tarjeta (Y del parámetro; X compartido por las gráficas con la misma edad)
// ------------------------------------------------------------------
function claveEscalasGraficas() { return `escalas-${document.getElementById('filtroProceso').value}`; }
function leerEscalasGraficas() {
    const g = leerPreferencia(claveEscalasGraficas()) || {};
    escalasGraficas = { x: g.x || {}, y: g.y || {} };
    tarjetasConEscalas = new Set();
}
function alternarEscalasTarjeta(clave) {
    if (tarjetasConEscalas.has(clave)) tarjetasConEscalas.delete(clave); else tarjetasConEscalas.add(clave);
    pintarGraficas();
}
function cambiarEscalaGrafica(eje, clave, campo, valor) {
    const destino = escalasGraficas[eje];
    const e = destino[clave] = destino[clave] || {};
    const n = numeroEscala(valor);
    if (n === null) delete e[campo]; else e[campo] = n;
    if (!Object.keys(e).length) delete destino[clave];
    guardarPreferencia(claveEscalasGraficas(), escalasGraficas);
    // El eje X se comparte: se redibujan todas; el foco vuelve a la casilla a la que se pasó (Tab)
    requestAnimationFrame(() => {
        const activo = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.escala : null;
        pintarGraficas();
        if (activo) { const campoNuevo = document.querySelector(`[data-escala="${activo}"]`); if (campoNuevo) campoNuevo.focus(); }
    });
}
function restablecerEscalaGrafica(eje, clave) {
    delete escalasGraficas[eje][clave];
    guardarPreferencia(claveEscalasGraficas(), escalasGraficas);
    pintarGraficas();
}
function htmlEscalasTarjeta(p, ejeClave, porEtapa, autoX, autoY, grande) {
    const donde = grande ? 'g' : 'n';
    const auto = (v) => v === null || v === undefined ? 'auto' : corto(v);
    const fila = (eje, clave, nombre, unidad, autos, nota) => {
        const e = escalasGraficas[eje][clave] || {};
        const error = e.min !== undefined && e.max !== undefined && e.min >= e.max ? 'El mínimo debe ser menor que el máximo: se usa el automático.'
            : e.paso !== undefined && e.paso <= 0 ? 'El incremento debe ser mayor que cero: se usa el automático.' : '';
        const celda = (campo, marcador) => `<td><input type="text" inputmode="decimal" class="campo-escala"
            data-escala="${donde}-${p.clave}-${eje}-${campo}" value="${e[campo] ?? ''}" placeholder="${marcador}"
            onchange="cambiarEscalaGrafica('${eje}', '${clave}', '${campo}', this.value)" aria-label="${campo} del ${escaparHtml(nombre)}"></td>`;
        return `<tr class="${error ? 'fila-escala--error' : ''}" title="${error}">
            <th>${escaparHtml(nombre)} ${unidad ? `<small>${escaparHtml(unidad)}</small>` : ''}${error ? ' ⚠️' : ''}
                ${nota ? `<small class="nota-escala">${nota}</small>` : ''}</th>
            ${celda('min', auto(autos[0]))}${celda('max', auto(autos[1]))}${celda('paso', 'auto')}
            <td><button type="button" class="btn-restablecer" onclick="restablecerEscalaGrafica('${eje}', '${clave}')" title="Volver a automático"
                ${Object.keys(e).length ? '' : 'disabled'}>↺</button></td></tr>`;
    };
    return `
        <div class="panel-escalas panel-escalas--claro">
            <table class="tabla-escalas">
                <thead><tr><th>Eje</th><th>Mínimo</th><th>Máximo</th><th>Incremento</th><th></th></tr></thead>
                <tbody>
                    ${fila('y', p.clave, `Eje Y · ${p.nombre}`, p.unidad, autoY, '')}
                    ${fila('x', ejeClave, porEtapa ? `Eje X · edad de la etapa ${p.etapa}` : 'Eje X · edad del lote', 'h', autoX,
                           'se aplica a todas las gráficas con esta edad')}
                </tbody>
            </table>
            <p class="panel-escalas__pie">Vacío = automático (en gris, el valor actual). Incremento = distancia entre marcas.
                Los datos fuera del rango quedan marcados ▲▼ en el borde. El zoom por arrastre la sustituye mientras está activo.</p>
        </div>`;
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
    const reducidos = analisis.lotes.filter(l => l.reducido).length;
    const aviso = document.getElementById('avisoReducidos');
    aviso.hidden = !reducidos;
    aviso.textContent = reducidos
        ? `⚡ Con muchos lotes, ${reducidos} lotes en gris se dibujan con hasta ${analisis.max_puntos_reducidos} puntos por gráfica `
          + '(se conservan máximos, mínimos y valores fuera de límites). Los destacados van completos; destaca un lote para ver todos sus datos.'
        : '';
    const parametros = parametrosVisibles();
    if (!parametros.length) {
        const conDatos = analisis.parametros.some(p => Object.keys(p.series).length);
        const vacio = !analisis.parametros.length;
        rejilla.innerHTML = `<div class="panel estado-vacio">${conDatos ? 'Todos los parámetros están ocultos: actívalos arriba.'
            : vacio ? 'Esta plantilla (o etapa) no captura parámetros numéricos: configúralos en el diseñador de procesos.'
            : 'Los lotes elegidos no tienen datos en esta plantilla o etapa.'}</div>`;
        return;
    }
    // Como en el diseñador: una sección por etapa y, dentro, un bloque por actividad · sección de captura
    const grupos = [];
    parametros.forEach(p => {
        let g = grupos[grupos.length - 1];
        if (!g || g.etapa_id !== p.etapa_id) grupos.push(g = { etapa_id: p.etapa_id, etapa: p.etapa, bloques: [] });
        let b = g.bloques[g.bloques.length - 1];
        if (!b || b.titulo !== p.bloque) g.bloques.push(b = { titulo: p.bloque, parametros: [] });
        b.parametros.push(p);
    });
    rejilla.innerHTML = grupos.map(g => `
        <section class="seccion-etapa" aria-label="Etapa ${escaparHtml(g.etapa)}">
            <header class="seccion-etapa__titulo">
                <span class="seccion-etapa__icono">📁</span> Etapa <strong>${escaparHtml(g.etapa)}</strong>
                <small>${g.bloques.reduce((n, b) => n + b.parametros.length, 0)} gráficas</small>
            </header>
            ${g.bloques.map(b => `
                <div class="bloque-actividad">
                    <div class="bloque-actividad__titulo">${escaparHtml(b.titulo)}</div>
                    <div class="rejilla-tarjetas">
                        ${b.parametros.map(p => `<article class="tarjeta-grafica" data-clave="${p.clave}">${htmlTarjeta(p)}</article>`).join('')}
                    </div>
                </div>`).join('')}
        </section>`).join('');
    const vista = [document.getElementById('filtroProceso').value, document.getElementById('filtroEtapa').value, [...elegidos].sort().join(',')].join('|');
    const animar = vista !== vistaAnimada;
    vistaAnimada = vista;
    parametros.forEach(p => dibujarTarjeta(rejilla.querySelector(`[data-clave="${p.clave}"]`), p, 290, animar));
    pintarGraficaGrande();
}

// ------------------------------------------------------------------
// Gráfica ampliada (modal)
// ------------------------------------------------------------------
let parametroAmpliado = null;

function abrirGraficaGrande(clave) {
    parametroAmpliado = clave;
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
    const i = lista.findIndex(p => p.clave === parametroAmpliado);
    if (i < 0 || lista.length < 2) return;
    parametroAmpliado = lista[(i + delta + lista.length) % lista.length].clave;
    pintarGraficaGrande();
}

function pintarGraficaGrande() {
    if (parametroAmpliado === null) return;
    const lista = parametrosVisibles();
    const i = lista.findIndex(p => p.clave === parametroAmpliado);
    if (i < 0) { cerrarGraficaGrande(); return; }
    const p = lista[i];
    const tarjeta = document.getElementById('tarjetaGrande');
    tarjeta.innerHTML = htmlTarjeta(p, true);
    document.getElementById('posicionGrafica').textContent = `${i + 1} de ${lista.length}`;
    // Alto según la ventana: lo que queda después del encabezado, la leyenda y la nota
    const alto = Math.max(320, Math.min(window.innerHeight - 230 - (tarjetasConEscalas.has(p.clave) ? 120 : 0), 900));
    dibujarTarjeta(tarjeta, p, alto);
}

let temporizadorAncho = null;
window.addEventListener('resize', () => {
    clearTimeout(temporizadorAncho);
    temporizadorAncho = setTimeout(() => { pintarGraficas(); pintarComparar(); }, 200);   // también redibuja la ampliada
});

// ------------------------------------------------------------------
// Pestaña Comparar: varios parámetros de los lotes elegidos
// ------------------------------------------------------------------
const MAX_COMPARAR = 6;
const MAX_EJES = 4;              // vista de ejes múltiples: más ejes ya no se pueden leer
let compSeleccion = [];          // claves (etapa-parámetro) en el orden en que se eligieron
let compVista = 'apiladas';
let compZoom = null;
let compEscalas = { x: {}, pct: {}, y: {} };   // escalas manuales: {min, max, paso} del eje X, del eje % y de cada parámetro
let compColores = {};            // color elegido por parámetro (clave → '#rrggbb') en superpuestas y ejes múltiples
let compVerEscalas = false;      // panel de escalas abierto
let compAmpliada = false;        // ventana flotante abierta

function claveComparar() { return `comparar-${document.getElementById('filtroProceso').value}`; }

function guardarComparar() {
    guardarPreferencia(claveComparar(), { seleccion: compSeleccion, vista: compVista,
        eje: document.getElementById('compEje').value, soloDestacados: document.getElementById('compSoloDestacados').checked,
        escalas: compEscalas, colores: compColores });
}

function leerComparar() {
    const g = leerPreferencia(claveComparar()) || {};
    compSeleccion = g.seleccion || [];
    compVista = g.vista || 'apiladas';
    document.getElementById('compEje').value = g.eje || 'LOTE';
    document.getElementById('compSoloDestacados').checked = !!g.soloDestacados;
    const e = g.escalas || {};
    compEscalas = { x: e.x || {}, pct: e.pct || {}, y: e.y || {} };
    compColores = Object.fromEntries(Object.entries(g.colores || {}).filter(([, c]) => /^#[0-9a-f]{6}$/i.test(c)));
    compZoom = null;
}

function cambiarComparar(reiniciarZoom = false) {
    if (reiniciarZoom) compZoom = null;
    guardarComparar();
    pintarComparar();
}

function cambiarVistaComparar(vista) {
    compVista = vista;
    cambiarComparar();
}

function alternarComparar(clave) {
    const i = compSeleccion.indexOf(clave);
    if (i >= 0) compSeleccion.splice(i, 1);
    else if (compSeleccion.length >= MAX_COMPARAR) { alert(`Compara hasta ${MAX_COMPARAR} parámetros a la vez.`); return; }
    else compSeleccion.push(clave);
    cambiarComparar();
}

function textoPuntoComparar(p, lote, q) {
    const [edad, , valor, estado, adicional, momento, tarea] = q.crudo;
    return `<strong>${escaparHtml(lote)}</strong> · ${escaparHtml(p.nombre)}<br>
        <strong>${corto(valor)}</strong>${p.unidad ? ' ' + escaparHtml(p.unidad) : ''}${edad !== null ? ` a ${corto(edad)} h` : ''}<br>
        <span class="tg-ayuda__tenue">${escaparHtml(analisis.tareas[tarea] || '')}${adicional ? ' · adicional' : ''}<br>
        ${new Date(momento * 1000).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })}</span>
        ${estado === 2 ? '<br>🚨 Fuera de especificación' : estado === 1 ? '<br>⚠️ Fuera de alerta' : ''}`;
}

function pintarComparar() {
    if (pestana !== 'comparar') return;
    document.querySelectorAll('.segmentado [data-vista]').forEach(b => {
        b.classList.toggle('segmentado--activo', b.dataset.vista === compVista);
        b.setAttribute('aria-checked', b.dataset.vista === compVista);
    });
    const caja = document.getElementById('compGraficas');
    const chips = document.getElementById('compParametros');
    if (!analisis) {
        chips.innerHTML = '';
        caja.innerHTML = `<div class="panel estado-vacio">${!document.getElementById('filtroProceso').value ? 'Elige una plantilla.'
            : !elegidos.size ? 'No hay lotes elegidos: elígelos en la pestaña 🧪 Lotes.' : 'Cargando…'}</div>`;
        return;
    }
    const conDatos = analisis.parametros.filter(p => Object.keys(p.series).length);
    // Los elegidos de otra etapa (si hay una filtrada) se conservan, solo no se muestran
    const visibles = compSeleccion.filter(c => conDatos.some(p => p.clave === c));

    // Parámetros a elegir, agrupados por etapa (como en el diseñador)
    const porEtapa = [];
    conDatos.forEach(p => {
        let g = porEtapa[porEtapa.length - 1];
        if (!g || g.etapa_id !== p.etapa_id) porEtapa.push(g = { etapa: p.etapa, etapa_id: p.etapa_id, parametros: [] });
        g.parametros.push(p);
    });
    const superpuestas = compVista === 'superpuestas';
    const multiEje = compVista === 'ejes';
    const etapaFiltrada = (infoReceta ? infoReceta.etapas : []).find(e => String(e.id) === document.getElementById('filtroEtapa').value);
    const aviso = etapaFiltrada ? `<div class="aviso-etapa">Solo se muestran parámetros de la etapa <strong>${escaparHtml(etapaFiltrada.nombre)}</strong>.
        <button type="button" class="btn-secundario" onclick="elegirEtapa('')">Ver todas las etapas</button></div>` : '';
    chips.innerHTML = aviso + porEtapa.map(g => `
        <div class="comparar-etapa"><span class="destacados__titulo">Etapa ${escaparHtml(g.etapa)}</span>
            ${g.parametros.map(p => {
                const i = visibles.indexOf(p.clave);
                const color = (superpuestas || (multiEje && i < MAX_EJES)) && i >= 0 ? colorParametro(p.clave, i) : '';
                return `<button type="button" class="chip-parametro ${i >= 0 ? 'chip-parametro--activo chip-parametro--elegido' : 'chip-parametro--libre'}"
                        onclick="alternarComparar('${p.clave}')" aria-pressed="${i >= 0}">
                    ${color ? `<i class="chip-lote__color" style="background:${color}"></i>` : ''}${escaparHtml(p.nombre)}${p.unidad ? ` <small>${escaparHtml(p.unidad)}</small>` : ''}</button>`;
            }).join('')}
        </div>`).join('') || '<span class="sin-dato">Los lotes elegidos no tienen datos.</span>';
    // «Solo lotes destacados» sin ningún destacado dejaría la gráfica vacía: se ignora y se avisa
    const filtroDestacados = document.getElementById('compSoloDestacados').checked;
    const soloDestacados = filtroDestacados && destacados.length > 0;
    document.getElementById('compPista').textContent = (visibles.length
        ? `${visibles.length} de ${MAX_COMPARAR} parámetros · arrastra para acercar (todas juntas) · doble clic para volver · clic en una línea para destacar el lote.`
        : 'Elige dos o más parámetros (de cualquier etapa) para compararlos.')
        + (filtroDestacados && !destacados.length ? ' ⚠️ «Solo lotes destacados» no aplica: no hay lotes destacados, se muestran todos.' : '');
    document.getElementById('btnZoomComparar').hidden = !compZoom;
    const ctx = { visibles, conDatos, soloDestacados, superpuestas, multiEje };
    dibujarComparacion(caja, ctx, false);
    if (compAmpliada) {
        if (!visibles.length) cerrarCompararGrande();
        else dibujarComparacion(document.getElementById('compGrande'), ctx, true);
    }
}

// Dibuja la comparación en la pestaña (grande = false) o en la ventana flotante (grande = true)
function dibujarComparacion(caja, { visibles, conDatos, soloDestacados, superpuestas, multiEje }, grande) {
    if (!visibles.length) { caja.innerHTML = ''; return; }
    const eje = document.getElementById('compEje').value;
    const indice = eje === 'FECHA' ? 5 : 0;
    const lotesPorId = Object.fromEntries(analisis.lotes.map(l => [String(l.id), l]));
    const elegidosParametros = visibles.map(c => conDatos.find(p => p.clave === c));
    const seriesDe = (p) => Object.entries(p.series)
        .filter(([id]) => !soloDestacados || destacados.includes(Number(id)))
        .map(([id, puntos]) => ({ id: Number(id), lote: lotesPorId[id] ? lotesPorId[id].identificador : id,
            puntos: puntos.filter(q => q[indice] !== null).map(q => ({ x: q[indice], y: q[2], crudo: q,
                estado: q[3] === 2 ? 'fuera' : q[3] === 1 ? 'alerta' : '' })) }))
        .filter(s => s.puntos.length);
    const xs = elegidosParametros.flatMap(p => seriesDe(p).flatMap(s => s.puntos.map(q => q.x)));
    if (!xs.length) {
        caja.innerHTML = `<div class="panel estado-vacio">${soloDestacados
            ? `Los lotes destacados no tienen datos de estos parámetros.
               <button type="button" class="btn-secundario" onclick="document.getElementById('compSoloDestacados').checked = false; cambiarComparar();">Ver todos los lotes</button>`
            : 'Sin datos.'}</div>`;
        return;
    }
    // Mismo rango X para todas: así quedan alineadas una debajo de otra (o el que se fijó en Escalas)
    let x0 = Math.min(...xs), x1 = Math.max(...xs);
    if (eje === 'FECHA') { const m = Math.max(1800, (x1 - x0) * 0.04); x0 -= m; x1 += m; }
    else { x0 = Math.min(0, x0); x1 = Math.max(x1 + Math.max(6, (x1 - x0) * 0.06), 24); }
    const xAuto = [x0, x1];
    const ex = escalaDe('x');
    if (eje !== 'FECHA') {
        const a = numeroEscala(ex.min), b = numeroEscala(ex.max);
        if ((b ?? x1) > (a ?? x0)) { x0 = a ?? x0; x1 = b ?? x1; }
    }
    const comunes = {
        tema: 'claro', tipoX: eje === 'FECHA' ? 'fecha' : 'numero', rangoX: [x0, x1], zoom: compZoom, grupoGuia: 'comparar',
        textoX: eje === 'FECHA' ? 'Fecha y hora' : 'Edad del lote (h)',
        escalaX: eje === 'FECHA' ? null : { paso: ex.paso },
        alZoom: (rango) => { compZoom = rango; pintarComparar(); }, alElegirSerie: (id) => alternarDestacado(id),
        mostrarPuntos: document.getElementById('opcionPuntos').checked,
    };
    // Filas del panel de escalas: X y luego un eje Y por parámetro (o el de % en superpuestas)
    const filas = [{ clave: 'x', nombre: eje === 'FECHA' ? 'Eje X (fecha: usa el zoom)' : 'Eje X · edad del lote', unidad: eje === 'FECHA' ? '' : 'h',
                     auto: xAuto, deshabilitado: eje === 'FECHA' }];
    const barra = `<div class="barra-comparacion">
            ${compZoom ? '<span class="barra-comparacion__aviso">🔍 Con zoom, la escala se ajusta a lo visible (doble clic para volver)</span>' : ''}
            <button type="button" class="btn-ampliar${compVerEscalas ? ' btn-ampliar--activo' : ''}" onclick="alternarEscalas()"
                    aria-expanded="${compVerEscalas}" title="Fijar mínimo, máximo e incremento de cada eje${superpuestas || multiEje ? ' y el color de cada parámetro' : ''}">⚙ ${superpuestas || multiEje ? 'Escalas y colores' : 'Escalas'}${hayEscalas() || (Object.keys(compColores).length && (superpuestas || multiEje)) ? ' ●' : ''}</button>
            ${grande ? '' : '<button type="button" class="btn-ampliar" onclick="abrirCompararGrande()" title="Abrir en una ventana grande">⤢ Ampliar</button>'}
        </div><div class="hueco-escalas"></div>`;
    let coloresEditables = null;   // colores por parámetro (solo superpuestas y ejes múltiples)
    const ponerEscalas = () => {
        const hueco = caja.querySelector('.hueco-escalas');
        if (hueco) hueco.outerHTML = compVerEscalas ? htmlEscalas(filas, grande, superpuestas || multiEje ? coloresEditables : null) : '';
    };

    if (!superpuestas && !multiEje) {
        const alto = grande ? Math.max(220, Math.min(560, Math.floor((window.innerHeight - 200 - (compVerEscalas ? 70 + (elegidosParametros.length + 1) * 34 : 0)) / elegidosParametros.length) - 80)) : 230;
        caja.innerHTML = barra + elegidosParametros.map(p => `
            <article class="tarjeta-grafica tarjeta-grafica--apilada" data-clave="${p.clave}">
                <header class="tarjeta-grafica__titulo">
                    <span>${escaparHtml(p.nombre)} ${p.unidad ? `<small>${escaparHtml(p.unidad)}</small>` : ''}
                        <small class="tarjeta-grafica__etapa">Etapa ${escaparHtml(p.etapa)}</small></span>
                    <span class="tarjeta-grafica__resumen"></span>
                </header>
                <div class="tg-leyenda tg-leyenda--claro"></div>
                <div class="tarjeta-grafica__lienzo tarjeta-grafica__lienzo--apilada"></div>
            </article>`).join('');
        elegidosParametros.forEach(p => {
            const tarjeta = caja.querySelector(`[data-clave="${p.clave}"]`);
            const series = seriesDe(p).map(s => {
                const color = colorDe(s.id);
                return { id: s.id, nombre: s.lote, color, destacada: !!color, puntos: s.puntos };
            }).sort((a, b) => (a.destacada - b.destacada) || (destacados.indexOf(a.id) - destacados.indexOf(b.id)));
            const ref = p.referencia || {};
            const curva = eje === 'LOTE' && ref.eje_edad !== 'ETAPA' ? ref.curva || [] : [];   // la curva va contra la edad del lote
            const ey = escalaDe(p.clave);
            const r = graficaLineas(tarjeta.querySelector('.tarjeta-grafica__lienzo'), {
                ...comunes, series, limites: p.limites, curva, objetivo: ref.objetivo, alto,
                banda: document.getElementById('opcionBanda').checked, escalaY: ey,
                textoPunto: (serie, q) => textoPuntoComparar(p, serie.nombre, q),
            });
            filas.push({ clave: p.clave, nombre: `${p.nombre} (${p.etapa})`, unidad: p.unidad, auto: r.rangoY || [null, null] });
            const conColor = series.filter(s => s.destacada);
            tarjeta.querySelector('.tg-leyenda').innerHTML = leyendaGrafica({
                series: conColor.map(s => ({ color: s.color, etiqueta: escaparHtml(s.nombre) })), fondo: series.length - conColor.length,
                banda: document.getElementById('opcionBanda').checked && series.length >= 3, curva: r.curvaVisible,
                objetivo: ref.objetivo !== null && ref.objetivo !== undefined, limites: p.limites,
            });
            tarjeta.querySelector('.tarjeta-grafica__resumen').textContent = `${series.length} lote${series.length === 1 ? '' : 's'}`
                + (r.fueraEscala ? ` · ▲▼ ${r.fueraEscala} fuera de escala` : '');
        });
        ponerEscalas();
        return;
    }

    // Superpuestas: cada parámetro escalado a 0–100 % de su propio rango; el color es el parámetro,
    // los lotes destacados van con línea gruesa y el resto delgada.
    // Ejes múltiples: igual, pero cada parámetro dibuja su eje con sus valores reales (hasta MAX_EJES); su rango
    // (con margen) va de 0 a 100 y en Escalas se puede fijar mínimo, máximo e incremento de cada eje.
    // Color = parámetro; tipo de trazo = lote destacado (continuo, guiones, puntos, guion-punto; los primeros 4)
    const enGrafica = multiEje ? elegidosParametros.slice(0, MAX_EJES) : elegidosParametros;
    const series = [], rangos = [];
    coloresEditables = enGrafica.map((p, i) => ({ clave: p.clave, nombre: `${p.nombre} (${p.etapa})`, color: colorParametro(p.clave, i) }));
    enGrafica.forEach((p, i) => {
        const color = colorParametro(p.clave, i);
        const propias = seriesDe(p);
        const valores = propias.flatMap(s => s.puntos.map(q => q.y));
        // Rango de cada parámetro sin valores atípicos (P2–P98 + margen): los que quedan fuera se marcan en el borde
        const orden = [...valores].sort((a, b) => a - b);
        const cuantil = (f) => orden[Math.round(f * (orden.length - 1))];
        let vMin = orden[0], vMax = orden[orden.length - 1];
        if (orden.length >= 30) {
            const ancho = (cuantil(0.98) - cuantil(0.02)) || Math.abs(cuantil(0.98)) * 0.1 || 1;
            vMax = Math.min(vMax, cuantil(0.98) + ancho * 0.6);
            vMin = Math.max(vMin, cuantil(0.02) - ancho * 0.6);
        }
        let lo = vMin, hi = vMax;
        if (multiEje) {
            const margen = (vMax - vMin) * 0.05 || Math.abs(vMax) * 0.05 || 1;
            lo = vMin - margen; hi = vMax + margen;
            filas.push({ clave: p.clave, nombre: `${p.nombre} (${p.etapa})`, unidad: p.unidad, color, auto: [lo, hi] });
            const e = escalaDe(p.clave), a = numeroEscala(e.min), b = numeroEscala(e.max);
            if ((b ?? hi) > (a ?? lo)) { lo = a ?? lo; hi = b ?? hi; }
        }
        const atipicos = valores.filter(v => v > (multiEje ? hi : vMax) || v < (multiEje ? lo : vMin)).length;
        const escala = (v) => hi > lo ? (v - lo) / (hi - lo) * 100 : 50;
        rangos.push({ p, color, vMin, vMax, lo, hi, atipicos });
        propias.forEach(s => {
            const n = destacados.indexOf(s.id);
            const destacado = n >= 0 && n < TRAZOS_SERIES.length;
            series.push({ id: s.id, nombre: `${s.lote} · ${p.nombre}`, color, tenue: !destacado, destacada: destacado,
                ...(destacado ? { trazo: TRAZOS_SERIES[n], marca: MARCAS_SERIES[n] } : {}),
                puntos: s.puntos.map(q => ({ ...q, y: escala(q.y) })), lote: s.lote, parametro: p });
        });
    });
    series.sort((a, b) => a.destacada - b.destacada);
    const sobran = elegidosParametros.length - enGrafica.length;
    // Leyenda de lotes: cada destacado (hasta 4) con su tipo de trazo
    const lotesConTrazo = destacados.slice(0, TRAZOS_SERIES.length)
        .filter(id => series.some(s => s.id === id && s.destacada))
        .map(id => ({ nombre: (analisis.lotes.find(l => l.id === id) || {}).identificador || id,
                      trazo: TRAZOS_SERIES[destacados.indexOf(id)], marca: MARCAS_SERIES[destacados.indexOf(id)] }));
    const muestraTrazo = (t, m) => `<svg class="tg-l-trazo" viewBox="0 0 30 12" aria-hidden="true"><line x1="2" y1="6" x2="28" y2="6" stroke-dasharray="${t}"/>
        <path d="${caminoMarca(m, 15, 6, 3.4)}"${String(m).endsWith('-hueco') ? ' class="hueca"' : ''}/></svg>`;
    const leyendaLotes = lotesConTrazo.length
        ? `<div class="tg-leyenda tg-leyenda--claro leyenda-trazos"><strong>Lotes:</strong>${lotesConTrazo.map(l => `<span>${muestraTrazo(l.trazo, l.marca)}${escaparHtml(l.nombre)}</span>`).join('')}
            <span class="sin-dato">${destacados.length > TRAZOS_SERIES.length ? `· solo los primeros ${TRAZOS_SERIES.length} destacados llevan trazo propio (los demás van delgados; para más lotes usa Apiladas)` : '· las delgadas: los demás lotes'}</span></div>`
        : '<div class="tg-leyenda tg-leyenda--claro leyenda-trazos"><span class="sin-dato">Destaca lotes (hasta 4) para verlos con trazo y figura propios: continuo ●, guiones □, puntos ▲ o guion-punto ◇.</span></div>';
    const nota = multiEje
        ? 'Cada eje está en las unidades de su parámetro (mismo color que su línea). Las escalas son independientes: '
          + 'que dos líneas se crucen o vayan juntas no significa que sus valores sean iguales.'
          + (sobran ? ` Solo caben ${MAX_EJES} ejes: ${sobran} parámetro(s) elegido(s) no se dibujan aquí (míralos en Apiladas).` : '')
        : '0 % = el valor más bajo de cada parámetro en estos lotes y 100 % = el más alto; la ficha muestra el valor real.';
    const conAtipicos = rangos.some(r => r.atipicos)
        ? ' Los valores fuera de la escala quedan marcados ▲▼ en el borde; pasa el cursor para ver su valor.' : '';
    caja.innerHTML = barra + `
        <article class="tarjeta-grafica tarjeta-grafica--superpuesta${grande ? ' tarjeta-grafica--comparar-grande' : ''}">
            <header class="tarjeta-grafica__titulo"><span>${enGrafica.map(p => escaparHtml(p.nombre)).join(' · ')}
                <small>${multiEje ? 'cada uno con su eje' : 'escalados de 0 a 100 % de su rango'}</small></span></header>
            <div class="tg-leyenda tg-leyenda--claro">${rangos.map(r => `<span><i class="tg-l" style="border-color:${r.color}"></i>
                ${escaparHtml(r.p.nombre)} <small>(${escaparHtml(r.p.etapa)}: ${corto(r.vMin)} → ${corto(r.vMax)}${r.p.unidad ? ' ' + escaparHtml(r.p.unidad) : ''}${r.atipicos ? ` · ▲▼ ${r.atipicos} fuera de escala` : ''})</small></span>`).join('')}
                </div>
            ${leyendaLotes}
            <div class="tarjeta-grafica__lienzo tarjeta-grafica__lienzo--superpuesta"></div>
            <div class="tarjeta-grafica__nota">${nota}${conAtipicos}</div>
        </article>`;
    // Título de cada eje: la unidad (o el nombre recortado si no tiene) — el nombre completo va en la leyenda
    const tituloEje = (p) => { const t = p.unidad || p.nombre; return t.length > 9 ? `${t.slice(0, 8)}…` : t; };
    // En la ventana flotante: lo que queda de alto (menos el panel de escalas si está abierto)
    const alto = grande ? Math.max(380, window.innerHeight - 290 - (compVerEscalas ? 40 + filas.length * 34 : 0))
        : Math.max(360, Math.min(window.innerHeight - 330, 620));
    const r = graficaLineas(caja.querySelector('.tarjeta-grafica__lienzo'), {
        ...comunes, series, alto, mostrarPuntos: false,
        rangoY: multiEje ? [0, 100] : [-5, 105], escalaY: multiEje ? null : escalaDe('pct'),
        ejesY: multiEje ? rangos.map(g => ({ color: g.color, titulo: tituloEje(g.p), vMin: g.lo, vMax: g.hi, paso: escalaDe(g.p.clave).paso })) : null,
        textoPunto: (serie, q) => textoPuntoComparar(serie.parametro, serie.lote, q),
    });
    if (!multiEje) filas.push({ clave: 'pct', nombre: 'Eje Y · % de su rango', unidad: '%', auto: r.rangoY || [null, null] });
    ponerEscalas();
}

// ------------------------------------------------------------------
// Comparar: escalas manuales (mínimo, máximo e incremento por eje; se guardan por receta)
// ------------------------------------------------------------------
const numeroEscala = (v) => {
    if (v === null || v === undefined || String(v).trim() === '') return null;
    const n = Number(String(v).replace(',', '.'));
    return Number.isFinite(n) ? n : null;
};
// 'x' = eje X, 'pct' = eje de % (superpuestas); cualquier otra clave = un parámetro (etapa-parámetro)
function escalaDe(clave) {
    return (clave === 'x' || clave === 'pct' ? compEscalas[clave] : compEscalas.y[clave]) || {};
}
// Color de un parámetro en las vistas combinadas: el elegido por el usuario o el de la paleta, por su posición
function colorParametro(clave, i) {
    return compColores[clave] || COLORES_SERIES_CLARO[i % COLORES_SERIES_CLARO.length];
}
function cambiarColor(clave, valor) {
    if (!/^#[0-9a-f]{6}$/i.test(valor)) return;
    compColores[clave] = valor.toLowerCase();
    guardarComparar();
    pintarComparar();
}
function restablecerColores() {
    compColores = {};
    guardarComparar();
    pintarComparar();
}
function hayEscalas() {
    return [compEscalas.x, compEscalas.pct, ...Object.values(compEscalas.y)].some(e => e && Object.keys(e).length);
}
function alternarEscalas() {
    compVerEscalas = !compVerEscalas;
    pintarComparar();
}
function cambiarEscala(clave, campo, valor) {
    const destino = clave === 'x' || clave === 'pct' ? compEscalas : compEscalas.y;
    const e = destino[clave] = destino[clave] || {};
    const n = numeroEscala(valor);
    if (n === null) delete e[campo]; else e[campo] = n;
    if (!Object.keys(e).length) delete destino[clave];
    guardarComparar();
    // Se redibuja al soltar el campo; el foco vuelve a la casilla a la que se pasó (Tab)
    requestAnimationFrame(() => {
        const activo = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.escala : null;
        pintarComparar();
        if (activo) { const campoNuevo = document.querySelector(`[data-escala="${activo}"]`); if (campoNuevo) campoNuevo.focus(); }
    });
}
function restablecerEscala(clave) {
    if (clave === 'x' || clave === 'pct') delete compEscalas[clave]; else delete compEscalas.y[clave];
    guardarComparar();
    pintarComparar();
}
function restablecerEscalas() {
    compEscalas = { x: {}, pct: {}, y: {} };
    guardarComparar();
    pintarComparar();
}
function htmlEscalas(filas, grande, colores = null) {
    const donde = grande ? 'g' : 'n';
    // Colores por parámetro (superpuestas y ejes múltiples); avisa si dos quedan iguales o muy parecidos
    const parecidos = (a, b) => {
        const rgb = (c) => [1, 3, 5].map(k => parseInt(c.slice(k, k + 2), 16));
        const [x, y] = [rgb(a), rgb(b)];
        return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) < 60;
    };
    const htmlColores = colores ? `
            <div class="colores-parametros">
                <span class="colores-parametros__titulo">Colores</span>
                ${colores.map((c, i) => {
                    const choca = colores.some((o, j) => j !== i && parecidos(o.color, c.color));
                    return `<label class="color-parametro${choca ? ' color-parametro--choca' : ''}" title="${choca ? 'Se parece mucho al color de otro parámetro' : 'Elegir color'}">
                        <input type="color" value="${c.color}" onchange="cambiarColor('${c.clave}', this.value)" aria-label="Color de ${escaparHtml(c.nombre)}">
                        ${escaparHtml(c.nombre)}${choca ? ' ⚠️' : ''}</label>`;
                }).join('')}
                <button type="button" class="btn-secundario" onclick="restablecerColores()" ${Object.keys(compColores).length ? '' : 'disabled'}>↺ Colores originales</button>
            </div>` : '';
    const auto = (v) => v === null || v === undefined ? 'auto' : corto(v);
    return `
        <div class="panel-escalas">
            <table class="tabla-escalas">
                <thead><tr><th>Eje</th><th>Mínimo</th><th>Máximo</th><th>Incremento</th><th></th></tr></thead>
                <tbody>${filas.map(f => {
                    const e = escalaDe(f.clave);
                    const error = e.min !== undefined && e.max !== undefined && e.min >= e.max ? 'El mínimo debe ser menor que el máximo: se usa el automático.'
                        : e.paso !== undefined && e.paso <= 0 ? 'El incremento debe ser mayor que cero: se usa el automático.' : '';
                    const celda = (campo, marcador) => `<td><input type="text" inputmode="decimal" class="campo-escala" data-escala="${donde}-${f.clave}-${campo}"
                        value="${e[campo] ?? ''}" placeholder="${marcador}" ${f.deshabilitado ? 'disabled' : ''}
                        onchange="cambiarEscala('${f.clave}', '${campo}', this.value)" aria-label="${campo} de ${escaparHtml(f.nombre)}"></td>`;
                    return `<tr class="${error ? 'fila-escala--error' : ''}" title="${error}">
                        <th>${f.color ? `<i class="chip-lote__color" style="background:${f.color}"></i>` : ''}${escaparHtml(f.nombre)}
                            ${f.unidad ? `<small>${escaparHtml(f.unidad)}</small>` : ''}${error ? ' ⚠️' : ''}</th>
                        ${celda('min', auto(f.auto[0]))}${celda('max', auto(f.auto[1]))}${celda('paso', 'auto')}
                        <td><button type="button" class="btn-restablecer" onclick="restablecerEscala('${f.clave}')" title="Volver a automático"
                            ${Object.keys(e).length ? '' : 'disabled'}>↺</button></td>
                    </tr>`;
                }).join('')}</tbody>
            </table>
            <p class="panel-escalas__pie">Vacío = automático (en gris, el valor actual). El incremento es la distancia entre las marcas del eje
                (si da más de 60 marcas se usa el automático). Los datos fuera del rango quedan marcados ▲▼ en el borde. Se guarda para esta receta.
                <button type="button" class="btn-secundario" onclick="restablecerEscalas()" ${hayEscalas() ? '' : 'disabled'}>↺ Todo automático</button></p>
            ${htmlColores}
        </div>`;
}

// ------------------------------------------------------------------
// Comparar en una ventana flotante (grande)
// ------------------------------------------------------------------
function abrirCompararGrande() {
    compAmpliada = true;
    document.getElementById('modalComparar').style.display = 'flex';
    document.body.classList.add('sin-desplazamiento');
    pintarComparar();
}
function cerrarCompararGrande() {
    if (!compAmpliada) return;
    compAmpliada = false;
    document.getElementById('modalComparar').style.display = 'none';
    document.getElementById('compGrande').innerHTML = '';
    document.body.classList.remove('sin-desplazamiento');
}

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
    if (e.key === 'Escape') { cerrarIndicadores(); cerrarGraficaGrande(); cerrarCompararGrande(); }
    if (parametroAmpliado !== null && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        if (e.key === 'ArrowRight') moverGraficaGrande(1);
        if (e.key === 'ArrowLeft') moverGraficaGrande(-1);
    }
});
document.addEventListener('DOMContentLoaded', iniciar);
