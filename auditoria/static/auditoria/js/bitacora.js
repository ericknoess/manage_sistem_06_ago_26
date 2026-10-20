// auditoria/static/auditoria/js/bitacora.js — Consulta de la bitácora de auditoría con filtros y exportación.

const LIMITE = 500;
let registros = [];

function hoyIso(desplazamientoDias = 0) {
    const d = new Date();
    d.setDate(d.getDate() + desplazamientoDias);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function iniciar() {
    document.getElementById('filtroDesde').value = hoyIso(-7);
    document.getElementById('filtroHasta').value = hoyIso();
    document.getElementById('filtroTexto').addEventListener('keydown', e => { if (e.key === 'Enter') buscar(); });
    ['filtroDesde', 'filtroHasta', 'filtroCategoria'].forEach(id => document.getElementById(id).addEventListener('change', buscar));

    try {
        const opciones = await (await fetch('/api/auditoria/opciones/')).json();
        const select = document.getElementById('filtroCategoria');
        opciones.categorias.forEach(c => select.insertAdjacentHTML('beforeend', `<option value="${c.valor}">${escaparAuditoria(c.texto)}</option>`));
    } catch (e) { /* el filtro de categoría es opcional */ }
    buscar();
}

function filtros() {
    const f = { limite: LIMITE };
    const valor = id => document.getElementById(id).value.trim();
    if (valor('filtroDesde')) f.desde = valor('filtroDesde');
    if (valor('filtroHasta')) f.hasta = valor('filtroHasta');
    if (valor('filtroCategoria')) f.categoria = valor('filtroCategoria');
    if (valor('filtroTexto')) f.q = valor('filtroTexto');
    return f;
}

async function buscar() {
    const cuerpo = document.getElementById('cuerpoBitacora');
    cuerpo.innerHTML = '<tr><td colspan="7" class="estado-vacio">Cargando…</td></tr>';
    try {
        const datos = await cargarHistorialAuditoria(filtros());
        registros = datos.resultados;
        document.getElementById('conteo').textContent = datos.total > datos.limite
            ? `Mostrando ${datos.limite} de ${datos.total} registros (acota las fechas para ver el resto)`
            : `${datos.total} registro${datos.total === 1 ? '' : 's'}`;
        renderizar();
    } catch (e) {
        cuerpo.innerHTML = `<tr><td colspan="7" class="estado-vacio">${escaparAuditoria(e.message)}</td></tr>`;
    }
}

function renderizar() {
    const cuerpo = document.getElementById('cuerpoBitacora');
    if (!registros.length) {
        cuerpo.innerHTML = '<tr><td colspan="7" class="estado-vacio">No hay registros con esos filtros.</td></tr>';
        return;
    }
    cuerpo.innerHTML = registros.map(r => `
        <tr>
            <td class="col-fecha">${fechaAuditoria(r.fecha)}</td>
            <td><strong>${escaparAuditoria(r.actor)}</strong>${r.roles ? `<div class="sub">${escaparAuditoria(r.roles)}</div>` : ''}${r.ip ? `<div class="sub">IP ${escaparAuditoria(r.ip)}</div>` : ''}</td>
            <td><span class="chip-categoria chip-categoria--${r.categoria.toLowerCase()}">${ICONOS_AUDITORIA[r.categoria] || ''} ${escaparAuditoria(r.categoria_display)}</span></td>
            <td>${escaparAuditoria(r.descripcion)}<div class="sub codigo">${escaparAuditoria(r.accion)}</div>${formatearFirmaAuditoria(r.firma, r.motivo)}</td>
            <td class="col-lote">${escaparAuditoria(r.lote_codigo) || '<span class="sin-dato">—</span>'}${r.fase_nombre ? `<div class="sub">${escaparAuditoria(r.fase_nombre)}</div>` : ''}</td>
            <td class="col-motivo">${escaparAuditoria(r.motivo) || '<span class="sin-dato">—</span>'}</td>
            <td>${formatearCambiosAuditoria(r.cambios) || '<span class="sin-dato">—</span>'}</td>
        </tr>`).join('');
}

// CSV con lo que está en pantalla (para auditorías de Calidad)
function exportarCsv() {
    if (!registros.length) return;
    const celda = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const cambiosTexto = c => Object.entries(c || {}).map(([k, [a, d]]) => `${k}: ${valorAuditoria(a)} -> ${valorAuditoria(d)}`).join(' | ');
    const firmaTexto = f => f ? `${f.nombre_firmante} | ${f.significado} | ${f.fecha} | ${f.metodo_display}${f.comentario ? ' | ' + f.comentario : ''}` : '';
    const filas = [['Fecha', 'Quién', 'Roles', 'IP', 'Categoría', 'Acción', 'Descripción', 'Lote', 'Fase', 'Motivo', 'Cambios', 'Firma electrónica']]
        .concat(registros.map(r => [r.fecha, r.actor, r.roles, r.ip, r.categoria_display, r.accion, r.descripcion, r.lote_codigo, r.fase_nombre, r.motivo, cambiosTexto(r.cambios), firmaTexto(r.firma)]));
    const csv = '﻿' + filas.map(f => f.map(celda).join(',')).join('\r\n');
    const enlace = document.createElement('a');
    enlace.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    enlace.download = `bitacora_auditoria_${hoyIso()}.csv`;
    enlace.click();
    URL.revokeObjectURL(enlace.href);
}

iniciar();
