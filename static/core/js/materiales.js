// static/core/js/materiales.js — utilidades de materiales compartidas por varias pantallas:
// formato de cantidades, íconos de almacenamiento y el buscador de materiales del catálogo.

const ALMACENAMIENTO_INFO = {
    AMBIENTE: { icono: '🌡️', texto: 'Ambiente' },
    REFRIGERADO: { icono: '❄️', texto: '2–8 °C' },
    CONGELADO: { icono: '🧊', texto: '-20 °C' },
    ULTRACONGELADO: { icono: '🥶', texto: '-80 °C' },
};

// "2.000" → "2", "0.250" → "0.25"
function formatearCantidad(cantidad, unidad = '') {
    const n = Number(cantidad);
    const texto = Number.isFinite(n) ? n.toLocaleString('es-MX', { maximumFractionDigits: 3 }) : cantidad;
    return unidad ? `${texto} ${unidad}` : `${texto}`;
}

function iconoAlmacenamiento(condicion) {
    return (ALMACENAMIENTO_INFO[condicion] || ALMACENAMIENTO_INFO.AMBIENTE).icono;
}

function textoAlmacenamiento(condicion) {
    return (ALMACENAMIENTO_INFO[condicion] || ALMACENAMIENTO_INFO.AMBIENTE).texto;
}

// Escapa texto para insertarlo en HTML (nombres de material, proveedores, motivos).
function escaparHtml(texto) {
    return String(texto ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Normaliza para buscar sin distinguir mayúsculas ni acentos.
function normalizarBusqueda(texto) {
    return String(texto ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

// Todas las palabras escritas deben aparecer en código, nombre, categoría, código ERP o proveedor.
function materialCoincide(material, consulta) {
    const palabras = normalizarBusqueda(consulta).split(/\s+/).filter(Boolean);
    if (!palabras.length) return true;
    const pajar = normalizarBusqueda([
        material.id, material.nombre, material.categoria_display, material.codigo_erp, material.proveedor,
    ].join(' '));
    return palabras.every(p => pajar.includes(p));
}

/**
 * Buscador de materiales con autocompletado y navegación por teclado.
 *   contenedor:      elemento donde se dibuja el campo
 *   obtenerMateriales(): lista actual del catálogo (solo se ofrecen los activos)
 *   excluir():       Set de ids que ya están agregados (se muestran deshabilitados)
 *   alSeleccionar(material): se llama al elegir uno con clic o Enter
 *   enLinea:         la lista empuja el contenido en vez de flotar (útil dentro de modales con scroll)
 */
function crearSelectorMateriales(contenedor, { obtenerMateriales, excluir = () => new Set(), alSeleccionar, placeholder, enLinea = false }) {
    contenedor.classList.add('selector-material');
    contenedor.classList.toggle('selector-material--en-linea', enLinea);
    contenedor.innerHTML = `
        <input type="search" class="selector-material__input" autocomplete="off"
               placeholder="${placeholder || '🔎 Buscar material por código, nombre, categoría, ERP o proveedor…'}">
        <div class="selector-material__lista" role="listbox" hidden></div>
    `;
    const input = contenedor.querySelector('.selector-material__input');
    const lista = contenedor.querySelector('.selector-material__lista');
    let resultados = [];
    let indiceActivo = -1;

    const dibujar = () => {
        const yaAgregados = excluir();
        resultados = obtenerMateriales()
            .filter(m => m.activo !== false && materialCoincide(m, input.value))
            .slice(0, 40);
        indiceActivo = resultados.findIndex(m => !yaAgregados.has(m.id));

        if (!resultados.length) {
            lista.innerHTML = `<div class="selector-material__vacio">Sin coincidencias. <a href="/materiales/catalogo/" target="_blank">Abrir catálogo ↗</a></div>`;
        } else {
            lista.innerHTML = resultados.map((m, i) => {
                const agregado = yaAgregados.has(m.id);
                return `
                    <div class="selector-material__opcion${agregado ? ' is-agregado' : ''}${i === indiceActivo ? ' is-activa' : ''}" data-indice="${i}" role="option">
                        <span class="selector-material__codigo">${escaparHtml(m.id)}</span>
                        <span class="selector-material__nombre">${escaparHtml(m.nombre)}</span>
                        <span class="selector-material__meta">${iconoAlmacenamiento(m.condicion_almacenamiento)} ${escaparHtml(m.categoria_display || '')} · ${escaparHtml(m.unidad_medida || '')}${agregado ? ' · ya agregado' : ''}</span>
                    </div>`;
            }).join('');
        }
        lista.hidden = false;
    };

    const elegir = (indice) => {
        const material = resultados[indice];
        if (!material || excluir().has(material.id)) return;
        alSeleccionar(material);
        input.value = '';
        lista.hidden = true;
        input.focus();
    };

    const moverActiva = (paso) => {
        const yaAgregados = excluir();
        let i = indiceActivo;
        for (let n = 0; n < resultados.length; n++) {
            i = (i + paso + resultados.length) % resultados.length;
            if (!yaAgregados.has(resultados[i].id)) break;
        }
        indiceActivo = i;
        lista.querySelectorAll('.selector-material__opcion').forEach(el => {
            el.classList.toggle('is-activa', Number(el.dataset.indice) === indiceActivo);
        });
        lista.querySelector('.is-activa')?.scrollIntoView({ block: 'nearest' });
    };

    input.addEventListener('focus', dibujar);
    input.addEventListener('input', dibujar);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); lista.hidden ? dibujar() : moverActiva(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); moverActiva(-1); }
        else if (e.key === 'Enter') { e.preventDefault(); elegir(indiceActivo); }
        else if (e.key === 'Escape') { lista.hidden = true; }
    });
    // mousedown en lugar de click: se dispara antes de que el input pierda el foco
    lista.addEventListener('mousedown', (e) => {
        const opcion = e.target.closest('.selector-material__opcion');
        if (opcion) { e.preventDefault(); elegir(Number(opcion.dataset.indice)); }
    });
    input.addEventListener('blur', () => setTimeout(() => { lista.hidden = true; }, 120));

    return { enfocar: () => input.focus(), limpiar: () => { input.value = ''; lista.hidden = true; } };
}
