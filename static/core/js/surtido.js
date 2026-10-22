// static/core/js/surtido.js — Surtido de materiales en las pantallas web (entrega, recepción, rechazo y devolución).
//
//   tarjeta.innerHTML += htmlSurtido(requerimiento);           // estado del surtido, entregas y botones
//   configurarSurtido({ alActualizar: () => recargar() });     // qué hacer tras cada movimiento
//   htmlDevolucionesPendientes(lista);                          // devoluciones por recibir en el almacén
//
// Cada paso se firma con contraseña (firma.js). Entregar y recibir devoluciones exige `surtir_material`;
// recibir, rechazar y devolver sobrante de una entrega, `ejecutar_fase` (en la tablet lo hace el operador con PIN).
// Quien entrega no puede recibir (el servidor lo valida). Requiere utils.js, materiales.js, sesion.js, firma.js
// y static/core/css/surtido.css + firma.css.

let alActualizarSurtido = () => location.reload();
// Datos por id para que los botones no lleven JSON en el HTML
const SURTIDO_MATERIALES = new Map();
const SURTIDO_ENTREGAS = new Map();

function configurarSurtido({ alActualizar }) {
    if (alActualizar) alActualizarSurtido = alActualizar;
}

const ESTADOS_SURTIDO = {
    SIN_SURTIR: { texto: 'Sin surtir', clase: 'surtido--sin' },
    EN_TRANSITO: { texto: 'Por recibir', clase: 'surtido--transito' },
    PARCIAL: { texto: 'Parcial', clase: 'surtido--parcial' },
    COMPLETO: { texto: 'Surtido', clase: 'surtido--completo' },
};

