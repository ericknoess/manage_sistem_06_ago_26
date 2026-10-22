// procesos/static/procesos/js/mobile_surtido.js — Surtido de materiales en la terminal (firma con PIN).
//
// Personal de la fase: en cada tarea ve sus materiales, recibe o rechaza lo que le entregaron y devuelve
// el sobrante. Pestaña "Recibir": todas las entregas pendientes, para cualquier operador en turno (o supervisor
// con su registro ligado); quien recibe no tiene que ser quien ejecuta la actividad.
// Quien tiene `surtir_material` (almacén o planeación con su registro del roster ligado)
// ve además la pestaña "Surtir": entrega lo pendiente de las próximas horas y recibe devoluciones.
// Quien entrega no puede recibir (el servidor lo valida). Usa `session` de mobile_dashboard.js.

const SURTIDO_TERMINAL = { entregas: new Map(), requerimientos: new Map() };

// Por si la sesión guardada en la tablet es anterior a estas firmas (el servidor manda las vigentes al ingresar)
const SIGNIFICADOS_SURTIDO = {
    ENTREGAR_MATERIAL: 'Entrego el material indicado',
    RECIBIR_MATERIAL: 'Recibo el material conforme',
    RECHAZAR_MATERIAL: 'Rechazo el material entregado',
    DEVOLVER_MATERIAL: 'Devuelvo el material sobrante',
};

const ESTADO_SURTIDO_TERMINAL = {
    SIN_SURTIR: { texto: 'Sin surtir', clase: 'mat-chip--sin' },
    EN_TRANSITO: { texto: 'Por recibir', clase: 'mat-chip--transito' },
    PARCIAL: { texto: 'Parcial', clase: 'mat-chip--parcial' },
    COMPLETO: { texto: 'Surtido', clase: 'mat-chip--completo' },
};

function puedeSurtir() {
    return !!(session && (session.permisos || []).includes('surtir_material'));
}

function cantidadTerminal(cantidad, unidad = '') {
    const n = Number(cantidad);
    const texto = Number.isFinite(n) ? n.toLocaleString('es-MX', { maximumFractionDigits: 3 }) : cantidad;
    return unidad ? `${texto} ${unidad}` : texto;
}

