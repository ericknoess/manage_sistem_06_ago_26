// procesos/static/procesos/js/retrasos.js — Pantalla /retrasos/: retraso de cada lote y dónde se originó.
//
// Lista: GET /api/lotes/retrasos/ (retraso estimado y origen principal por lote). Detalle: GET /api/lotes/<id>/retrasos/
// (cálculo en `analisis_retrasos`, procesos/services.py). Cada actividad se compara contra su línea base CPM:
//   heredado  = retraso que trae de su predecesora
//   espera    = retraso que nació aquí al iniciar (inició tarde, sigue sin iniciar o se reprogramó)
//   duración  = retraso que nació aquí por tardar más (o menos) de lo planeado
// La URL acepta ?lote=<id> (desde Piso de planta).

let lotes = [];
let loteAbierto = null;
let detalleActual = null;
let soloConRetraso = true;
let soloFueraTolerancia = true;
const parametrosUrl = new URLSearchParams(location.search);

const UMBRAL_H = 5 / 60;   // menos de 5 minutos no se cuenta como retraso

// 3.5 → "3 h 30 min"; 50 → "2 d 2 h"; con signo: "+3 h", "−45 min"
function horasTexto(h, conSigno = false) {
    const signo = h > 0 ? '+' : '−';
    const total = Math.round(Math.abs(h) * 60);
    if (total < 5) return '0';
    const dias = Math.floor(total / 1440), horas = Math.floor((total % 1440) / 60), min = total % 60;
    let texto;
    if (dias) texto = `${dias} d${horas ? ` ${horas} h` : ''}`;
    else if (horas) texto = `${horas} h${min ? ` ${min} min` : ''}`;
    else texto = `${min} min`;
    return conSigno ? `${signo}${texto}` : texto;
}

const fechaHora = (iso) => iso ? new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
const ESTADOS = { PLANEADO: 'Planeado', EN_PROGRESO: 'En curso', COMPLETADO: 'Completado', DESVIACION: 'Detenido', ABORTADO: 'Abortado',
                  PENDIENTE: 'Pendiente', COMPLETADA: 'Completada', OMITIDA: 'Omitida' };
const claseRetraso = (h) => h > 24 ? 'rt-valor--alto' : h > UMBRAL_H ? 'rt-valor--medio' : h < -UMBRAL_H ? 'rt-valor--adelanto' : 'rt-valor--cero';

async function iniciar() {
    try {
        const res = await fetch('/api/procesos-maestros/');
        const recetas = res.ok ? await res.json() : [];
        document.getElementById('filtroReceta').innerHTML = '<option value="">Todas las recetas</option>'
            + (Array.isArray(recetas) ? recetas : recetas.results || [])
                .map(r => `<option value="${r.id}">${escaparHtml(r.nombre)}</option>`).join('');
    } catch (e) { /* el filtro de receta es opcional */ }
    if (parametrosUrl.get('lote')) document.getElementById('filtroArchivados').checked = true;
    await cargarLotes();
    if (parametrosUrl.get('lote')) abrirLote(Number(parametrosUrl.get('lote')));
}

