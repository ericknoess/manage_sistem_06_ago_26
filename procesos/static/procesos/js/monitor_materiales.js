// procesos/static/procesos/js/monitor_materiales.js
// Monitor de materiales: requerimientos de los lotes agrupados por día y hora (hora local),
// con totales por material. Los datos vienen de /api/materiales-fase/requerimientos/.
// Cada requerimiento muestra su surtido (entregar, recibir, rechazar, devolver: static/core/js/surtido.js).

const NOMBRES_DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

let fechaInicio = inicioDelDia(new Date());
let duracionDias = 3;
let requerimientos = [];
let opcionesCatalogo = { categorias: [], almacenamiento: [] };

function inicioDelDia(fecha) {
    const d = new Date(fecha);
    d.setHours(0, 0, 0, 0);
    return d;
}

function sumarDias(fecha, dias) {
    const d = new Date(fecha);
    d.setDate(d.getDate() + dias);
    return d;
}

function claveDia(fecha) {
    return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
}

function horaTexto(fecha) {
    return fecha.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function fechaCorta(fecha) {
    return fecha.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
}

// --- Periodo -----------------------------------------------------------------

function moverPeriodo(direccion) {
    fechaInicio = sumarDias(fechaInicio, direccion * duracionDias);
    cargarRequerimientos();
}

function irAHoy() {
    fechaInicio = inicioDelDia(new Date());
    cargarRequerimientos();
}

function cambiarFechaInicio(valor) {
    if (!valor) return;
    const [a, m, d] = valor.split('-').map(Number);
    fechaInicio = new Date(a, m - 1, d);
    cargarRequerimientos();
}

function cambiarDuracion(dias) {
    duracionDias = dias;
    cargarRequerimientos();
}

function actualizarControlesPeriodo() {
    const fin = sumarDias(fechaInicio, duracionDias - 1);
    document.getElementById('inputFechaInicio').value = claveDia(fechaInicio);
    document.getElementById('etiquetaPeriodo').innerText = duracionDias === 1
        ? `${NOMBRES_DIAS[fechaInicio.getDay()]} ${fechaCorta(fechaInicio)}`
        : `${fechaCorta(fechaInicio)} – ${fechaCorta(fin)}`;
    document.querySelectorAll('.segmentado button').forEach(b => {
        b.classList.toggle('is-activo', Number(b.dataset.dias) === duracionDias);
    });
}

// --- Datos -------------------------------------------------------------------

async function cargarOpciones() {
    try {
        const res = await fetch('/api/materiales/opciones/');
        opcionesCatalogo = await res.json();
        const llenar = (id, lista) => {
            const select = document.getElementById(id);
            lista.forEach(o => select.insertAdjacentHTML('beforeend', `<option value="${o.valor}">${escaparHtml(o.etiqueta)}</option>`));
        };
        llenar('filtroCategoria', opcionesCatalogo.categorias);
        llenar('filtroAlmacenamiento', opcionesCatalogo.almacenamiento);
    } catch (err) {
        console.error('No se pudieron cargar las opciones del catálogo:', err);
    }
}

async function cargarRequerimientos() {
    actualizarControlesPeriodo();
    const desde = claveDia(fechaInicio);
    const hasta = claveDia(sumarDias(fechaInicio, duracionDias - 1));
    try {
        const res = await fetch(`/api/materiales-fase/requerimientos/?desde=${desde}&hasta=${hasta}`);
        if (!res.ok) throw new Error((await res.json()).error || 'Error del servidor');
        requerimientos = await res.json();
        renderizar();
    } catch (err) {
        document.getElementById('lineaTiempo').innerHTML = `<div class="estado-vacio estado-vacio--error">⚠️ No se pudieron cargar los requerimientos: ${escaparHtml(err.message)}</div>`;
    }
    cargarDevoluciones();
}

async function cargarDevoluciones() {
    const caja = document.getElementById('devolucionesPendientes');
    try {
        const res = await fetch('/api/surtido/?tipo=DEVOLUCION&estado=EN_TRANSITO');
        if (!res.ok) throw new Error('Error del servidor');
        caja.innerHTML = htmlDevolucionesPendientes(await res.json());
    } catch (err) {
        caja.innerHTML = `<div class="estado-vacio estado-vacio--error">⚠️ No se pudieron cargar las devoluciones.</div>`;
    }
}

function filtrar() {
    const texto = normalizarBusqueda(document.getElementById('filtroTexto').value).split(/\s+/).filter(Boolean);
    const categoria = document.getElementById('filtroCategoria').value;
    const almacenamiento = document.getElementById('filtroAlmacenamiento').value;
    return requerimientos.filter(r => {
        if (categoria && r.categoria !== categoria) return false;
        if (almacenamiento && r.condicion_almacenamiento !== almacenamiento) return false;
        if (!texto.length) return true;
        const pajar = normalizarBusqueda(`${r.material} ${r.material_nombre} ${r.lote_codigo} ${r.paso} ${r.actividad}`);
        return texto.every(p => pajar.includes(p));
    });
}

// --- Dibujo ------------------------------------------------------------------

function renderizar() {
    const filas = filtrar();
    renderizarIndicadores(filas);
    renderizarLineaTiempo(filas);
    renderizarTotales(filas);
}

function renderizarIndicadores(filas) {
    const enFrio = filas.filter(r => r.condicion_almacenamiento !== 'AMBIENTE').length;
    const ahora = new Date();
    const atrasados = filas.filter(r => new Date(r.momento_requerido) < ahora && r.fase_estado === 'PENDIENTE').length;
    const sinSurtir = filas.filter(r => new Date(r.momento_requerido) < ahora && r.surtido && r.surtido.estado !== 'COMPLETO').length;
    const indicadores = [
        { valor: filas.length, etiqueta: 'Requerimientos' },
        { valor: new Set(filas.map(r => r.material)).size, etiqueta: 'Materiales distintos' },
        { valor: new Set(filas.map(r => r.lote_codigo)).size, etiqueta: 'Lotes' },
        { valor: enFrio, etiqueta: 'En cadena de frío', clase: enFrio ? 'indicador--frio' : '' },
        { valor: atrasados, etiqueta: 'Hora ya pasada (fase pendiente)', clase: atrasados ? 'indicador--alerta' : '' },
        { valor: sinSurtir, etiqueta: 'Sin surtir completo a su hora', clase: sinSurtir ? 'indicador--alerta' : '' },
    ];
    document.getElementById('indicadores').innerHTML = indicadores.map(i => `
        <div class="indicador ${i.clase || ''}">
            <span class="indicador-valor">${i.valor}</span>
            <span class="indicador-etiqueta">${i.etiqueta}</span>
        </div>`).join('');
}

function renderizarLineaTiempo(filas) {
    // dia -> hora -> filas
    const porDia = new Map();
    for (let i = 0; i < duracionDias; i++) porDia.set(claveDia(sumarDias(fechaInicio, i)), new Map());
    filas.forEach(r => {
        const momento = new Date(r.momento_requerido);
        const horas = porDia.get(claveDia(momento));
        if (!horas) return;
        const hora = momento.getHours();
        if (!horas.has(hora)) horas.set(hora, []);
        horas.get(hora).push(r);
    });

    const ahora = new Date();
    const hoy = claveDia(ahora);
    let html = '';
    porDia.forEach((horas, clave) => {
        const [a, m, d] = clave.split('-').map(Number);
        const fecha = new Date(a, m - 1, d);
        const total = [...horas.values()].reduce((n, lista) => n + lista.length, 0);
        html += `
            <div class="dia ${clave === hoy ? 'dia--hoy' : ''}">
                <div class="dia-encabezado">
                    <span>${NOMBRES_DIAS[fecha.getDay()]} ${fechaCorta(fecha)}${clave === hoy ? ' · HOY' : ''}</span>
                    <span class="dia-conteo">${total} requerimiento${total === 1 ? '' : 's'}</span>
                </div>`;
        if (!total) {
            html += `<div class="estado-vacio">Sin materiales requeridos este día.</div></div>`;
            return;
        }
        [...horas.keys()].sort((x, y) => x - y).forEach(hora => {
            const esHoraActual = clave === hoy && hora === ahora.getHours();
            html += `
                <div class="bloque-hora ${esHoraActual ? 'bloque-hora--actual' : ''}">
                    <div class="bloque-hora__etiqueta">${String(hora).padStart(2, '0')}:00</div>
                    <div class="bloque-hora__tarjetas">${horas.get(hora).map(tarjetaRequerimiento).join('')}</div>
                </div>`;
        });
        html += '</div>';
    });
    document.getElementById('lineaTiempo').innerHTML = html;
}

function tarjetaRequerimiento(r) {
    const momento = new Date(r.momento_requerido);
    const inicio = new Date(r.inicio_actividad);
    const atrasado = momento < new Date() && r.fase_estado === 'PENDIENTE';
    const anticipacion = r.anticipacion_horas
        ? `para la actividad de las ${horaTexto(inicio)}${claveDia(inicio) !== claveDia(momento) ? ` del ${fechaCorta(inicio)}` : ''} (${r.anticipacion_horas} h antes)`
        : 'al inicio de la actividad';
    const etiquetas = [];
    if (r.ajustado) {
        etiquetas.push(r.cantidad_receta === null
            ? `<span class="etiqueta etiqueta--ajuste" title="${escaparHtml(r.motivo_ajuste)}">agregado en el lote</span>`
            : `<span class="etiqueta etiqueta--ajuste" title="${escaparHtml(r.motivo_ajuste)}">ajustado · receta ${formatearCantidad(r.cantidad_receta, r.unidad_medida)}</span>`);
    }
    if (r.fase_estado === 'EN_PROGRESO') etiquetas.push('<span class="etiqueta etiqueta--progreso">fase en progreso</span>');
    if (atrasado) etiquetas.push('<span class="etiqueta etiqueta--alerta">hora ya pasada</span>');

    return `
        <article class="tarjeta ${atrasado ? 'tarjeta--atrasada' : ''} tarjeta--${r.condicion_almacenamiento.toLowerCase()}">
            <div class="tarjeta__principal">
                <span class="tarjeta__hora">${horaTexto(momento)}</span>
                <span class="tarjeta__cantidad">${formatearCantidad(r.cantidad, r.unidad_medida)}</span>
                <span class="tarjeta__material">${escaparHtml(r.material_nombre)}</span>
                <span class="tarjeta__frio" title="${textoAlmacenamiento(r.condicion_almacenamiento)}">${iconoAlmacenamiento(r.condicion_almacenamiento)} ${textoAlmacenamiento(r.condicion_almacenamiento)}</span>
            </div>
            <div class="tarjeta__contexto">
                <span class="tarjeta__codigo">${escaparHtml(r.material)}</span>
                Lote <strong>${escaparHtml(r.lote_codigo)}</strong> · [${escaparHtml(r.paso)}] ${escaparHtml(r.actividad)} · ${anticipacion}
            </div>
            ${etiquetas.length ? `<div class="tarjeta__etiquetas">${etiquetas.join('')}</div>` : ''}
            ${htmlSurtido(r)}
        </article>`;
}

function renderizarTotales(filas) {
    // Clave material + unidad: si la unidad cambió en el catálogo, los lotes anteriores conservan la suya
    const porMaterial = new Map();
    filas.forEach(r => {
        const clave = `${r.material}|${r.unidad_medida}`;
        if (!porMaterial.has(clave)) {
            porMaterial.set(clave, { ...r, total: 0, eventos: 0, porDia: new Map() });
        }
        const t = porMaterial.get(clave);
        t.total += Number(r.cantidad);
        t.eventos += 1;
        const dia = claveDia(new Date(r.momento_requerido));
        t.porDia.set(dia, (t.porDia.get(dia) || 0) + Number(r.cantidad));
    });

    if (!porMaterial.size) {
        document.getElementById('totales').innerHTML = '<div class="estado-vacio">Sin requerimientos en el periodo.</div>';
        return;
    }

    const ordenados = [...porMaterial.values()].sort((a, b) => a.material_nombre.localeCompare(b.material_nombre, 'es'));
    document.getElementById('totales').innerHTML = ordenados.map(t => {
        const desglose = duracionDias > 1
            ? `<div class="total__desglose">${[...t.porDia.entries()].sort().map(([dia, cantidad]) => {
                const [a, m, d] = dia.split('-').map(Number);
                return `<span>${fechaCorta(new Date(a, m - 1, d))}: ${formatearCantidad(cantidad, t.unidad_medida)}</span>`;
            }).join('')}</div>`
            : '';
        return `
            <div class="total">
                <div class="total__encabezado">
                    <span class="total__material">${iconoAlmacenamiento(t.condicion_almacenamiento)} ${escaparHtml(t.material_nombre)}</span>
                    <span class="total__cantidad">${formatearCantidad(t.total, t.unidad_medida)}</span>
                </div>
                <div class="total__meta">${escaparHtml(t.material)} · ${t.eventos} entrega${t.eventos === 1 ? '' : 's'}</div>
                ${desglose}
            </div>`;
    }).join('');
}

document.addEventListener('DOMContentLoaded', async () => {
    configurarSurtido({ alActualizar: cargarRequerimientos });
    await cargarOpciones();
    cargarRequerimientos();
    // Refresca cada 5 minutos: los requerimientos siguen a las reprogramaciones de las fases
    setInterval(cargarRequerimientos, 5 * 60 * 1000);
});
