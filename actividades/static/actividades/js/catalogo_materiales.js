// actividades/static/actividades/js/catalogo_materiales.js
// Catálogo maestro de materiales: búsqueda, filtros, alta, edición y baja lógica (activo=false).

let materiales = [];
let opciones = { categorias: [], unidades: [], almacenamiento: [] };
let materialEnEdicion = null;  // id del material que se edita; null = alta

async function cargarCatalogo() {
    try {
        const [resMat, resOpc] = await Promise.all([fetch('/api/materiales/'), fetch('/api/materiales/opciones/')]);
        materiales = await resMat.json();
        opciones = await resOpc.json();
        llenarSelects();
        renderizarTabla();
    } catch (err) {
        document.getElementById('cuerpoTabla').innerHTML = `<tr><td colspan="11" class="estado-vacio">⚠️ No se pudo cargar el catálogo.</td></tr>`;
    }
}

function llenarSelects() {
    const opcionesHtml = (lista) => lista.map(o => `<option value="${o.valor}">${escaparHtml(o.etiqueta)}</option>`).join('');
    const filtroCat = document.getElementById('filtroCategoria');
    const filtroAlm = document.getElementById('filtroAlmacenamiento');
    if (filtroCat.options.length === 1) filtroCat.insertAdjacentHTML('beforeend', opcionesHtml(opciones.categorias));
    if (filtroAlm.options.length === 1) filtroAlm.insertAdjacentHTML('beforeend', opcionesHtml(opciones.almacenamiento));
    document.getElementById('campoCategoria').innerHTML = opcionesHtml(opciones.categorias);
    document.getElementById('campoUnidad').innerHTML = opcionesHtml(opciones.unidades);
    document.getElementById('campoAlmacenamiento').innerHTML = opcionesHtml(opciones.almacenamiento);
}

function materialesFiltrados() {
    const texto = document.getElementById('filtroTexto').value;
    const categoria = document.getElementById('filtroCategoria').value;
    const almacenamiento = document.getElementById('filtroAlmacenamiento').value;
    const estado = document.getElementById('filtroEstado').value;
    return materiales.filter(m =>
        materialCoincide(m, texto)
        && (!categoria || m.categoria === categoria)
        && (!almacenamiento || m.condicion_almacenamiento === almacenamiento)
        && (estado === 'todos' || (estado === 'activos') === m.activo)
    );
}

