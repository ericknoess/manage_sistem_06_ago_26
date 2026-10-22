// procesos/static/procesos/js/monitor_equipos.js
// Monitor de equipos: una fila por equipo con sus tramos reservados (preparación + actividad + limpieza)
// en el periodo elegido, y la lista de requerimientos que aún no tienen equipo reservado.
// Datos: /api/equipos/, /api/tipos-equipo/ y /api/equipos-fase/ocupacion/.

const NOMBRES_DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];
const DIAS_AVISO_CALIFICACION = 30;

let fechaInicio = inicioDelDia(new Date());
let duracionDias = 3;
let equipos = [];
let tipos = [];
let ocupacion = { tramos: [], pendientes: [] };

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

function fechaCorta(fecha) {
    return fecha.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
}

function momentoTexto(iso) {
    return new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

// --- Periodo -----------------------------------------------------------------

function moverPeriodo(direccion) {
    fechaInicio = sumarDias(fechaInicio, direccion * duracionDias);
    cargarOcupacion();
}

function irAHoy() {
    fechaInicio = inicioDelDia(new Date());
    cargarOcupacion();
}

function cambiarFechaInicio(valor) {
    if (!valor) return;
    const [a, m, d] = valor.split('-').map(Number);
    fechaInicio = new Date(a, m - 1, d);
    cargarOcupacion();
}

function cambiarDuracion(dias) {
    duracionDias = dias;
    cargarOcupacion();
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

async function cargarCatalogos() {
    try {
        const [resEq, resTipos] = await Promise.all([fetch('/api/equipos/?activo=true'), fetch('/api/tipos-equipo/')]);
        equipos = await resEq.json();
        tipos = await resTipos.json();
        const select = document.getElementById('filtroTipo');
        tipos.filter(t => t.activo).forEach(t => select.insertAdjacentHTML('beforeend', `<option value="${escaparHtml(t.codigo)}">${escaparHtml(t.nombre)}</option>`));
    } catch (e) {
        equipos = [];
    }
}

async function cargarOcupacion() {
    actualizarControlesPeriodo();
    const desde = claveDia(fechaInicio);
    const hasta = claveDia(sumarDias(fechaInicio, duracionDias - 1));
    try {
        const res = await fetch(`/api/equipos-fase/ocupacion/?desde=${desde}&hasta=${hasta}`);
        if (!res.ok) throw new Error();
        ocupacion = await res.json();
        renderizar();
    } catch (e) {
        document.getElementById('cronograma').innerHTML = '<div class="estado-vacio estado-vacio--error">⚠️ No se pudo cargar la ocupación.</div>';
    }
}

// --- Vista -------------------------------------------------------------------

function textoFiltro() {
    return normalizarBusqueda(document.getElementById('filtroTexto').value).split(/\s+/).filter(Boolean);
}

function equiposVisibles() {
    const tipo = document.getElementById('filtroTipo').value;
    const palabras = textoFiltro();
    return equipos.filter(e => {
        if (tipo && e.tipo !== tipo) return false;
        if (!palabras.length) return true;
        const lotes = ocupacion.tramos.filter(t => t.equipo === e.id).map(t => t.lote_codigo).join(' ');
        const pajar = normalizarBusqueda([e.id, e.nombre, e.area, e.tipo_nombre, lotes].join(' '));
        return palabras.every(p => pajar.includes(p));
    });
}

function renderizar() {
    const inicio = fechaInicio.getTime();
    const fin = sumarDias(fechaInicio, duracionDias).getTime();
    const total = fin - inicio;
    const lista = equiposVisibles();
    const porcentaje = (ms) => Math.min(100, Math.max(0, ((ms - inicio) / total) * 100));

    renderizarIndicadores(lista, inicio, fin);
    renderizarPendientes();

    if (!lista.length) {
        document.getElementById('cronograma').innerHTML = '<div class="estado-vacio">No hay equipos que coincidan con el filtro.</div>';
        return;
    }

    // Encabezado: días y marcas de hora (cada 6 h en la semana, cada 3 h en 3 días, cada hora en un día)
    const pasoHoras = duracionDias === 1 ? 1 : duracionDias === 3 ? 3 : 6;
    let marcas = '';
    for (let h = 0; h < duracionDias * 24; h += pasoHoras) {
        const momento = new Date(inicio + h * 3600000);
        const esDia = momento.getHours() === 0;
        marcas += `<span class="marca ${esDia ? 'marca--dia' : ''}" style="left: ${(h / (duracionDias * 24)) * 100}%">${esDia
            ? `${NOMBRES_DIAS[momento.getDay()].slice(0, 3)} ${momento.getDate()}`
            : String(momento.getHours()).padStart(2, '0') + 'h'}</span>`;
    }
    const ahora = Date.now();
    const lineaAhora = ahora >= inicio && ahora < fin ? `<div class="linea-ahora" style="left: ${porcentaje(ahora)}%" data-tooltip="Ahora"></div>` : '';

    const filas = lista.map(e => {
        const tramos = ocupacion.tramos.filter(t => t.equipo === e.id);
        const bloques = tramos.map(t => {
            const tInicio = new Date(t.inicio).getTime();
            const tFin = new Date(t.fin).getTime();
            const izquierda = porcentaje(tInicio);
            const ancho = Math.max(porcentaje(tFin) - izquierda, 0.4);
            // Parte de actividad dentro del tramo (lo demás es preparación o limpieza)
            const aInicio = Math.max(new Date(t.inicio_actividad).getTime(), tInicio);
            const aFin = Math.min(new Date(t.fin_actividad).getTime(), tFin);
            const duracion = tFin - tInicio || 1;
            const actividad = aFin > aInicio
                ? `<div class="bloque__actividad" style="left: ${((aInicio - tInicio) / duracion) * 100}%; width: ${((aFin - aInicio) / duracion) * 100}%"></div>` : '';
            const clase = { EN_PROGRESO: 'progreso', COMPLETADA: 'completada' }[t.fase_estado] || 'pendiente';
            const titulo = `${t.lote_codigo} · [${t.paso}] ${t.actividad}\nOcupa: ${momentoTexto(t.inicio)} – ${momentoTexto(t.fin)}`
                + `\nActividad: ${momentoTexto(t.inicio_actividad)} – ${momentoTexto(t.fin_actividad)}`
                + (t.cambiado ? `\n🔁 Tramo por cambio de equipo: ${t.motivo}` : '');
            return `<div class="bloque bloque--${clase} ${t.cambiado ? 'bloque--cambio' : ''}" style="left: ${izquierda}%; width: ${ancho}%" data-tooltip="${escaparHtml(titulo)}">
                        ${actividad}<span class="bloque__texto">${escaparHtml(t.lote_codigo)} · ${escaparHtml(t.paso)}</span>
                    </div>`;
        }).join('');
        const noDisponible = e.estado !== 'DISPONIBLE';
        const calificacion = e.dias_calificacion === null ? '' : e.dias_calificacion < 0
            ? '<span class="aviso aviso--rojo">⛔ Calificación vencida</span>'
            : e.dias_calificacion <= DIAS_AVISO_CALIFICACION ? `<span class="aviso">⚠️ Calificación en ${e.dias_calificacion} d</span>` : '';
        return `
            <div class="fila ${noDisponible ? 'fila--no-disponible' : ''}">
                <div class="fila__equipo">
                    <div><span class="codigo">${escaparHtml(e.id)}</span> ${escaparHtml(e.nombre)}</div>
                    <div class="fila__meta">${escaparHtml(e.tipo_nombre)}${e.area ? ` · ${escaparHtml(e.area)}` : ''}
                        ${noDisponible ? `<span class="aviso aviso--rojo">${escaparHtml(e.estado_display)}</span>` : ''} ${calificacion}</div>
                </div>
                <div class="fila__pista">${bloques}</div>
            </div>`;
    }).join('');

    document.getElementById('cronograma').innerHTML = `
        <div class="cronograma__encabezado"><div class="fila__equipo"></div><div class="fila__pista fila__pista--marcas">${marcas}</div></div>
        <div class="cronograma__cuerpo">${filas}<div class="capa-ahora">${lineaAhora}</div></div>`;
}

function renderizarIndicadores(lista, inicio, fin) {
    const ids = new Set(lista.map(e => e.id));
    const tramos = ocupacion.tramos.filter(t => ids.has(t.equipo));
    // Horas ocupadas dentro del periodo, sobre las horas disponibles de los equipos visibles
    const horasOcupadas = tramos.reduce((suma, t) => {
        const a = Math.max(new Date(t.inicio).getTime(), inicio);
        const b = Math.min(new Date(t.fin).getTime(), fin);
        return suma + Math.max(0, b - a) / 3600000;
    }, 0);
    const horasPeriodo = lista.length * (fin - inicio) / 3600000;
    const uso = horasPeriodo ? Math.round((horasOcupadas / horasPeriodo) * 100) : 0;
    const noDisponibles = lista.filter(e => e.estado !== 'DISPONIBLE').length;
    const calificaciones = lista.filter(e => e.dias_calificacion !== null && e.dias_calificacion <= DIAS_AVISO_CALIFICACION).length;
    const pendientes = ocupacion.pendientes.reduce((suma, p) => suma + p.faltan, 0);
    const indicadores = [
        { valor: lista.length, etiqueta: 'Equipos' },
        { valor: `${uso}%`, etiqueta: 'Ocupación del periodo' },
        { valor: tramos.length, etiqueta: 'Reservas en el periodo' },
        { valor: pendientes, etiqueta: 'Equipos por reservar', clase: pendientes ? 'indicador--alerta' : '' },
        { valor: noDisponibles + calificaciones, etiqueta: 'No disponibles o calificación por vencer', clase: noDisponibles + calificaciones ? 'indicador--aviso' : '' },
    ];
    document.getElementById('indicadores').innerHTML = indicadores.map(i => `
        <div class="indicador ${i.clase || ''}">
            <span class="indicador-valor">${i.valor}</span>
            <span class="indicador-etiqueta">${i.etiqueta}</span>
        </div>`).join('');
}

function renderizarPendientes() {
    const tipo = document.getElementById('filtroTipo').value;
    const lista = ocupacion.pendientes.filter(p => !tipo || p.tipo === tipo)
        .sort((a, b) => new Date(a.inicio) - new Date(b.inicio));
    const contenedor = document.getElementById('pendientes');
    if (!lista.length) {
        contenedor.innerHTML = '<div class="estado-vacio">✔ Todas las fases del periodo tienen su equipo reservado.</div>';
        return;
    }
    contenedor.innerHTML = lista.map(p => `
        <div class="pendiente ${p.fase_estado === 'EN_PROGRESO' ? 'pendiente--urgente' : ''}">
            <div class="pendiente__principal"><strong>${p.faltan} × ${escaparHtml(p.tipo_nombre)}</strong>
                <span class="pendiente__estado">${p.fase_estado === 'EN_PROGRESO' ? 'En ejecución' : 'Por iniciar'}</span></div>
            <div>${escaparHtml(p.lote_codigo)} · [${escaparHtml(p.paso)}] ${escaparHtml(p.actividad)}</div>
            <div class="pendiente__meta">Ocupa ${momentoTexto(p.inicio)} – ${momentoTexto(p.fin)}</div>
        </div>`).join('') + `<a class="btn-secundario pendientes__enlace" href="/planificacion/">📅 Reservar en Planificación</a>`;
}

document.addEventListener('DOMContentLoaded', async () => {
    await cargarCatalogos();
    await cargarOcupacion();
});
