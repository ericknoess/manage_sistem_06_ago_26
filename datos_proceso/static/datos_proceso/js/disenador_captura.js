// datos_proceso/static/datos_proceso/js/disenador_captura.js
// Sección "Datos de proceso" de los modales de actividad del diseñador (crear / editar):
//   - si la actividad captura datos (al completar o en cada muestreo) y si su incubación muestrea a las 0 h;
//   - si define la edad 0 de su etapa (al iniciar o al completar) y del lote;
//   - secciones de captura: cuándo aplican, muestra física con código y parámetros con sus límites;
//   - por parámetro, el valor esperado (objetivo fijo y/o curva por edad) que se dibuja en la gráfica de tendencia al capturar.
// Usa de index.js: esIncubacionConMuestreo(modo). Expone inicializarCaptura, renderizarCaptura y obtenerCaptura.

let parametrosCatalogo = [];
const capturaBuilder = { crear: null, editar: null };
const LIMITES_CAPTURA = [
    ['especificacion_min', 'Esp. mín'], ['especificacion_max', 'Esp. máx'],
    ['alerta_min', 'Alerta mín'], ['alerta_max', 'Alerta máx'],
];

function establecerParametrosCatalogo(lista) {
    parametrosCatalogo = lista || [];
    ['crear', 'editar'].forEach(modo => { if (capturaBuilder[modo]) renderizarCaptura(modo); });
}

function parametroCatalogo(id) {
    return parametrosCatalogo.find(p => p.id === id) || { id, codigo: '?', nombre: `Parámetro ${id}`, unidad: '', tipo_dato: 'NUMERO' };
}

function camposMuestreo(modo) {
    const sufijo = modo === 'crear' ? { frec: 'inputFrecMuestreo', dur: 'inputTareaDuracion' } : { frec: 'editOpFrecMuestreo', dur: 'editOpDuracion' };
    return {
        frecuencia: parseInt(document.getElementById(sufijo.frec).value, 10) || 0,
        duracion: parseFloat(document.getElementById(sufijo.dur).value) || 0,
    };
}

function horasDeMuestreo(modo) {
    const { frecuencia, duracion } = camposMuestreo(modo);
    if (!esIncubacionConMuestreo(modo) || !frecuencia) return [];
    const horas = [];
    for (let h = capturaBuilder[modo].muestreo_inicial ? 0 : frecuencia; h <= duracion; h += frecuencia) horas.push(h);
    return horas;
}

function inicializarCaptura(modo, op = null) {
    capturaBuilder[modo] = {
        captura: op ? op.captura_datos || 'NINGUNA' : 'NINGUNA',
        muestreo_inicial: op ? !!op.muestreo_inicial : false,
        edad_cero: op ? op.edad_cero || '' : '',
        edad_cero_lote: op ? !!op.edad_cero_lote : false,
        secciones: (op && op.secciones_captura || []).map(s => ({
            nombre: s.nombre, frecuencia: s.frecuencia, cada_horas: s.cada_horas || '',
            horas: (s.horas || []).join(', '), muestra_fisica: s.muestra_fisica, patron_codigo_muestra: s.patron_codigo_muestra || '',
            parametros: s.parametros.map(p => ({
                parametro: p.parametro, obligatorio: p.obligatorio,
                // El servidor manda "36.000000": se muestra como 36
                ...Object.fromEntries([...LIMITES_CAPTURA.map(([c]) => c), 'objetivo'].map(c => [c, p[c] === null || p[c] === undefined ? '' : String(Number(p[c]))])),
                eje_edad: p.eje_edad || 'LOTE',
                curva: (p.curva_referencia || []).map(([edad, valor]) => `${edad}\t${valor}`).join('\n'),
                curva_abierta: false,
            })),
        })),
    };
    renderizarCaptura(modo);
}

function cambiarCaptura(modo, campo, valor) {
    capturaBuilder[modo][campo] = valor;
    if (campo === 'captura' && valor !== 'NINGUNA' && !capturaBuilder[modo].secciones.length) agregarSeccionCaptura(modo);
    else renderizarCaptura(modo);
}