function fechaTerminal(iso) {
    if (!iso) return '--';
    const [a, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    return new Date(a, m - 1, d).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
}

function hoyIso() {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}-${String(h.getDate()).padStart(2, '0')}`;
}

function chipSurtidoTerminal(surtido, unidad) {
    const info = ESTADO_SURTIDO_TERMINAL[surtido.estado] || ESTADO_SURTIDO_TERMINAL.SIN_SURTIR;
    let detalle = '';
    if (surtido.estado === 'PARCIAL') detalle = ` · ${cantidadTerminal(surtido.recibido)} de ${cantidadTerminal(surtido.requerido, unidad)}`;
    return `<span class="mat-chip ${info.clase}">${info.texto}${detalle}</span>`;
}

// --- Materiales dentro de la tarjeta de cada tarea -----------------------------------

function htmlEntregaTerminal(e, material, { recibir = false, devolver = false } = {}) {
    SURTIDO_TERMINAL.entregas.set(e.id, { ...e, material_nombre: e.material_nombre || material });
    const esDevolucion = e.tipo === 'DEVOLUCION';
    const botones = [];
    if (recibir && e.estado === 'EN_TRANSITO') {
        botones.push(`<button class="btn-mat btn-mat--ok" onclick="recibirMaterialTerminal(${e.id})">✔ Recibir</button>`);
        botones.push(`<button class="btn-mat btn-mat--no" onclick="rechazarMaterialTerminal(${e.id})">✕ Rechazar</button>`);
    }
    if (devolver && !esDevolucion && e.estado === 'RECIBIDA' && Number(e.disponible_devolver) > 0) {
        botones.push(`<button class="btn-mat" onclick="devolverMaterialTerminal(${e.id})">↩ Devolver sobrante</button>`);
    }
    const quien = e.estado === 'EN_TRANSITO'
        ? `${esDevolucion ? 'Devuelve' : 'Entrega'}: ${escaparTexto(e.entregado_por_nombre)}`
        : `${escaparTexto(e.estado_display)} por ${escaparTexto(e.recibido_por_nombre)}`;
    return `
        <div class="mat-entrega mat-entrega--${e.estado.toLowerCase()}">
            <div class="mat-entrega__linea">
                <strong>${esDevolucion ? '↩' : '📦'} ${cantidadTerminal(e.cantidad, e.unidad_medida)}</strong>
                <span>Lote ${escaparTexto(e.lote_material)} · cad. ${fechaTerminal(e.caducidad)}</span>
            </div>
            <div class="mat-entrega__quien">${quien}${e.motivo_rechazo ? ` · ${escaparTexto(e.motivo_rechazo)}` : ''}</div>
            ${botones.length ? `<div class="mat-entrega__botones">${botones.join('')}</div>` : ''}
        </div>`;
}

function htmlMaterialesTarea(t) {
    const materiales = t.materiales || [];
    if (!materiales.length) return '';
    const filas = materiales.map(m => {
        // Las entregas se muestran todas (las rechazadas, con su motivo); las devoluciones rechazadas no
        const entregas = m.entregas.filter(e => e.estado !== 'RECHAZADA' || e.tipo === 'ENTREGA')
            .map(e => htmlEntregaTerminal(e, m.material_nombre, { recibir: e.tipo === 'ENTREGA', devolver: true })).join('');
        return `
            <div class="mat-item">
                <div class="mat-item__cabecera">
                    <span class="mat-item__nombre">${escaparTexto(m.material_nombre)}</span>
                    <span class="mat-item__cantidad">${cantidadTerminal(m.cantidad, m.unidad_medida)}</span>
                    ${chipSurtidoTerminal(m.surtido, m.unidad_medida)}
                </div>
                ${entregas}
            </div>`;
    }).join('');
    return `<div class="mat-bloque"><div class="mat-bloque__titulo">📦 Materiales</div>${filas}</div>`;
}

function htmlSobrantes(sobrantes) {
    if (!sobrantes || !sobrantes.length) return '';
    return `
        <div class="task-card mat-sobrantes">
            <h4 class="task-title">↩ Sobrantes por devolver</h4>
            <div class="task-lote">De tareas que ya terminaste. Devuélvelos al almacén con tu firma.</div>
            ${sobrantes.map(e => `
                <div class="mat-item">
                    <div class="mat-item__cabecera"><span class="mat-item__nombre">${escaparTexto(e.material_nombre)}</span>
                        <span class="mat-item__cantidad">Lote ${escaparTexto(e.lote_codigo)}</span></div>
                    <div class="mat-entrega__quien">${escaparTexto(e.actividad)}</div>
                    ${htmlEntregaTerminal(e, e.material_nombre, { devolver: true })}
                </div>`).join('')}
        </div>`;
}

// --- Pestaña "Surtir" (almacén / planeación) -----------------------------------------

const PESTANAS_TERMINAL = { tareas: 'taskListContainer', recibir: 'recibirContainer', surtir: 'surtirContainer' };
let pestanaActual = 'tareas';

function prepararPestanasSurtido() {
    const surtir = document.querySelector('#pestanasTerminal [data-pestana="surtir"]');
    surtir.hidden = !puedeSurtir();
    document.getElementById('pestanasTerminal').classList.toggle('pestanas-terminal--tres', puedeSurtir());
    mostrarPestana('tareas');
}

function mostrarPestana(cual) {
    pestanaActual = cual;
    document.querySelectorAll('#pestanasTerminal button').forEach(b => b.classList.toggle('is-activa', b.dataset.pestana === cual));
    Object.entries(PESTANAS_TERMINAL).forEach(([clave, id]) => { document.getElementById(id).hidden = clave !== cual; });
    if (cual === 'surtir') cargarPorSurtir();
    if (cual === 'recibir') cargarPorRecibir();
}

// --- Pestaña "Recibir" (cualquier operador en turno, supervisión) ---------------------

async function cargarPorRecibir() {
    const caja = document.getElementById('recibirContainer');
    caja.innerHTML = '<div class="empty-state"><p>Cargando entregas por recibir…</p></div>';
    try {
        const res = await fetch('/api/surtido/por-recibir/');
        if (!res.ok) throw new Error();
        const datos = await res.json();
        renderizarPorRecibir(datos.entregas, datos.puede_recibir);
    } catch (e) {
        caja.innerHTML = '<div class="empty-state"><p>⚠️ No se pudieron cargar las entregas por recibir.</p></div>';
    }
}

function renderizarPorRecibir(entregas, puedeRecibir) {
    const caja = document.getElementById('recibirContainer');
    let html = puedeRecibir ? '' : `<div class="task-aviso task-aviso--espera">🕒 No tienes turno en este momento: solo ves lo que llega a tus tareas asignadas.
        Cualquier operador en turno, un supervisor o jefatura puede recibir las demás.</div>`;
    if (!entregas.length) {
        html += `<div class="empty-state"><div style="font-size: 3rem; margin-bottom: 1rem;">📥</div><h3>Nada por recibir</h3>
            <p>No hay material entregado esperando recepción.</p></div>`;
    }
    entregas.forEach(e => {
        html += `
            <div class="task-card">
                <div class="task-header">
                    <div style="flex: 1; padding-right: 1rem;">
                        <h4 class="task-title">${escaparTexto(e.material_nombre)} · ${cantidadTerminal(e.cantidad, e.unidad_medida)}</h4>
                        <div class="task-lote">${escaparTexto(e.actividad)}</div>
                    </div>
                </div>
                <div class="task-details">
                    <div class="detail-item"><strong>⏰ Requerido</strong><span>${formatearMomento(e.momento_requerido)}</span></div>
                    <div class="detail-item"><strong>▶ Inicio de la actividad</strong><span>${formatearMomento(e.inicio_actividad)}</span></div>
                </div>
                ${htmlEntregaTerminal(e, e.material_nombre, { recibir: true })}
            </div>`;
    });
    caja.innerHTML = html;
}

async function cargarPorSurtir() {
    const caja = document.getElementById('surtirContainer');
    caja.innerHTML = '<div class="empty-state"><p>Cargando materiales por surtir…</p></div>';
    try {
        const res = await fetch('/api/surtido/por-surtir/?horas=48');
        if (!res.ok) throw new Error();
        const datos = await res.json();
        renderizarPorSurtir(datos.requerimientos, datos.devoluciones);
    } catch (e) {
        caja.innerHTML = '<div class="empty-state"><p>⚠️ No se pudo cargar lo pendiente de surtir.</p></div>';
    }
}

function renderizarPorSurtir(requerimientos, devoluciones) {
    const caja = document.getElementById('surtirContainer');
    const ahora = new Date();
    let html = '';
    if (devoluciones.length) {
        html += `<div class="task-card mat-sobrantes"><h4 class="task-title">↩ Devoluciones por recibir</h4>
            ${devoluciones.map(d => `<div class="mat-item"><div class="mat-item__cabecera"><span class="mat-item__nombre">${escaparTexto(d.material_nombre)}</span>
                <span class="mat-item__cantidad">Lote ${escaparTexto(d.lote_codigo)}</span></div>
                ${htmlEntregaTerminal(d, d.material_nombre, { recibir: true })}</div>`).join('')}</div>`;
    }
    if (!requerimientos.length) {
        html += `<div class="empty-state"><div style="font-size: 3rem; margin-bottom: 1rem;">✅</div><h3>Todo surtido</h3>
            <p>No hay materiales pendientes de entregar en las próximas 48 horas.</p></div>`;
    }
    requerimientos.forEach(r => {
        SURTIDO_TERMINAL.requerimientos.set(r.id, r);
        const momento = new Date(r.momento_requerido);
        const atrasado = momento < ahora;
        const enTransito = r.entregas.filter(e => e.estado === 'EN_TRANSITO' && e.tipo === 'ENTREGA')
            .map(e => htmlEntregaTerminal(e, r.material_nombre)).join('');
        html += `
            <div class="task-card ${atrasado ? 'mat-card--atrasada' : ''}">
                <div class="task-header">
                    <div style="flex: 1; padding-right: 1rem;">
                        <h4 class="task-title">${escaparTexto(r.material_nombre)} · ${cantidadTerminal(r.cantidad, r.unidad_medida)}</h4>
                        <div class="task-lote">Lote ${escaparTexto(r.lote_codigo)} · [${escaparTexto(r.paso)}] ${escaparTexto(r.actividad)}</div>
                    </div>
                    ${chipSurtidoTerminal(r.surtido, r.unidad_medida)}
                </div>
                <div class="task-details">
                    <div class="detail-item"><strong>⏰ Requerido</strong><span>${formatearMomento(r.momento_requerido)}${atrasado ? ' · atrasado' : ''}</span></div>
                    <div class="detail-item"><strong>📦 Falta entregar</strong><span>${cantidadTerminal(r.surtido.faltante, r.unidad_medida)}</span></div>
                </div>
                ${enTransito}
                ${Number(r.surtido.faltante) > 0 ? `<button class="btn-massive btn-primary" onclick="entregarMaterialTerminal(${r.id})">📦 ENTREGAR</button>` : ''}
            </div>`;
    });
    caja.innerHTML = html;
}

// --- Firma con PIN (modal con campos del movimiento) ---------------------------------

function firmarSurtidoPin({ titulo, detalle, accion, campos = '', url, cuerpo = () => ({}) }) {
    const significado = ((session && session.firmas) || {})[accion] || SIGNIFICADOS_SURTIDO[accion] || titulo;
    return new Promise(resolver => {
        const fondo = document.createElement('div');
        fondo.className = 'firma-pin-fondo';
        fondo.innerHTML = `
            <form class="firma-pin" autocomplete="off">
                <div class="firma-pin__titulo">${escaparTexto(titulo)}</div>
                <div class="firma-pin__tarea">${detalle}</div>
                ${campos}
                <div class="firma-pin__significado"><span>Significado de tu firma</span><strong>«${escaparTexto(significado)}»</strong></div>
                <div class="firma-pin__firmante">Firmas como <strong>${escaparTexto(session ? `${session.nombre} (${session.codigo_empleado})` : '')}</strong></div>
                <label class="input-group">
                    <span>Confirma con tu PIN</span>
                    <input type="password" name="firma_pin" class="input-gxp" required pattern="[0-9]*" inputmode="numeric" placeholder="••••">
                </label>
                <div class="firma-pin__error" hidden></div>
                <p class="firma-pin__legal">Tu firma electrónica equivale a tu firma autógrafa y queda registrada con tu nombre, fecha y hora.</p>
                <div class="firma-pin__botones">
                    <button type="button" class="btn-massive btn-secundario-pin">Cancelar</button>
                    <button type="submit" class="btn-massive btn-primary">Firmar</button>
                </div>
            </form>`;
        document.body.appendChild(fondo);
        const formulario = fondo.querySelector('form');
        const error = fondo.querySelector('.firma-pin__error');
        const boton = formulario.querySelector('button[type="submit"]');
        const cerrar = (valor) => { fondo.remove(); resolver(valor); };
        fondo.querySelector('.btn-secundario-pin').addEventListener('click', () => cerrar(null));
        (formulario.querySelector('.mat-campo input, .mat-campo textarea') || formulario.elements.firma_pin).focus();

        formulario.addEventListener('submit', async (evento) => {
            evento.preventDefault();
            boton.disabled = true;
            error.hidden = true;
            const valores = Object.fromEntries(new FormData(formulario).entries());
            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                    body: JSON.stringify({ ...valores, ...cuerpo(valores) }),
                });
                let datos = {};
                try { datos = await res.json(); } catch (e) { /* sin cuerpo */ }
                if (res.ok) return cerrar(datos);
                if (datos.codigo === 'TERMINAL_CERRADA') { cerrar(null); terminalCerrada(datos.error); return; }
                if (datos.codigo === 'CUENTA_BLOQUEADA') { cerrar(null); alert('🔒 ' + datos.error); handleLogout(); return; }
                if (res.status === 401 || (res.status === 403 && !datos.error)) {
                    cerrar(null); alert('🔒 ' + (datos.detail || 'Tu sesión expiró. Vuelve a ingresar.')); handleLogout(); return;
                }
                error.textContent = datos.error || datos.detail || 'No se pudo registrar.';
                error.hidden = false;
                formulario.elements.firma_pin.value = '';
            } catch (e) {
                error.textContent = 'Error de red. Verifique la conexión WiFi de la Tablet.';
                error.hidden = false;
            } finally {
                boton.disabled = false;
            }
        });
    });
}

function campoTerminal(etiqueta, html) {
    return `<label class="input-group mat-campo"><span>${etiqueta}</span>${html}</label>`;
}

async function trasMovimiento(datos, mensaje) {
    if (!datos) return;
    alert((datos.avisos && datos.avisos.length ? '⚠️ ' + datos.avisos.join('\n') + '\n\n' : '') + mensaje);
    if (pestanaActual === 'surtir') cargarPorSurtir();
    else if (pestanaActual === 'recibir') cargarPorRecibir();
    else cargarTareasPendientes();
}

async function entregarMaterialTerminal(id) {
    const r = SURTIDO_TERMINAL.requerimientos.get(id);
    if (!r) return;
    const datos = await firmarSurtidoPin({
        titulo: '📦 Entregar material', accion: 'ENTREGAR_MATERIAL',
        detalle: `${escaparTexto(r.material_nombre)} · Lote ${escaparTexto(r.lote_codigo)} · [${escaparTexto(r.paso)}] ${escaparTexto(r.actividad)}`,
        campos: [
            campoTerminal(`Cantidad (${escaparTexto(r.unidad_medida)})`, `<input type="number" name="cantidad" class="input-gxp" step="any" min="0.001" required value="${Number(r.surtido.faltante)}">`),
            campoTerminal('Lote del material', '<input type="text" name="lote_material" class="input-gxp" maxlength="80" required placeholder="Ej: MC-2026-118">'),
            campoTerminal('Caducidad', `<input type="date" name="caducidad" class="input-gxp" required min="${hoyIso()}">`),
        ].join(''),
        url: '/api/surtido/entregar/', cuerpo: () => ({ material_fase: r.id }),
    });
    await trasMovimiento(datos, '✅ Entrega registrada. Queda por recibir en la fase.');
}

async function recibirMaterialTerminal(id) {
    const e = SURTIDO_TERMINAL.entregas.get(id);
    if (!e) return;
    const datos = await firmarSurtidoPin({
        titulo: e.tipo === 'DEVOLUCION' ? '↩ Recibir devolución' : '✔ Recibir material', accion: 'RECIBIR_MATERIAL',
        detalle: `${cantidadTerminal(e.cantidad, e.unidad_medida)} de ${escaparTexto(e.material_nombre)} · lote ${escaparTexto(e.lote_material)} · cad. ${fechaTerminal(e.caducidad)}<br>
                  ${e.tipo === 'DEVOLUCION' ? 'Devuelve' : 'Entrega'}: ${escaparTexto(e.entregado_por_nombre)}`,
        url: `/api/surtido/${e.id}/recibir/`,
    });
    await trasMovimiento(datos, '✅ Recepción registrada.');
}

async function rechazarMaterialTerminal(id) {
    const e = SURTIDO_TERMINAL.entregas.get(id);
    if (!e) return;
    const datos = await firmarSurtidoPin({
        titulo: '✕ Rechazar material', accion: 'RECHAZAR_MATERIAL',
        detalle: `${cantidadTerminal(e.cantidad, e.unidad_medida)} de ${escaparTexto(e.material_nombre)} · lote ${escaparTexto(e.lote_material)}`,
        campos: campoTerminal('Motivo del rechazo', '<textarea name="motivo" class="input-gxp mat-texto" rows="2" minlength="10" maxlength="500" required placeholder="Cantidad incorrecta, empaque dañado, caducado…"></textarea>'),
        url: `/api/surtido/${e.id}/rechazar/`,
    });
    await trasMovimiento(datos, 'Rechazo registrado.');
}

async function devolverMaterialTerminal(id) {
    const e = SURTIDO_TERMINAL.entregas.get(id);
    if (!e) return;
    const datos = await firmarSurtidoPin({
        titulo: '↩ Devolver sobrante', accion: 'DEVOLVER_MATERIAL',
        detalle: `${escaparTexto(e.material_nombre)} · lote ${escaparTexto(e.lote_material)}<br>Puedes devolver hasta <strong>${cantidadTerminal(e.disponible_devolver, e.unidad_medida)}</strong>`,
        campos: campoTerminal(`Cantidad (${escaparTexto(e.unidad_medida)})`, `<input type="number" name="cantidad" class="input-gxp" step="any" min="0.001" max="${Number(e.disponible_devolver)}" required>`),
        url: `/api/surtido/${e.id}/devolver/`,
    });
    await trasMovimiento(datos, '✅ Devolución registrada. Queda por recibir en el almacén.');
}
