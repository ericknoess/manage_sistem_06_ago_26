// static/core/js/auditoria.js — Muestra registros de la bitácora de auditoría (quién, qué, cuándo, por qué).
// Lo usan la Bitácora (/auditoria/), Piso de planta (historial del lote) y Planificación (historial de la fase).

const ICONOS_AUDITORIA = {
    LOTE: '📦', FASE: '⚙️', ASIGNACION: '👤', MATERIAL_LOTE: '🧪', EQUIPO_LOTE: '🏗️', DATOS_PROCESO: '📊',
    RECETA: '🧫', CATALOGO: '📚', ROSTER: '👥', SESION: '🔑',
};

const NOMBRES_CAMPO = {
    inicio_programado: 'Inicio', estado: 'Estado', cantidad: 'Cantidad', anticipacion_horas: 'Anticipación (h)',
    sucesoras_reajustadas: 'Sucesoras reajustadas', equipos_asignados: 'Equipos', activo: 'Activo',
    equipo: 'Equipo', tipo: 'Tipo', horas_preparacion: 'Preparación (h)', horas_limpieza: 'Limpieza (h)', ocupacion: 'Ocupación',
    momento_del_cambio: 'Momento del cambio', estado_display: 'Estado', calificacion_vence: 'Calificación vence', calibracion_vence: 'Calificación vence', area: 'Área', capacidad: 'Capacidad',
    operador: 'Operador', rol: 'Rol', receta: 'Receta', inicio_planeado: 'Inicio planeado', fases: 'Fases',
    archivado: 'Archivado', nombre: 'Nombre', turno: 'Turno', cuadrilla: 'Cuadrilla', operadores: 'Operadores',
    lote_material: 'Lote del material', caducidad: 'Caducidad', materiales_incompletos: 'Materiales incompletos',
    fase: 'Fase', material: 'Material', origen: 'Origen', actividades: 'Actividades', estrategia: 'Estrategia', registros: 'Registros',
};

function escaparAuditoria(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function valorAuditoria(valor) {
    if (valor === null || valor === undefined || valor === '') return '—';
    if (valor === true) return 'Sí';
    if (valor === false) return 'No';
    if (Array.isArray(valor)) return valor.length ? valor.map(valorAuditoria).join(', ') : '—';
    if (typeof valor === 'object') return JSON.stringify(valor);
    return String(valor);
}

// {"campo": [antes, después]} → lista HTML "Campo: antes → después" (o solo el valor nuevo en altas)
function formatearCambiosAuditoria(cambios) {
    const filas = Object.entries(cambios || {}).map(([campo, par]) => {
        const [antes, despues] = Array.isArray(par) && par.length === 2 ? par : [null, par];
        const nombre = NOMBRES_CAMPO[campo] || campo.replace(/_/g, ' ');
        const valor = antes === null || antes === undefined
            ? `<span class="aud-nuevo">${escaparAuditoria(valorAuditoria(despues))}</span>`
            : despues === null || despues === undefined
                ? `<span class="aud-antes">${escaparAuditoria(valorAuditoria(antes))}</span>`
                : `<span class="aud-antes">${escaparAuditoria(valorAuditoria(antes))}</span> → <span class="aud-nuevo">${escaparAuditoria(valorAuditoria(despues))}</span>`;
        return `<li><span class="aud-campo">${escaparAuditoria(nombre)}:</span> ${valor}</li>`;
    });
    return filas.length ? `<ul class="aud-cambios">${filas.join('')}</ul>` : '';
}

// Manifestación de la firma electrónica: nombre, significado, fecha y método (21 CFR Part 11)
function formatearFirmaAuditoria(firma, motivo = '') {
    if (!firma) return '';
    const comentario = firma.comentario && firma.comentario !== motivo ? firma.comentario : '';
    return `<div class="aud-firma" title="Firma electrónica">✍️ Firmado por <strong>${escaparAuditoria(firma.nombre_firmante)}</strong>
        · «${escaparAuditoria(firma.significado)}» · ${fechaAuditoria(firma.fecha)} · ${escaparAuditoria(firma.metodo_display)}
        ${comentario ? `<div class="aud-firma__comentario">${escaparAuditoria(comentario)}</div>` : ''}</div>`;
}

function fechaAuditoria(iso) {
    return new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

// Lista compacta tipo línea de tiempo (historial de un lote o una fase)
function renderizarHistorialAuditoria(contenedor, registros, { vacio = 'Sin movimientos registrados.' } = {}) {
    if (!registros.length) {
        contenedor.innerHTML = `<div class="aud-vacio">${escaparAuditoria(vacio)}</div>`;
        return;
    }
    contenedor.innerHTML = `<ol class="aud-linea">${registros.map(r => `
        <li class="aud-evento aud-evento--${r.categoria.toLowerCase()}">
            <div class="aud-evento__cabecera">
                <span class="aud-evento__icono">${ICONOS_AUDITORIA[r.categoria] || '•'}</span>
                <span class="aud-evento__descripcion">${escaparAuditoria(r.descripcion)}</span>
            </div>
            <div class="aud-evento__meta">
                <strong>${escaparAuditoria(r.actor)}</strong>${r.roles ? ` · ${escaparAuditoria(r.roles)}` : ''} · ${fechaAuditoria(r.fecha)}
            </div>
            ${r.motivo ? `<div class="aud-motivo">Motivo: ${escaparAuditoria(r.motivo)}</div>` : ''}
            ${formatearCambiosAuditoria(r.cambios)}
            ${formatearFirmaAuditoria(r.firma, r.motivo)}
        </li>`).join('')}</ol>`;
}

async function cargarHistorialAuditoria(filtros) {
    const params = new URLSearchParams(filtros);
    const respuesta = await fetch(`/api/auditoria/?${params}`);
    if (!respuesta.ok) throw new Error('No se pudo leer la bitácora.');
    return respuesta.json();
}