function agregarSeccionCaptura(modo) {
    capturaBuilder[modo].secciones.push({
        nombre: '', frecuencia: 'TODOS', cada_horas: '', horas: '', muestra_fisica: false, patron_codigo_muestra: '', parametros: [],
    });
    renderizarCaptura(modo);
    const nombres = document.querySelectorAll(`#capturaBuilder${modo === 'crear' ? 'Crear' : 'Editar'} .seccion-captura__nombre`);
    nombres[nombres.length - 1]?.focus();
}

function quitarSeccionCaptura(modo, i) {
    capturaBuilder[modo].secciones.splice(i, 1);
    renderizarCaptura(modo);
}

function moverSeccionCaptura(modo, i, delta) {
    const lista = capturaBuilder[modo].secciones;
    const j = i + delta;
    if (j < 0 || j >= lista.length) return;
    [lista[i], lista[j]] = [lista[j], lista[i]];
    renderizarCaptura(modo);
}

function agregarParametroSeccion(modo, i, select) {
    const id = parseInt(select.value, 10);
    if (!id) return;
    capturaBuilder[modo].secciones[i].parametros.push({
        parametro: id, obligatorio: !parametroCatalogo(id).es_calculado,
        ...Object.fromEntries(LIMITES_CAPTURA.map(([c]) => [c, ''])),
        objetivo: '', eje_edad: 'LOTE', curva: '', curva_abierta: false,
    });
    renderizarCaptura(modo);
}

function quitarParametroSeccion(modo, i, j) {
    capturaBuilder[modo].secciones[i].parametros.splice(j, 1);
    renderizarCaptura(modo);
}

function htmlCuandoSeccion(modo, s, i) {
    if (capturaBuilder[modo].captura !== 'MUESTREOS') return '<span class="seccion-captura__cuando-fijo">Se captura al completar la actividad</span>';
    const ruta = `capturaBuilder['${modo}'].secciones[${i}]`;
    return `
        <select title="En qué muestreos se captura" onchange="${ruta}.frecuencia = this.value; renderizarCaptura('${modo}')">
            <option value="TODOS" ${s.frecuencia === 'TODOS' ? 'selected' : ''}>En todos los muestreos</option>
            <option value="CADA_N" ${s.frecuencia === 'CADA_N' ? 'selected' : ''}>Cada N horas</option>
            <option value="HORAS" ${s.frecuencia === 'HORAS' ? 'selected' : ''}>En horas específicas</option>
        </select>
        ${s.frecuencia === 'CADA_N' ? `<input type="number" min="1" step="1" class="input-corto" placeholder="12" title="Cada cuántas horas (múltiplo de la frecuencia)"
            value="${escaparHtml(String(s.cada_horas))}" oninput="${ruta}.cada_horas = this.value"> h` : ''}
        ${s.frecuencia === 'HORAS' ? `<input type="text" class="input-horas" placeholder="0, 24, 48" title="Horas del muestreo, separadas por coma"
            value="${escaparHtml(s.horas)}" oninput="${ruta}.horas = this.value"> h` : ''}`;
}