function fechaSurtido(iso) {
    if (!iso) return '--';
    const [a, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    return new Date(a, m - 1, d).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
}

function momentoSurtido(iso) {
    return iso ? new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '--';
}

// Chip corto: "Parcial · 1 de 2 L"
function chipSurtido(mf) {
    const s = mf.surtido;
    if (!s) return '';
    const info = ESTADOS_SURTIDO[s.estado] || ESTADOS_SURTIDO.SIN_SURTIR;
    let detalle = '';
    if (s.estado === 'PARCIAL') detalle = ` · ${formatearCantidad(s.recibido)} de ${formatearCantidad(s.requerido, mf.unidad_medida)}`;
    if (s.estado === 'EN_TRANSITO') detalle = ` · ${formatearCantidad(s.en_transito, mf.unidad_medida)}`;
    if (s.estado === 'COMPLETO' && Number(s.excedente) > 0) detalle = ` · sobran ${formatearCantidad(s.excedente, mf.unidad_medida)}`;
    return `<span class="surtido-chip ${info.clase}">📦 ${info.texto}${detalle}</span>`;
}

function htmlEntrega(e, abierta) {
    SURTIDO_ENTREGAS.set(e.id, e);
    const esDevolucion = e.tipo === 'DEVOLUCION';
    const quien = e.estado === 'EN_TRANSITO'
        ? `${esDevolucion ? 'devolvió' : 'entregó'} ${escaparHtml(e.entregado_por_nombre)} · ${momentoSurtido(e.entregado_en)}`
        : `${escaparHtml(e.entregado_por_nombre)} → ${escaparHtml(e.recibido_por_nombre)} · ${momentoSurtido(e.recibido_en)}`;
    const botones = [];
    if (e.estado === 'EN_TRANSITO') {
        const permiso = esDevolucion ? 'surtir_material' : 'ejecutar_fase';
        botones.push(`<button type="button" class="btn-surtido btn-surtido--ok" data-permiso="${permiso}" onclick="recibirEntregaMaterial(${e.id})">✔ Recibir</button>`);
        botones.push(`<button type="button" class="btn-surtido btn-surtido--no" data-permiso="${permiso}" onclick="abrirRechazoMaterial(${e.id})">✕ Rechazar</button>`);
    } else if (!esDevolucion && e.estado === 'RECIBIDA' && Number(e.disponible_devolver) > 0 && abierta) {
        botones.push(`<button type="button" class="btn-surtido" data-permiso="ejecutar_fase" onclick="abrirDevolucionMaterial(${e.id})">↩ Devolver sobrante</button>`);
    }
    const rechazo = e.estado === 'RECHAZADA' && e.motivo_rechazo ? ` · <em>${escaparHtml(e.motivo_rechazo)}</em>` : '';
    return `
        <div class="surtido-entrega surtido-entrega--${e.estado.toLowerCase()}">
            <span class="surtido-entrega__tipo">${esDevolucion ? '↩' : '📦'} ${formatearCantidad(e.cantidad, e.unidad_medida)}</span>
            <span class="surtido-entrega__lote">Lote <strong>${escaparHtml(e.lote_material)}</strong> · cad. ${fechaSurtido(e.caducidad)}</span>
            <span class="surtido-entrega__estado">${escaparHtml(e.estado_display)}</span>
            <span class="surtido-entrega__quien">${quien}${rechazo}</span>
            ${botones.length ? `<span class="surtido-entrega__botones">${botones.join('')}</span>` : ''}
        </div>`;
}

// Bloque para la tarjeta de un requerimiento (MaterialFase con `surtido` y `entregas`)
function htmlSurtido(mf) {
    SURTIDO_MATERIALES.set(mf.id, mf);
    const abierta = ['PENDIENTE', 'EN_PROGRESO'].includes(mf.fase_estado || 'PENDIENTE');
    const puedeEntregar = mf.activo !== false && abierta && mf.surtido && mf.surtido.estado !== 'COMPLETO';
    const entregas = (mf.entregas || []).map(e => htmlEntrega(e, true)).join('');
    return `
        <div class="surtido">
            <div class="surtido__cabecera">
                ${chipSurtido(mf)}
                ${puedeEntregar ? `<button type="button" class="btn-surtido btn-surtido--entregar" data-permiso="surtir_material" onclick="abrirEntregaMaterial(${mf.id})">📦 Entregar</button>` : ''}
            </div>
            ${entregas ? `<div class="surtido__entregas">${entregas}</div>` : ''}
        </div>`;
}

function htmlDevolucionesPendientes(lista) {
    if (!lista.length) return '<div class="estado-vacio">Sin devoluciones por recibir.</div>';
    return lista.map(d => `
        <div class="surtido-devolucion">
            <div class="surtido-devolucion__material">${escaparHtml(d.material_nombre)} <span>· lote ${escaparHtml(d.lote_codigo)}</span></div>
            ${htmlEntrega(d, false)}
        </div>`).join('');
}

// --- Formularios -------------------------------------------------------------------

// Modal con campos; resuelve con los valores o null si se cancela. Usa los estilos de firma.css.
function formularioSurtido({ titulo, detalle, campos, boton }) {
    return new Promise(resolver => {
        const fondo = document.createElement('div');
        fondo.className = 'firma-fondo';
        fondo.innerHTML = `
            <form class="firma-modal" role="dialog" aria-modal="true" autocomplete="off">
                <h3>${escaparHtml(titulo)}</h3>
                ${detalle ? `<div class="firma-accion"><span>${detalle}</span></div>` : ''}
                ${campos}
                <div class="firma-error" role="alert" hidden></div>
                <div class="firma-botones">
                    <button type="button" class="firma-cancelar">Cancelar</button>
                    <button type="submit" class="firma-firmar">${escaparHtml(boton)}</button>
                </div>
            </form>`;
        document.body.appendChild(fondo);
        const formulario = fondo.querySelector('form');
        const cerrar = (valor) => { fondo.remove(); resolver(valor); };
        fondo.querySelector('.firma-cancelar').addEventListener('click', () => cerrar(null));
        fondo.addEventListener('keydown', e => { if (e.key === 'Escape') cerrar(null); });
        formulario.addEventListener('submit', e => {
            e.preventDefault();
            cerrar(Object.fromEntries(new FormData(formulario).entries()));
        });
        const primero = formulario.querySelector('input, textarea');
        if (primero) primero.focus();
    });
}

function campoSurtido(etiqueta, html) {
    return `<label class="firma-campo"><span>${etiqueta}</span>${html}</label>`;
}

function textoRequerimiento(mf) {
    return `${escaparHtml(mf.material_nombre)} · Lote ${escaparHtml(mf.lote_codigo || '')} · [${escaparHtml(mf.paso || '')}] ${escaparHtml(mf.actividad || '')}`;
}

async function procesarRespuestaSurtido(r, exito) {
    if (!r) return;
    if (r.ok) {
        if (r.data.avisos && r.data.avisos.length) alert('⚠️ ' + r.data.avisos.join('\n'));
        else if (exito) mostrarAvisoSurtido(exito);
        await alActualizarSurtido();
    } else {
        alert('⚠️ ' + (r.data.error || r.data.detail || 'No se pudo registrar el movimiento.'));
    }
}

function mostrarAvisoSurtido(texto) {
    const aviso = document.createElement('div');
    aviso.className = 'surtido-toast';
    aviso.textContent = texto;
    document.body.appendChild(aviso);
    setTimeout(() => aviso.remove(), 3000);
}

async function abrirEntregaMaterial(mfId) {
    const mf = SURTIDO_MATERIALES.get(mfId);
    if (!mf) return;
    const faltante = Number(mf.surtido.faltante) || Number(mf.cantidad);
    const hoy = new Date();
    const minimo = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-${String(hoy.getDate()).padStart(2, '0')}`;
    const datos = await formularioSurtido({
        titulo: '📦 Entregar material',
        detalle: `${textoRequerimiento(mf)}<br>Requerido: <strong>${formatearCantidad(mf.cantidad, mf.unidad_medida)}</strong>` +
                 (Number(mf.surtido.recibido) ? ` · recibido ${formatearCantidad(mf.surtido.recibido, mf.unidad_medida)}` : '') +
                 (Number(mf.surtido.en_transito) ? ` · por recibir ${formatearCantidad(mf.surtido.en_transito, mf.unidad_medida)}` : ''),
        campos: [
            campoSurtido(`Cantidad que entregas (${escaparHtml(mf.unidad_medida)})`, `<input type="number" name="cantidad" step="any" min="0.001" required value="${faltante}">`),
            campoSurtido('Lote del material', '<input type="text" name="lote_material" maxlength="80" required placeholder="Ej: MC-2026-118">'),
            campoSurtido('Caducidad', `<input type="date" name="caducidad" required min="${minimo}">`),
            campoSurtido('Observaciones (opcional)', '<textarea name="observaciones" rows="2" maxlength="500"></textarea>'),
        ].join(''),
        boton: 'Continuar a firma',
    });
    if (!datos) return;
    const r = await ejecutarConFirma({
        accion: 'ENTREGAR_MATERIAL', titulo: '📦 Entregar material',
        detalle: `${formatearCantidad(datos.cantidad, mf.unidad_medida)} de ${mf.material_nombre} · lote ${datos.lote_material}`,
        url: '/api/surtido/entregar/', cuerpo: { material_fase: mf.id, ...datos },
    });
    await procesarRespuestaSurtido(r, 'Entrega registrada: queda por recibir en la fase.');
}

async function recibirEntregaMaterial(entregaId) {
    const e = SURTIDO_ENTREGAS.get(entregaId);
    if (!e) return;
    const r = await ejecutarConFirma({
        accion: 'RECIBIR_MATERIAL', titulo: e.tipo === 'DEVOLUCION' ? '↩ Recibir devolución' : '✔ Recibir material',
        detalle: `${formatearCantidad(e.cantidad, e.unidad_medida)} de ${e.material_nombre} · lote ${e.lote_material} · cad. ${fechaSurtido(e.caducidad)} · de ${e.entregado_por_nombre}`,
        url: `/api/surtido/${e.id}/recibir/`,
    });
    await procesarRespuestaSurtido(r, 'Recepción registrada.');
}

async function abrirRechazoMaterial(entregaId) {
    const e = SURTIDO_ENTREGAS.get(entregaId);
    if (!e) return;
    const datos = await formularioSurtido({
        titulo: '✕ Rechazar material',
        detalle: `${formatearCantidad(e.cantidad, e.unidad_medida)} de ${escaparHtml(e.material_nombre)} · lote ${escaparHtml(e.lote_material)}`,
        campos: campoSurtido('Motivo del rechazo (mínimo 10 caracteres)', '<textarea name="motivo" rows="3" maxlength="500" minlength="10" required placeholder="Cantidad incorrecta, empaque dañado, lote equivocado…"></textarea>'),
        boton: 'Continuar a firma',
    });
    if (!datos) return;
    const r = await ejecutarConFirma({
        accion: 'RECHAZAR_MATERIAL', titulo: '✕ Rechazar material', detalle: datos.motivo,
        url: `/api/surtido/${e.id}/rechazar/`, cuerpo: { motivo: datos.motivo },
    });
    await procesarRespuestaSurtido(r, 'Rechazo registrado.');
}

async function abrirDevolucionMaterial(entregaId) {
    const e = SURTIDO_ENTREGAS.get(entregaId);
    if (!e) return;
    const datos = await formularioSurtido({
        titulo: '↩ Devolver sobrante',
        detalle: `${escaparHtml(e.material_nombre)} · lote ${escaparHtml(e.lote_material)} · puedes devolver hasta <strong>${formatearCantidad(e.disponible_devolver, e.unidad_medida)}</strong>`,
        campos: [
            campoSurtido(`Cantidad que devuelves (${escaparHtml(e.unidad_medida)})`, `<input type="number" name="cantidad" step="any" min="0.001" max="${Number(e.disponible_devolver)}" required>`),
            campoSurtido('Observaciones (opcional)', '<textarea name="observaciones" rows="2" maxlength="500"></textarea>'),
        ].join(''),
        boton: 'Continuar a firma',
    });
    if (!datos) return;
    const r = await ejecutarConFirma({
        accion: 'DEVOLVER_MATERIAL', titulo: '↩ Devolver sobrante',
        detalle: `${formatearCantidad(datos.cantidad, e.unidad_medida)} de ${e.material_nombre} · lote ${e.lote_material}`,
        url: `/api/surtido/${e.id}/devolver/`, cuerpo: datos,
    });
    await procesarRespuestaSurtido(r, 'Devolución registrada: queda por recibir en el almacén.');
}
