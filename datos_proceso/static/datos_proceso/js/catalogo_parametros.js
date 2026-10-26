// datos_proceso/static/datos_proceso/js/catalogo_parametros.js
// Catálogo de parámetros de proceso: búsqueda, filtros, alta, edición, fórmulas (con probador) y baja lógica.

let parametros = [];
let opcionesCatalogo = { tipos: [], funciones: [] };
let parametroEnEdicion = null;  // id del parámetro que se edita; null = alta
let temporizadorPrueba = null;

async function cargarCatalogo() {
    try {
        const [resPar, resOpc] = await Promise.all([fetch('/api/parametros-proceso/'), fetch('/api/parametros-proceso/opciones/')]);
        parametros = await resPar.json();
        opcionesCatalogo = await resOpc.json();
        llenarSelects();
        renderizarTabla();
    } catch (err) {
        document.getElementById('cuerpoTabla').innerHTML = `<tr><td colspan="9" class="estado-vacio">⚠️ No se pudo cargar el catálogo.</td></tr>`;
    }
}

function llenarSelects() {
    const opcionesHtml = opcionesCatalogo.tipos.map(o => `<option value="${o.valor}">${escaparHtml(o.etiqueta)}</option>`).join('');
    const filtro = document.getElementById('filtroTipo');
    if (filtro.options.length === 1) filtro.insertAdjacentHTML('beforeend', opcionesHtml);
    document.getElementById('campoTipo').innerHTML = opcionesHtml;
    document.getElementById('listaFunciones').innerHTML = opcionesCatalogo.funciones.map(f => `<code>${f}()</code>`).join(' ');
}

function parametrosFiltrados() {
    const texto = normalizarBusqueda(document.getElementById('filtroTexto').value);
    const tipo = document.getElementById('filtroTipo').value;
    const calculo = document.getElementById('filtroCalculo').value;
    const estado = document.getElementById('filtroEstado').value;
    return parametros.filter(p =>
        (!texto || normalizarBusqueda(`${p.codigo} ${p.nombre} ${p.unidad}`).includes(texto))
        && (!tipo || p.tipo_dato === tipo)
        && (!calculo || (calculo === 'calculado') === p.es_calculado)
        && (estado === 'todos' || (estado === 'activos') === p.activo)
    );
}

function detalleTipo(p) {
    if (p.es_calculado) return `<span class="etiqueta-calculado">ƒ calculado</span><code>${escaparHtml(p.formula)}</code>`;
    if (p.tipo_dato === 'OPCION') return escaparHtml(p.opciones.join(' · '));
    return '<span class="sin-dato">—</span>';
}