function htmlParametrosSeccion(modo, s, i) {
    const ruta = `capturaBuilder['${modo}'].secciones[${i}]`;
    const usados = new Set(capturaBuilder[modo].secciones.flatMap(x => x.parametros.map(p => p.parametro)));
    const disponibles = parametrosCatalogo.filter(p => p.activo && !usados.has(p.id));
    const filas = s.parametros.map((p, j) => {
        const cat = parametroCatalogo(p.parametro);
        const numerico = cat.tipo_dato === 'NUMERO';
        const limite = ([campo, etiqueta]) => `<td><input type="number" step="any" class="input-limite" title="${etiqueta}"
            ${numerico ? '' : 'disabled'} value="${escaparHtml(String(p[campo] ?? ''))}" oninput="${ruta}.parametros[${j}].${campo} = this.value"></td>`;
        return `<tr>
            <td><strong>${escaparHtml(cat.nombre)}</strong> <span class="codigo-parametro">${escaparHtml(cat.codigo)}</span>
                ${cat.unidad ? `<span class="unidad-parametro">${escaparHtml(cat.unidad)}</span>` : ''}
                ${cat.es_calculado ? '<span class="etiqueta-calculado" title="Se calcula con su fórmula">ƒ</span>' : ''}
                ${cat.activo === false ? '<div class="material-inactivo">⚠️ Inactivo en el catálogo</div>' : ''}</td>
            <td class="celda-centro"><input type="checkbox" title="${cat.es_calculado ? 'Calculado: no se captura' : 'Obligatorio para completar la tarea'}"
                ${cat.es_calculado ? 'disabled' : ''} ${p.obligatorio && !cat.es_calculado ? 'checked' : ''}
                onchange="${ruta}.parametros[${j}].obligatorio = this.checked"></td>
            ${LIMITES_CAPTURA.map(limite).join('')}
            ${limite(['objetivo', 'Valor esperado fijo (línea en la gráfica de tendencia)'])}
            <td class="celda-centro"><button type="button" class="btn-curva ${puntosCurva(p.curva) ? 'btn-curva--con' : ''}" ${numerico ? '' : 'disabled'}
                title="Curva esperada por edad (gráfica de tendencia)" onclick="${ruta}.parametros[${j}].curva_abierta = !${ruta}.parametros[${j}].curva_abierta; renderizarCaptura('${modo}')">
                📈${puntosCurva(p.curva) ? ` ${puntosCurva(p.curva)}` : ''}</button></td>
            <td><button type="button" class="btn-icon delete" title="Quitar parámetro" onclick="quitarParametroSeccion('${modo}', ${i}, ${j})">🗑️</button></td>
        </tr>
        ${p.curva_abierta && numerico ? `<tr class="fila-curva"><td colspan="9">
            <div class="editor-curva">
                <label>Graficar contra
                    <select onchange="${ruta}.parametros[${j}].eje_edad = this.value">
                        <option value="LOTE" ${p.eje_edad === 'LOTE' ? 'selected' : ''}>Edad del lote</option>
                        <option value="ETAPA" ${p.eje_edad === 'ETAPA' ? 'selected' : ''}>Edad de la etapa</option>
                    </select>
                </label>
                <label>Curva esperada: una línea por punto, «edad (h)» y «valor» (puedes pegar dos columnas de Excel)
                    <textarea rows="5" class="editor-curva__puntos" placeholder="0	0.26\n12	0.35\n24	0.47"
                        oninput="${ruta}.parametros[${j}].curva = this.value">${escaparHtml(p.curva)}</textarea>
                </label>
                <span class="ayuda-captura">Al capturar, la gráfica muestra los datos anteriores de la etapa, el valor que se escribe, los límites, el valor esperado fijo y esta curva.</span>
            </div></td></tr>` : ''}`;
    }).join('');
    return `
        <table class="tabla-materiales tabla-parametros-seccion">
            <thead><tr>
                <th>Parámetro</th><th style="width: 46px;" title="Obligatorio para completar la tarea">Oblig.</th>
                ${LIMITES_CAPTURA.map(([, e]) => `<th style="width: 74px;">${e}</th>`).join('')}
                <th style="width: 74px;" title="Valor esperado fijo">Esperado</th><th style="width: 52px;" title="Curva esperada por edad">Curva</th><th style="width: 32px;"></th>
            </tr></thead>
            <tbody>${filas || '<tr><td colspan="9" class="tabla-materiales__vacio">Sin parámetros: agrégalos abajo.</td></tr>'}</tbody>
        </table>
        <div class="agregar-parametro">
            <select aria-label="Parámetro a agregar">
                <option value="">${disponibles.length ? '— Elegir parámetro del catálogo —' : 'No quedan parámetros activos en el catálogo'}</option>
                ${disponibles.map(p => `<option value="${p.id}">${escaparHtml(p.nombre)} (${escaparHtml(p.codigo)})${p.es_calculado ? ' ƒ' : ''}</option>`).join('')}
            </select>
            <button type="button" class="btn-agregar-equipo" onclick="agregarParametroSeccion('${modo}', ${i}, this.previousElementSibling)">➕ Agregar parámetro</button>
        </div>`;
}