function renderizarTabla() {
    const lista = materialesFiltrados();
    document.getElementById('conteo').innerText = `${lista.length} de ${materiales.length} materiales`;
    const cuerpo = document.getElementById('cuerpoTabla');
    if (!lista.length) {
        cuerpo.innerHTML = `<tr><td colspan="11" class="estado-vacio">Ningún material coincide con la búsqueda.</td></tr>`;
        return;
    }
    cuerpo.innerHTML = lista.map(m => `
        <tr class="${m.activo ? '' : 'fila-inactiva'}">
            <td class="col-codigo">${escaparHtml(m.id)}</td>
            <td><strong>${escaparHtml(m.nombre)}</strong></td>
            <td>${escaparHtml(m.categoria_display)}</td>
            <td>${escaparHtml(m.unidad_medida)}</td>
            <td>${iconoAlmacenamiento(m.condicion_almacenamiento)} ${escaparHtml(m.condicion_almacenamiento_display)}</td>
            <td>${escaparHtml(m.codigo_erp) || '<span class="sin-dato">—</span>'}</td>
            <td>${escaparHtml(m.proveedor) || '<span class="sin-dato">—</span>'}</td>
            <td>${m.stock_controlado ? '✔' : '<span class="sin-dato">—</span>'}</td>
            <td>${m.usos_en_recetas || '<span class="sin-dato">0</span>'}</td>
            <td><span class="estado ${m.activo ? 'estado--activo' : 'estado--inactivo'}">${m.activo ? 'Activo' : 'Inactivo'}</span></td>
            <td class="col-acciones">
                <button class="btn-icono" data-permiso="gestionar_catalogos" title="Editar" onclick="abrirModalMaterial('${escaparHtml(m.id)}')">✏️</button>
                ${m.activo
                    ? `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Desactivar (baja lógica)" onclick="cambiarEstado('${escaparHtml(m.id)}', false)">⏸️</button>`
                    : `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Reactivar" onclick="cambiarEstado('${escaparHtml(m.id)}', true)">▶️</button>`}
            </td>
        </tr>`).join('');
}

// --- Alta y edición --------------------------------------------------------------

function abrirModalMaterial(id = null) {
    materialEnEdicion = id;
    const m = id ? materiales.find(x => x.id === id) : null;
    document.getElementById('modalMaterialTitulo').innerText = m ? `✏️ Editar ${m.id}` : '➕ Nuevo material';
    document.getElementById('campoId').value = m ? m.id : '';
    document.getElementById('campoId').readOnly = !!m;
    document.getElementById('ayudaCodigo').innerText = m
        ? 'El código no se puede cambiar.'
        : 'Único y permanente: lo referencian recetas y lotes.';
    document.getElementById('campoNombre').value = m ? m.nombre : '';
    document.getElementById('campoCategoria').value = m ? m.categoria : 'OTRO';
    document.getElementById('campoUnidad').value = m ? m.unidad_medida : 'pza';
    document.getElementById('campoAlmacenamiento').value = m ? m.condicion_almacenamiento : 'AMBIENTE';
    document.getElementById('campoErp').value = m ? m.codigo_erp : '';
    document.getElementById('campoProveedor').value = m ? m.proveedor : '';
    document.getElementById('campoStockControlado').checked = m ? m.stock_controlado : true;
    document.getElementById('errorMaterial').hidden = true;
    document.getElementById('modalMaterial').style.display = 'flex';
    document.getElementById(m ? 'campoNombre' : 'campoId').focus();
}

function cerrarModalMaterial() {
    document.getElementById('modalMaterial').style.display = 'none';
}

function mostrarErrorFormulario(datos) {
    const caja = document.getElementById('errorMaterial');
    const mensajes = typeof datos === 'object'
        ? Object.entries(datos).map(([campo, errores]) => `${campo === 'id' ? 'Código' : campo}: ${[].concat(errores).join(' ')}`)
        : [String(datos)];
    caja.innerHTML = mensajes.map(escaparHtml).join('<br>');
    caja.hidden = false;
}

async function guardarMaterial(evento) {
    evento.preventDefault();
    const datos = {
        nombre: document.getElementById('campoNombre').value.trim(),
        categoria: document.getElementById('campoCategoria').value,
        unidad_medida: document.getElementById('campoUnidad').value,
        condicion_almacenamiento: document.getElementById('campoAlmacenamiento').value,
        codigo_erp: document.getElementById('campoErp').value.trim(),
        proveedor: document.getElementById('campoProveedor').value.trim(),
        stock_controlado: document.getElementById('campoStockControlado').checked,
    };
    if (!materialEnEdicion) {
        datos.id = document.getElementById('campoId').value.trim();
        if (materiales.some(m => m.id.toLowerCase() === datos.id.toLowerCase())) {
            return mostrarErrorFormulario({ id: `Ya existe un material con el código "${datos.id}".` });
        }
    }

    const url = materialEnEdicion ? `/api/materiales/${encodeURIComponent(materialEnEdicion)}/` : '/api/materiales/';
    try {
        const res = await fetch(url, {
            method: materialEnEdicion ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify(datos),
        });
        if (!res.ok) return mostrarErrorFormulario(await res.json());
        cerrarModalMaterial();
        await cargarCatalogo();
    } catch (err) {
        mostrarErrorFormulario('Error de red al guardar el material.');
    }
}

// --- Baja lógica -----------------------------------------------------------------

async function cambiarEstado(id, activo) {
    const m = materiales.find(x => x.id === id);
    if (!activo) {
        const aviso = m.usos_en_recetas
            ? `\n\nSe usa en ${m.usos_en_recetas} operación(es) de recetas: ahí se conserva, pero ya no se podrá agregar a recetas ni lotes nuevos.`
            : '';
        if (!confirm(`¿Desactivar [${m.id}] ${m.nombre}?${aviso}`)) return;
    }
    try {
        const res = await fetch(`/api/materiales/${encodeURIComponent(id)}/`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ activo }),
        });
        if (!res.ok) throw new Error('El servidor rechazó el cambio.');
        await cargarCatalogo();
    } catch (err) {
        alert(err.message);
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('modalMaterial').style.display === 'flex') cerrarModalMaterial();
});
document.addEventListener('DOMContentLoaded', cargarCatalogo);