function renderizarTabla() {
    const lista = parametrosFiltrados();
    document.getElementById('conteo').innerText = `${lista.length} de ${parametros.length} parámetros`;
    const cuerpo = document.getElementById('cuerpoTabla');
    if (!lista.length) {
        cuerpo.innerHTML = `<tr><td colspan="9" class="estado-vacio">${parametros.length ? 'Ningún parámetro coincide con la búsqueda.' : 'Aún no hay parámetros. Crea el primero con «Nuevo parámetro».'}</td></tr>`;
        return;
    }
    cuerpo.innerHTML = lista.map(p => `
        <tr class="${p.activo ? '' : 'fila-inactiva'}">
            <td class="col-codigo">${escaparHtml(p.codigo)}</td>
            <td><strong>${escaparHtml(p.nombre)}</strong>${p.descripcion ? `<br><span class="sin-dato">${escaparHtml(p.descripcion)}</span>` : ''}</td>
            <td>${escaparHtml(p.unidad) || '<span class="sin-dato">—</span>'}</td>
            <td>${escaparHtml(p.tipo_dato_display)}</td>
            <td>${p.tipo_dato === 'NUMERO' ? p.decimales : '<span class="sin-dato">—</span>'}</td>
            <td class="celda-formula">${detalleTipo(p)}</td>
            <td>${p.usos_en_recetas || '<span class="sin-dato">0</span>'}</td>
            <td><span class="estado ${p.activo ? 'estado--activo' : 'estado--inactivo'}">${p.activo ? 'Activo' : 'Inactivo'}</span></td>
            <td class="col-acciones">
                <button class="btn-icono" data-permiso="gestionar_catalogos" title="Editar" onclick="abrirModalParametro(${p.id})">✏️</button>
                ${p.activo
                    ? `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Desactivar (baja lógica)" onclick="cambiarEstado(${p.id}, false)">⏸️</button>`
                    : `<button class="btn-icono" data-permiso="gestionar_catalogos" title="Reactivar" onclick="cambiarEstado(${p.id}, true)">▶️</button>`}
            </td>
        </tr>`).join('');
}

// --- Alta y edición --------------------------------------------------------------

function actualizarCamposPorTipo() {
    const tipo = document.getElementById('campoTipo').value;
    const numerico = tipo === 'NUMERO';
    document.getElementById('grupoDecimales').hidden = !numerico;
    document.getElementById('grupoOpciones').hidden = tipo !== 'OPCION';
    document.getElementById('grupoFormula').hidden = !numerico;
    if (!numerico) document.getElementById('campoEsCalculado').checked = false;
    const calculado = document.getElementById('campoEsCalculado').checked;
    document.getElementById('bloqueFormula').hidden = !calculado;
    document.getElementById('campoFormula').required = calculado;
    if (calculado) programarPruebaFormula();
}

function abrirModalParametro(id = null) {
    parametroEnEdicion = id;
    const p = id ? parametros.find(x => x.id === id) : null;
    document.getElementById('modalParametroTitulo').innerText = p ? `✏️ Editar ${p.codigo}` : '➕ Nuevo parámetro';
    document.getElementById('campoCodigo').value = p ? p.codigo : '';
    document.getElementById('campoCodigo').readOnly = !!p;
    document.getElementById('ayudaCodigo').innerText = p
        ? 'El código no se puede cambiar: lo usan fórmulas, recetas y datos capturados.'
        : 'Minúsculas, números y _; lo usan las fórmulas. No cambia después.';
    document.getElementById('campoNombre').value = p ? p.nombre : '';
    document.getElementById('campoUnidad').value = p ? p.unidad : '';
    document.getElementById('campoTipo').value = p ? p.tipo_dato : 'NUMERO';
    document.getElementById('campoDecimales').value = p ? p.decimales : 2;
    document.getElementById('campoOpciones').value = p ? p.opciones.join('\n') : '';
    document.getElementById('campoEsCalculado').checked = p ? p.es_calculado : false;
    document.getElementById('campoFormula').value = p ? p.formula : '';
    document.getElementById('campoDescripcion').value = p ? p.descripcion : '';
    document.getElementById('probadorFormula').innerHTML = '';
    document.getElementById('errorParametro').hidden = true;
    actualizarCamposPorTipo();
    document.getElementById('modalParametro').style.display = 'flex';
    document.getElementById(p ? 'campoNombre' : 'campoCodigo').focus();
}

function cerrarModalParametro() {
    document.getElementById('modalParametro').style.display = 'none';
}

function mostrarErrorFormulario(datos) {
    const caja = document.getElementById('errorParametro');
    const nombres = { codigo: 'Código', nombre: 'Nombre', tipo_dato: 'Tipo', opciones: 'Opciones', formula: 'Fórmula', decimales: 'Decimales' };
    const mensajes = typeof datos === 'object'
        ? Object.entries(datos).map(([campo, errores]) => `${nombres[campo] || campo}: ${[].concat(errores).join(' ')}`)
        : [String(datos)];
    caja.innerHTML = mensajes.map(escaparHtml).join('<br>');
    caja.hidden = false;
}

async function guardarParametro(evento) {
    evento.preventDefault();
    const tipo = document.getElementById('campoTipo').value;
    const calculado = tipo === 'NUMERO' && document.getElementById('campoEsCalculado').checked;
    const datos = {
        nombre: document.getElementById('campoNombre').value.trim(),
        unidad: document.getElementById('campoUnidad').value.trim(),
        tipo_dato: tipo,
        decimales: parseInt(document.getElementById('campoDecimales').value, 10) || 0,
        opciones: tipo === 'OPCION' ? document.getElementById('campoOpciones').value.split('\n').map(o => o.trim()).filter(Boolean) : [],
        formula: calculado ? document.getElementById('campoFormula').value.trim() : '',
        descripcion: document.getElementById('campoDescripcion').value.trim(),
    };
    if (!parametroEnEdicion) datos.codigo = document.getElementById('campoCodigo').value.trim();

    const url = parametroEnEdicion ? `/api/parametros-proceso/${parametroEnEdicion}/` : '/api/parametros-proceso/';
    try {
        const res = await fetch(url, {
            method: parametroEnEdicion ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify(datos),
        });
        if (!res.ok) return mostrarErrorFormulario(await res.json());
        cerrarModalParametro();
        await cargarCatalogo();
    } catch (err) {
        mostrarErrorFormulario('Error de red al guardar el parámetro.');
    }
}

// --- Probador de fórmulas: valida al escribir y calcula con valores de prueba -------

function programarPruebaFormula() {
    clearTimeout(temporizadorPrueba);
    temporizadorPrueba = setTimeout(probarFormula, 350);
}

async function probarFormula() {
    const caja = document.getElementById('probadorFormula');
    const formula = document.getElementById('campoFormula').value.trim();
    if (!formula) { caja.innerHTML = ''; return; }
    const valores = {};
    caja.querySelectorAll('[data-variable]').forEach(input => { if (input.value !== '') valores[input.dataset.variable] = input.value; });
    try {
        const res = await fetch('/api/parametros-proceso/probar-formula/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ formula, valores, codigo: document.getElementById('campoCodigo').value.trim() }),
        });
        const datos = await res.json();
        if (!res.ok) {
            caja.innerHTML = `<span class="probador__error">⚠️ ${escaparHtml(datos.error || 'Fórmula no válida.')}</span>`;
            return;
        }
        const resultado = datos.resultado === null || datos.resultado === undefined
            ? '<span class="sin-dato">Captura valores de prueba para ver el resultado.</span>'
            : `Resultado: <span class="probador__resultado">${Number(datos.resultado.toFixed(6))}</span>`;
        caja.innerHTML = `
            ✅ Fórmula válida. Prueba con valores:
            <div class="probador__variables">
                ${datos.variables.map(v => `<label>${escaparHtml(v)} <input type="number" step="any" data-variable="${escaparHtml(v)}"
                    value="${valores[v] ?? ''}" oninput="programarPruebaFormula()"></label>`).join('')}
            </div>
            ${resultado}`;
        // Conserva el foco en el valor de prueba que se estaba escribiendo
        const enfocado = document.activeElement?.dataset?.variable;
        if (enfocado) caja.querySelector(`[data-variable="${CSS.escape(enfocado)}"]`)?.focus();
    } catch (err) {
        caja.innerHTML = '<span class="probador__error">No se pudo validar la fórmula (error de red).</span>';
    }
}

// --- Baja lógica -----------------------------------------------------------------

async function cambiarEstado(id, activo) {
    const p = parametros.find(x => x.id === id);
    if (!activo) {
        const aviso = p.usos_en_recetas
            ? `\n\nSe captura en ${p.usos_en_recetas} actividad(es) de recetas: ahí se conserva, pero ya no se podrá agregar a recetas nuevas.`
            : '';
        if (!confirm(`¿Desactivar [${p.codigo}] ${p.nombre}?${aviso}`)) return;
    }
    try {
        const res = await fetch(`/api/parametros-proceso/${id}/`, {
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
    if (e.key === 'Escape' && document.getElementById('modalParametro').style.display === 'flex') cerrarModalParametro();
});
document.addEventListener('DOMContentLoaded', cargarCatalogo);