function renderizarCaptura(modo) {
    const estado = capturaBuilder[modo];
    const contenedor = document.getElementById(modo === 'crear' ? 'capturaBuilderCrear' : 'capturaBuilderEditar');
    if (!estado || !contenedor) return;
    const conMuestreo = esIncubacionConMuestreo(modo);
    if (!conMuestreo) estado.muestreo_inicial = false;
    if (!conMuestreo && estado.captura === 'MUESTREOS') estado.captura = 'COMPLETAR';
    if (!estado.edad_cero) estado.edad_cero_lote = false;
    const horas = horasDeMuestreo(modo);

    const secciones = estado.captura === 'NINGUNA' ? '' : `
        ${conMuestreo && estado.captura === 'MUESTREOS'
            ? `<div class="captura__muestreos">🧪 Muestreos de esta incubación: ${horas.length ? horas.map(h => `${h} h`).join(' · ') : 'ninguno (revisa duración y frecuencia)'}</div>` : ''}
        ${estado.secciones.map((s, i) => {
            const ruta = `capturaBuilder['${modo}'].secciones[${i}]`;
            return `<div class="seccion-captura">
                <div class="seccion-captura__encabezado">
                    <input type="text" class="seccion-captura__nombre" maxlength="100" placeholder="Nombre de la sección (ej. Reactor)"
                           value="${escaparHtml(s.nombre)}" oninput="${ruta}.nombre = this.value">
                    <span class="seccion-captura__cuando">${htmlCuandoSeccion(modo, s, i)}</span>
                    <span class="seccion-captura__orden">
                        <button type="button" class="btn-icon" title="Subir" onclick="moverSeccionCaptura('${modo}', ${i}, -1)">▲</button>
                        <button type="button" class="btn-icon" title="Bajar" onclick="moverSeccionCaptura('${modo}', ${i}, 1)">▼</button>
                        <button type="button" class="btn-icon delete" title="Quitar sección" onclick="quitarSeccionCaptura('${modo}', ${i})">🗑️</button>
                    </span>
                </div>
                <div class="seccion-captura__muestra">
                    <label><input type="checkbox" ${s.muestra_fisica ? 'checked' : ''}
                        onchange="${ruta}.muestra_fisica = this.checked; renderizarCaptura('${modo}')"> Se toma muestra física</label>
                    ${s.muestra_fisica ? `<input type="text" maxlength="60" placeholder="PO41-M{n}" title="{n} = consecutivo (01, 02…), {h} = hora del muestreo"
                        value="${escaparHtml(s.patron_codigo_muestra)}" oninput="${ruta}.patron_codigo_muestra = this.value">
                        <span class="ayuda-captura">{n} = consecutivo · {h} = hora</span>` : ''}
                </div>
                ${htmlParametrosSeccion(modo, s, i)}
            </div>`;
        }).join('')}
        <button type="button" class="btn-agregar-seccion" onclick="agregarSeccionCaptura('${modo}')">➕ Agregar sección</button>`;

    contenedor.innerHTML = `
        <div class="captura__opciones">
            <label>Captura de datos
                <select onchange="cambiarCaptura('${modo}', 'captura', this.value)">
                    <option value="NINGUNA" ${estado.captura === 'NINGUNA' ? 'selected' : ''}>No captura datos</option>
                    <option value="COMPLETAR" ${estado.captura === 'COMPLETAR' ? 'selected' : ''}>Al completar la actividad</option>
                    ${conMuestreo ? `<option value="MUESTREOS" ${estado.captura === 'MUESTREOS' ? 'selected' : ''}>En cada muestreo</option>` : ''}
                </select>
            </label>
            ${conMuestreo ? `<label class="captura__check"><input type="checkbox" ${estado.muestreo_inicial ? 'checked' : ''}
                onchange="cambiarCaptura('${modo}', 'muestreo_inicial', this.checked)"> Muestreo al arrancar (0 h)</label>` : ''}
            <label>Edad 0 de la etapa
                <select onchange="cambiarCaptura('${modo}', 'edad_cero', this.value)" title="La hora real de esta actividad es la edad 0 de su etapa: desde ahí se cuentan las edades de los datos">
                    <option value="" ${!estado.edad_cero ? 'selected' : ''}>No la define</option>
                    <option value="INICIO" ${estado.edad_cero === 'INICIO' ? 'selected' : ''}>Al iniciar esta actividad</option>
                    <option value="FIN" ${estado.edad_cero === 'FIN' ? 'selected' : ''}>Al completar esta actividad</option>
                </select>
            </label>
            ${estado.edad_cero ? `<label class="captura__check"><input type="checkbox" ${estado.edad_cero_lote ? 'checked' : ''}
                onchange="cambiarCaptura('${modo}', 'edad_cero_lote', this.checked)"> También es la edad 0 del lote</label>` : ''}
        </div>
        ${secciones}`;
}