async function cargarLotes() {
    const p = new URLSearchParams();
    const receta = document.getElementById('filtroReceta').value;
    const estado = document.getElementById('filtroEstado').value;
    if (receta) p.set('proceso', receta);
    if (estado === 'todos') p.set('todos', '1');
    else if (estado) p.set('estado', estado);
    if (document.getElementById('filtroArchivados').checked) p.set('archivados', '1');
    const caja = document.getElementById('listaLotes');
    try {
        const res = await fetch(`/api/lotes/retrasos/?${p}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || data.detail || 'No se pudieron cargar los lotes.');
        lotes = data.sort((a, b) => b.retraso_horas - a.retraso_horas);
        pintarLotes();
    } catch (e) {
        caja.innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
    }
}

function textoOrigen(origen) {
    if (!origen) return '<span class="rt-sub">Sin retraso propio</span>';
    const que = origen.tipo === 'INICIO' ? 'inicio tarde' : 'duró más';
    return `<span class="rt-sub">Origen: <strong>[${escaparHtml(origen.paso)}] ${escaparHtml(origen.nombre)}</strong> · ${que} ${horasTexto(origen.horas)}</span>`;
}

function pintarLotes() {
    const texto = document.getElementById('filtroTexto').value.trim().toLowerCase();
    const visibles = lotes.filter(l => !texto || l.identificador_lote.toLowerCase().includes(texto));
    document.getElementById('conteo').textContent = `${visibles.length} lote${visibles.length === 1 ? '' : 's'}`
        + (visibles.length ? ` · ${visibles.filter(l => l.retraso_horas > UMBRAL_H).length} con retraso` : '');
    const caja = document.getElementById('listaLotes');
    if (!visibles.length) { caja.innerHTML = '<div class="estado-vacio">No hay lotes con estos filtros.</div>'; return; }
    caja.innerHTML = visibles.map(l => `
        <button type="button" class="rt-lote ${loteAbierto === l.id ? 'rt-lote--activo' : ''}" onclick="abrirLote(${l.id})">
            <span class="rt-lote__fila">
                <strong class="rt-lote__codigo">${escaparHtml(l.identificador_lote)}</strong>
                <span class="rt-valor ${claseRetraso(l.retraso_horas)}">${l.retraso_horas > UMBRAL_H ? horasTexto(l.retraso_horas, true)
                    : l.retraso_horas < -UMBRAL_H ? `${horasTexto(l.retraso_horas, true)} adelantado` : 'A tiempo'}</span>
            </span>
            <span class="rt-sub">${escaparHtml(l.receta)} · ${ESTADOS[l.estado] || l.estado}${l.terminado ? '' : ' · estimado'}${l.archivado ? ' · archivado' : ''}</span>
            ${l.retraso_horas > UMBRAL_H ? textoOrigen(l.origen) : ''}
        </button>`).join('');
}

async function abrirLote(id) {
    loteAbierto = id;
    pintarLotes();
    history.replaceState(null, '', `?lote=${id}`);
    const caja = document.getElementById('detalle');
    caja.innerHTML = '<div class="estado-vacio">Calculando retrasos…</div>';
    try {
        const res = await fetch(`/api/lotes/${id}/retrasos/`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || data.detail || 'No se pudo calcular el retraso del lote.');
        if (loteAbierto !== id) return;
        detalleActual = data;
        pintarDetalle();
    } catch (e) {
        caja.innerHTML = `<div class="estado-vacio">⚠️ ${escaparHtml(e.message)}</div>`;
    }
}

// Frase de lo que nació en la actividad al iniciar, según si ya inició, sigue pendiente o se reprogramó
function textoEspera(a) {
    if (a.espera_h > UMBRAL_H) {
        if (a.inicio_real) return `Inició ${horasTexto(a.espera_h)} tarde`;
        if (a.estado === 'PENDIENTE' && new Date(a.inicio) <= new Date(detalleActual.ahora)) return `Lleva ${horasTexto(a.espera_h)} sin iniciar`;
        return `Se reprogramó ${horasTexto(a.espera_h)} después`;
    }
    if (a.espera_h < -UMBRAL_H) return `Inició ${horasTexto(a.espera_h)} antes`;
    return '';
}

function textoDuracion(a) {
    if (Math.abs(a.duracion_extra_h) <= UMBRAL_H) return '';
    if (a.duracion_extra_h < 0) return `Duró ${horasTexto(a.duracion_extra_h)} menos`;
    return a.fin_real ? `Duró ${horasTexto(a.duracion_extra_h)} más` : `Va ${horasTexto(a.duracion_extra_h)} arriba de su duración`;
}

function pintarDetalle() {
    const d = detalleActual;
    const l = d.lote;
    const porId = Object.fromEntries(d.actividades.map(a => [a.id, a]));
    const ruta = d.ruta.map(id => porId[id]).filter(Boolean);
    const origen = d.origen;
    const conMotivo = (a) => a.motivos.length || a.eventos.length || a.reprogramacion;

    const tarjetaOrigen = origen ? `
        <div class="rt-tarjeta rt-tarjeta--origen">
            <span class="rt-tarjeta__etiqueta">Origen principal</span>
            <strong>[${escaparHtml(origen.paso)}] ${escaparHtml(origen.nombre)}</strong>
            <span class="rt-sub">${origen.tipo === 'INICIO' ? textoEspera(porId[origen.fase]) : textoDuracion(porId[origen.fase])}
                ${origen.en_ruta ? '' : ' · fuera de la ruta que fija el fin'}</span>
        </div>` : `
        <div class="rt-tarjeta"><span class="rt-tarjeta__etiqueta">Origen principal</span><strong>Ninguno</strong>
            <span class="rt-sub">Ninguna actividad agregó retraso propio.</span></div>`;

    document.getElementById('detalle').innerHTML = `
        <div class="rt-cabecera">
            <div>
                <h3>${escaparHtml(l.identificador_lote)} <span class="rt-estado">${ESTADOS[l.estado] || l.estado}${l.archivado ? ' · archivado' : ''}</span></h3>
                <span class="rt-sub">${escaparHtml(l.receta)}${l.terminado ? '' : ` · estimado al ${fechaHora(d.ahora)}`}</span>
            </div>
            <nav class="rt-enlaces">
                <a class="btn-secundario" href="/eventos/?lote=${l.id}">⚠️ Eventos del lote</a>
            </nav>
        </div>

        <div class="rt-tarjetas">
            <div class="rt-tarjeta">
                <span class="rt-tarjeta__etiqueta">${l.terminado ? 'Retraso al terminar' : 'Retraso estimado al terminar'}</span>
                <strong class="rt-valor ${claseRetraso(d.retraso_horas)} rt-valor--grande">${Math.abs(d.retraso_horas) <= UMBRAL_H ? 'A tiempo' : horasTexto(d.retraso_horas, true)}</strong>
                <span class="rt-sub">Fin planeado ${fechaHora(d.fin_base)} → ${l.terminado ? 'real' : 'estimado'} ${fechaHora(d.fin_estimado)}</span>
            </div>
            ${tarjetaOrigen}
            <div class="rt-tarjeta">
                <span class="rt-tarjeta__etiqueta">Muestreos fuera de tolerancia</span>
                <strong class="rt-valor ${d.muestreos_fuera_tolerancia ? 'rt-valor--medio' : 'rt-valor--cero'} rt-valor--grande">${d.muestreos_fuera_tolerancia}</strong>
                <span class="rt-sub">${d.muestreos.length} muestreo${d.muestreos.length === 1 ? '' : 's'} tomados tarde (no mueven el fin del lote)</span>
            </div>
        </div>

        <section class="rt-seccion">
            <h4>Cómo se acumuló el retraso</h4>
            <p class="rt-ayuda">La ruta es la cadena de actividades que fija el fin del lote. Cada barra arranca en el retraso que la actividad
                heredó y muestra lo que nació en ella: <span class="rt-muestra rt-muestra--espera"></span> al iniciar
                y <span class="rt-muestra rt-muestra--duracion"></span> por su duración
                (<span class="rt-muestra rt-muestra--recupera"></span> tiempo recuperado).</p>
            ${htmlCascada(ruta)}
        </section>

        <section class="rt-seccion">
            <div class="rt-seccion__titulo">
                <h4>Actividades</h4>
                <label class="check-filtro"><input type="checkbox" ${soloConRetraso ? 'checked' : ''}
                    onchange="soloConRetraso = this.checked; pintarDetalle()"> Solo las que agregaron retraso o tienen motivo</label>
            </div>
            ${htmlTablaActividades(d.actividades.filter(a => !soloConRetraso || a.espera_h > UMBRAL_H || a.duracion_extra_h > UMBRAL_H || conMotivo(a)))}
        </section>

        <section class="rt-seccion">
            <div class="rt-seccion__titulo">
                <h4>Muestreos tomados tarde</h4>
                <label class="check-filtro"><input type="checkbox" ${soloFueraTolerancia ? 'checked' : ''}
                    onchange="soloFueraTolerancia = this.checked; pintarDetalle()"> Solo fuera de tolerancia</label>
            </div>
            ${htmlTablaMuestreos(d.muestreos.filter(m => !soloFueraTolerancia || m.fuera_tolerancia))}
        </section>`;
}

// Cascada sobre la ruta: cada fila va del retraso heredado al retraso con que terminó la actividad
function htmlCascada(ruta) {
    if (!ruta.length) return '<div class="estado-vacio">El lote no tiene actividades con línea base.</div>';
    const valores = ruta.flatMap(a => [Math.max(0, a.heredado_h), a.retraso_inicio_h, a.retraso_fin_h]);
    const min = Math.min(0, ...valores), max = Math.max(0, ...valores);
    const rango = (max - min) || 1;
    const x = (h) => ((h - min) / rango) * 100;
    const segmento = (desde, hasta, clase, titulo) => {
        if (Math.abs(hasta - desde) <= UMBRAL_H) return '';
        const izq = x(Math.min(desde, hasta)), ancho = Math.max(0.6, Math.abs(x(hasta) - x(desde)));
        return `<span class="rt-barra ${hasta < desde ? 'rt-barra--recupera' : clase}" style="left:${izq}%;width:${ancho}%" title="${escaparHtml(titulo)}"></span>`;
    };
    const filas = ruta.map(a => {
        const partida = Math.max(0, a.heredado_h);
        const propio = [textoEspera(a), textoDuracion(a)].filter(Boolean).join(' · ');
        const origen = detalleActual.origen && detalleActual.origen.fase === a.id;
        return `
            <div class="rt-cascada__fila ${origen ? 'rt-cascada__fila--origen' : ''}">
                <span class="rt-cascada__nombre" title="${escaparHtml(a.etapa)}">
                    <strong>[${escaparHtml(a.paso)}]</strong> ${escaparHtml(a.nombre)}
                    <span class="rt-sub">${ESTADOS[a.estado] || a.estado}${a.etapa ? ` · ${escaparHtml(a.etapa)}` : ''}</span>
                </span>
                <span class="rt-cascada__pista">
                    <span class="rt-cero" style="left:${x(0)}%"></span>
                    ${partida > UMBRAL_H ? `<span class="rt-arrastre" style="left:${x(0)}%;width:${x(partida) - x(0)}%" title="Heredado: ${horasTexto(partida)}"></span>` : ''}
                    ${segmento(partida, a.retraso_inicio_h, 'rt-barra--espera', `Al iniciar: ${horasTexto(a.espera_h, true)}`)}
                    ${segmento(a.retraso_inicio_h, a.retraso_fin_h, 'rt-barra--duracion', `Por duración: ${horasTexto(a.duracion_extra_h, true)}`)}
                </span>
                <span class="rt-cascada__valor">
                    <strong class="rt-valor ${claseRetraso(a.retraso_fin_h)}">${Math.abs(a.retraso_fin_h) <= UMBRAL_H ? 'A tiempo' : horasTexto(a.retraso_fin_h, true)}</strong>
                    <span class="rt-sub">${propio ? escaparHtml(propio) : 'Sin retraso propio'}</span>
                </span>
            </div>`;
    }).join('');
    return `<div class="rt-cascada">${filas}</div>`;
}

function htmlMotivos(a) {
    const partes = [];
    if (a.reprogramacion) {
        partes.push(`<li><span class="rt-motivo__que">Reprogramada:</span> ${escaparHtml(a.reprogramacion.motivo)}${a.reprogramacion.notas
            ? ` — ${escaparHtml(a.reprogramacion.notas)}` : ''}</li>`);
    }
    for (const m of a.motivos) {
        partes.push(`<li><span class="rt-motivo__que">${escaparHtml(m.que)} (${fechaHora(m.momento)}, ${escaparHtml(m.actor)}):</span> ${escaparHtml(m.texto)}</li>`);
    }
    for (const e of a.eventos) {
        partes.push(`<li><a href="/eventos/?evento=${e.id}&lote=${detalleActual.lote.id}">${escaparHtml(e.folio)}</a>
            ${escaparHtml(e.tipo)}: ${escaparHtml(e.titulo)}${e.estado === 'ABIERTO' ? ' <span class="rt-abierto">abierto</span>' : ''}</li>`);
    }
    return partes.length ? `<ul class="rt-motivos">${partes.join('')}</ul>` : '<span class="sin-dato">—</span>';
}

const celdaHoras = (h) => `<td class="rt-num"><span class="rt-valor ${claseRetraso(h)}">${Math.abs(h) <= UMBRAL_H ? '—' : horasTexto(h, true)}</span></td>`;
const horaPlanReal = (plan, real, esReal) => `${fechaHora(plan)}<span class="rt-sub">${esReal ? 'Real' : 'Estimado'}: ${fechaHora(real)}</span>`;

function htmlTablaActividades(actividades) {
    if (!actividades.length) return '<div class="estado-vacio">Ninguna actividad agregó retraso.</div>';
    const filas = actividades.map(a => `
        <tr class="${a.en_ruta ? 'rt-fila--ruta' : ''} ${detalleActual.origen && detalleActual.origen.fase === a.id ? 'rt-fila--origen' : ''}">
            <td><strong>[${escaparHtml(a.paso)}]</strong> ${escaparHtml(a.nombre)}
                <span class="rt-sub">${ESTADOS[a.estado] || a.estado}${a.en_ruta ? ' · en la ruta' : ''}${a.predecesora ? ` · después de [${escaparHtml(a.predecesora)}] (${a.dependencia})` : ''}</span></td>
            <td>${horaPlanReal(a.base_inicio, a.inicio, a.inicio_real)}</td>
            <td>${horaPlanReal(a.base_fin, a.fin, a.fin_real)}</td>
            ${celdaHoras(a.heredado_h)}
            ${celdaHoras(a.espera_h)}
            ${celdaHoras(a.duracion_extra_h)}
            ${celdaHoras(a.retraso_fin_h)}
            <td class="rt-col-motivos">${htmlMotivos(a)}</td>
        </tr>`).join('');
    return `
        <div class="tabla-contenedor rt-tabla">
            <table class="tabla-catalogo">
                <thead><tr>
                    <th>Actividad</th><th>Inicio planeado</th><th>Fin planeado</th>
                    <th class="rt-num" title="Retraso que trae de su predecesora">Heredado</th>
                    <th class="rt-num" title="Retraso que nació al iniciar: inició tarde, sigue sin iniciar o se reprogramó">Nació al iniciar</th>
                    <th class="rt-num" title="Retraso que nació por durar más (o menos) de lo planeado">Nació por duración</th>
                    <th class="rt-num" title="Retraso con que termina (o terminará) la actividad">Al terminar</th>
                    <th>Motivos y eventos</th>
                </tr></thead>
                <tbody>${filas}</tbody>
            </table>
        </div>`;
}

function htmlTablaMuestreos(muestreos) {
    if (!muestreos.length) return `<div class="estado-vacio">${soloFueraTolerancia ? 'Ningún muestreo fuera de tolerancia.' : 'Ningún muestreo tomado tarde.'}</div>`;
    const filas = muestreos.map(m => `
        <tr>
            <td><strong>[${escaparHtml(m.paso)}]</strong> ${escaparHtml(m.nombre)}<span class="rt-sub">${ESTADOS[m.estado] || m.estado}</span></td>
            <td>${fechaHora(m.esperado)}</td>
            <td>${m.inicio_real ? fechaHora(m.inicio) : '<span class="rt-abierto">Aún no se toma</span>'}</td>
            <td class="rt-num"><span class="rt-valor ${m.fuera_tolerancia ? 'rt-valor--alto' : 'rt-valor--medio'}">${horasTexto(m.retraso_h, true)}</span>
                <span class="rt-sub">tolerancia ${horasTexto(m.tolerancia_h) === '0' ? '0 h' : horasTexto(m.tolerancia_h)}</span></td>
            <td class="rt-col-motivos">${htmlMotivos(m)}</td>
        </tr>`).join('');
    return `
        <div class="tabla-contenedor rt-tabla">
            <table class="tabla-catalogo">
                <thead><tr><th>Muestreo</th><th>Le tocaba</th><th>Se tomó</th><th class="rt-num">Retraso</th><th>Motivos y eventos</th></tr></thead>
                <tbody>${filas}</tbody>
            </table>
        </div>`;
}

iniciar();