// Texto de la curva → [[edad, valor], …]; NaN si alguna línea no se entiende (se ignora un encabezado en la primera línea)
function leerCurva(texto) {
    const lineas = String(texto || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    const puntos = [];
    for (const [k, linea] of lineas.entries()) {
        let partes = linea.split(/[\t; ]+/).filter(Boolean);
        if (partes.length === 1) partes = partes[0].split(',');
        const numeros = partes.map(x => Number(x.replace(',', '.')));
        if (numeros.length !== 2 || numeros.some(n => !Number.isFinite(n))) {
            if (k === 0) continue;
            return NaN;
        }
        puntos.push(numeros);
    }
    return puntos;
}

function puntosCurva(texto) {
    const puntos = leerCurva(texto);
    return Array.isArray(puntos) ? puntos.length : 0;
}

function numeroOVacio(texto) {
    const t = String(texto ?? '').trim().replace(',', '.');
    if (t === '') return null;
    const n = Number(t);
    return Number.isFinite(n) ? t : NaN;
}

// Devuelve los campos de captura listos para la API, o null (con aviso) si algo no es válido.
function obtenerCaptura(modo) {
    const estado = capturaBuilder[modo];
    if (!estado) return {};
    const resultado = {
        captura_datos: estado.captura, muestreo_inicial: estado.muestreo_inicial,
        edad_cero: estado.edad_cero, edad_cero_lote: estado.edad_cero_lote, secciones_captura: [],
    };
    if (estado.captura === 'NINGUNA') return resultado;
    if (!estado.secciones.length) {
        alert('Agrega al menos una sección de captura, o elige «No captura datos».');
        return null;
    }
    for (const s of estado.secciones) {
        const nombre = s.nombre.trim();
        if (!nombre) { alert('Ponle nombre a todas las secciones de captura.'); return null; }
        if (!s.parametros.length) { alert(`La sección «${nombre}» no tiene parámetros.`); return null; }
        const seccion = {
            nombre, frecuencia: estado.captura === 'MUESTREOS' ? s.frecuencia : 'TODOS',
            cada_horas: 0, horas: [], muestra_fisica: s.muestra_fisica, patron_codigo_muestra: s.muestra_fisica ? s.patron_codigo_muestra.trim() : '',
            parametros: [],
        };
        if (seccion.frecuencia === 'CADA_N') {
            seccion.cada_horas = parseInt(s.cada_horas, 10) || 0;
            if (seccion.cada_horas <= 0) { alert(`Sección «${nombre}»: indica cada cuántas horas se captura.`); return null; }
        }
        if (seccion.frecuencia === 'HORAS') {
            seccion.horas = String(s.horas).split(/[,;\s]+/).filter(Boolean).map(h => parseInt(h, 10));
            if (!seccion.horas.length || seccion.horas.some(isNaN)) { alert(`Sección «${nombre}»: escribe las horas separadas por coma (ej. 0, 24, 48).`); return null; }
        }
        if (seccion.muestra_fisica && !seccion.patron_codigo_muestra) { alert(`Sección «${nombre}»: indica el código de la muestra (ej. PO41-M{n}).`); return null; }
        for (const p of s.parametros) {
            const fila = { parametro: p.parametro, obligatorio: !!p.obligatorio };
            for (const [campo, etiqueta] of LIMITES_CAPTURA) {
                const valor = numeroOVacio(p[campo]);
                if (Number.isNaN(valor)) { alert(`${parametroCatalogo(p.parametro).nombre}: «${etiqueta}» debe ser un número.`); return null; }
                fila[campo] = valor;
            }
            const objetivo = numeroOVacio(p.objetivo);
            if (Number.isNaN(objetivo)) { alert(`${parametroCatalogo(p.parametro).nombre}: el valor esperado debe ser un número.`); return null; }
            const curva = leerCurva(p.curva);
            if (!Array.isArray(curva)) {
                alert(`${parametroCatalogo(p.parametro).nombre}: revisa la curva esperada; cada línea lleva dos números (edad y valor).`);
                return null;
            }
            Object.assign(fila, { objetivo, curva_referencia: curva, eje_edad: p.eje_edad || 'LOTE' });
            seccion.parametros.push(fila);
        }
        resultado.secciones_captura.push(seccion);
    }
    return resultado;
}

// Mensajes de error del servidor sobre la captura, en texto legible
function mensajeErrorCaptura(datos) {
    const campos = { secciones_captura: 'Captura de datos', captura_datos: 'Captura de datos', edad_cero: 'Edad 0', edad_cero_lote: 'Edad 0 del lote' };
    const textos = [];
    const aplanar = (valor) => typeof valor === 'string' ? [valor]
        : Array.isArray(valor) ? valor.flatMap(aplanar)
        : (valor && typeof valor === 'object') ? Object.values(valor).flatMap(aplanar) : [];
    Object.entries(campos).forEach(([campo, etiqueta]) => {
        if (datos && datos[campo]) textos.push(`${etiqueta}: ${aplanar(datos[campo]).join(' ')}`);
    });
    return textos.join('\n');
}

// Chips para la tabla de actividades de la receta
function chipsCapturaActividad(op) {
    const chips = [];
    if (op.captura_datos && op.captura_datos !== 'NINGUNA') {
        const total = (op.secciones_captura || []).reduce((n, s) => n + s.parametros.length, 0);
        const cuando = op.captura_datos === 'MUESTREOS' ? 'en muestreos' : 'al completar';
        const detalle = (op.secciones_captura || []).map(s => `${s.nombre}: ${s.parametros.map(p => p.parametro_codigo).join(', ')}`).join(' | ');
        chips.push(`<span class="tag-resource chip-captura" title="${escaparHtml(detalle)}">📊 ${total} parámetro${total === 1 ? '' : 's'} ${cuando}</span>`);
    }
    if (op.muestreo_inicial) chips.push('<span class="tag-resource chip-captura" title="Primer muestreo a las 0 h">🧪 M-0h</span>');
    if (op.edad_cero) {
        const momento = op.edad_cero === 'FIN' ? 'al completar' : 'al iniciar';
        chips.push(`<span class="tag-resource chip-edad-cero" title="Su hora real es la edad 0 de la etapa${op.edad_cero_lote ? ' y del lote' : ''}">⏱ Edad 0 ${momento}${op.edad_cero_lote ? ' · lote' : ''}</span>`);
    }
    return chips.join(' ');
}
