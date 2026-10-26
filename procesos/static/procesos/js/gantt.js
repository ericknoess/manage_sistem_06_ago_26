// procesos/static/procesos/js/gantt.js

const PIXELS_PER_HOUR = 3;
const MS_PER_HOUR = 60 * 60 * 1000;

let globalMinDate = null;
let globalMaxDate = null;

async function initGantt() {
    const todos = document.getElementById('chkGanttTodos')?.checked;
    try {
        // Barras ya agregadas por etapa en el servidor: no se traen las tareas (un lote puede tener miles)
        const response = await fetch(`/api/lotes/gantt/${todos ? '?todos=1' : ''}`);
        if (!response.ok) throw new Error("Error fetching data");
        const datos = await response.json();
        const aviso = document.getElementById('ganttOcultos');
        if (aviso) aviso.textContent = datos.ocultos ? `${datos.ocultos} lotes terminados hace más de 30 días no se muestran.` : '';

        procesarYRenderizar(datos.lotes);
    } catch (error) {
        document.getElementById('loadingState').innerHTML = `<span style="color:var(--danger)">Error al cargar datos: ${error.message}</span>`;
    }
}

function procesarYRenderizar(lotes) {
    globalMinDate = null;
    globalMaxDate = null;
    const fecha = v => (v ? new Date(v) : null);
    const lotesProcesados = lotes.map(lote => {
        const etapasArray = lote.filas.map(fila => {
            const baseStart = fecha(fila.base_inicio), baseEnd = fecha(fila.base_fin);
            const progStart = fecha(fila.prog_inicio), progEnd = fecha(fila.prog_fin);

            if (baseStart && (!globalMinDate || baseStart < globalMinDate)) globalMinDate = new Date(baseStart);
            if (progStart && (!globalMinDate || progStart < globalMinDate)) globalMinDate = new Date(progStart);
            if (baseEnd && (!globalMaxDate || baseEnd > globalMaxDate)) globalMaxDate = new Date(baseEnd);
            if (progEnd && (!globalMaxDate || progEnd > globalMaxDate)) globalMaxDate = new Date(progEnd);

            const delayHours = (baseEnd && progEnd) ? (progEnd - baseEnd) / MS_PER_HOUR : 0;
            return { nombre: fila.nombre, orden: fila.orden, tipo: fila.tipo, baseStart, baseEnd, progStart, progEnd, delayHours };
        });
        // El servidor ya las manda en orden de etapa (o de actividad) y luego por inicio
        return { ...lote, sinEtapas: lote.sin_etapas, etapasSummary: etapasArray };
    });

    if (!globalMinDate) globalMinDate = new Date();
    if (!globalMaxDate) globalMaxDate = new Date();

    globalMinDate.setDate(globalMinDate.getDate() - 2);
    globalMinDate.setHours(0,0,0,0);

    globalMaxDate.setDate(globalMaxDate.getDate() + 10);
    globalMaxDate.setHours(23,59,59,999);

    const totalMs = globalMaxDate - globalMinDate;
    const totalDays = Math.ceil(totalMs / (24 * MS_PER_HOUR));
    const totalWidthPx = totalDays * 72; 

    document.getElementById('ganttTimeline').style.width = `${totalWidthPx}px`;
    document.getElementById('ganttTimeline').style.minWidth = `${totalWidthPx}px`;

    const headerHtml = [];
    const nombresDias = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
    const nombresMeses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
    let currentDay = new Date(globalMinDate);
    const todayStr = new Date().toISOString().split('T')[0];

    for (let i = 0; i < totalDays; i++) {
        const isToday = currentDay.toISOString().split('T')[0] === todayStr;
        headerHtml.push(`
            <div class="day-tick ${isToday ? 'today' : ''}">
                <span style="font-weight:bold; font-size:0.75rem;">${currentDay.getDate()} ${nombresMeses[currentDay.getMonth()]}</span>
                <span style="font-size:0.6rem;">${nombresDias[currentDay.getDay()]}</span>
            </div>
        `);
        currentDay.setDate(currentDay.getDate() + 1);
    }
    document.getElementById('timelineHeader').innerHTML = headerHtml.join('');

    let sidebarHtml = '';
    let rowsHtml = '';

    const formatDateStr = (dateObj) => {
        if(!dateObj) return 'N/A';
        const d = dateObj.getDate().toString().padStart(2, '0');
        const mo = nombresMeses[dateObj.getMonth()];
        const h = dateObj.getHours().toString().padStart(2, '0');
        const mi = dateObj.getMinutes().toString().padStart(2, '0');
        return `${d} ${mo} - ${h}:${mi} hrs`;
    };

    lotesProcesados.forEach(lote => {
        let badgeLote = lote.estado === 'COMPLETADO' ? 'success' : 'info';
        const avisoSinEtapas = lote.sinEtapas
            ? ` <span class="aviso-sin-etapas" title="La receta no tiene etapas ISA-88: se muestra una fila por actividad. Defínelas en el Diseñador de procesos.">⚠️</span>`
            : '';
        sidebarHtml += `<div class="lote-group-header">📦 ${lote.identificador_lote}${avisoSinEtapas} <span style="font-size:0.6rem; color:var(--${badgeLote}); border:1px solid; border-radius:3px; padding:1px 3px; float:right;">${lote.estado}</span></div>`;
        rowsHtml += `<div class="lote-row-spacer"></div>`;

        lote.etapasSummary.forEach(etapa => {
            const icono = { etapa: '📁', actividad: '▸', 'sin-etapa': '⚠️' }[etapa.tipo];
            sidebarHtml += `<div class="etapa-label etapa-label--${etapa.tipo}" title="${etapa.nombre}">${icono} ${etapa.nombre}</div>`;

            let barsHtml = '';
            const getStyle = (startD, endD) => {
                const leftPx = ((startD - globalMinDate) / MS_PER_HOUR) * PIXELS_PER_HOUR;
                const widthPx = ((endD - startD) / MS_PER_HOUR) * PIXELS_PER_HOUR;
                return `left: ${Math.max(0, leftPx)}px; width: ${Math.max(2, widthPx)}px;`;
            };

            // [MODIFICADO] Inyectamos el nombre de la etapa dentro de la barra Baseline
            if (etapa.baseStart && etapa.baseEnd) {
                barsHtml += `
                    <div class="gantt-bar bar-baseline" 
                        style="${getStyle(etapa.baseStart, etapa.baseEnd)}"
                        data-nombre="${etapa.nombre}"
                        data-tipo="baseline"
                        data-inicio="${formatDateStr(etapa.baseStart)}"
                        data-fin="${formatDateStr(etapa.baseEnd)}"
                    >
                        <span class="bar-label">${etapa.nombre}</span>
                    </div>
                `;
            }

            if (etapa.progStart && etapa.progEnd) {
                let colorClass = 'bar-forecast';
                if (etapa.delayHours > 0) colorClass += ' delayed';
                else if (lote.estado === 'EN_PROGRESO') colorClass += ' in-progress';

                let innerTextHtml = `<span class="bar-label">${etapa.nombre}</span>`;
                if (etapa.delayHours > 0) {
                    innerTextHtml += `<span class="bar-delay-badge">⚠️ +${etapa.delayHours.toFixed(1)}h</span>`;
                }

                barsHtml += `
                    <div class="gantt-bar ${colorClass}" 
                        style="${getStyle(etapa.progStart, etapa.progEnd)}"
                        data-nombre="${etapa.nombre}"
                        data-tipo="forecast"
                        data-inicio="${formatDateStr(etapa.progStart)}"
                        data-fin="${formatDateStr(etapa.progEnd)}"
                        data-delay="${etapa.delayHours.toFixed(1)}"
                    >
                        ${innerTextHtml}
                    </div>
                `;
            }

            rowsHtml += `<div class="etapa-row">${barsHtml}</div>`;
        });
    });

    document.getElementById('sidebarContent').innerHTML = sidebarHtml;
    document.getElementById('timelineRows').innerHTML = rowsHtml;

    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('ganttScrollArea').style.display = 'flex';

    activarTooltipsInteractivos();

    setTimeout(() => {
        const msDesdeInicioHastaHoy = new Date() - globalMinDate;
        const pxHastaHoy = (msDesdeInicioHastaHoy / MS_PER_HOUR) * PIXELS_PER_HOUR;
        const scrollArea = document.getElementById('ganttScrollArea');
        scrollArea.scrollLeft = Math.max(0, pxHastaHoy - 300);
    }, 100);
}

// LÓGICA DEL CUSTOM TOOLTIP
function activarTooltipsInteractivos() {
    const tooltip = document.getElementById('customGanttTooltip');
    const barras = document.querySelectorAll('.gantt-bar');

    barras.forEach(bar => {
        bar.addEventListener('mouseenter', (e) => {
            const tipoAttr = bar.getAttribute('data-tipo');
            const nombre = bar.getAttribute('data-nombre');
            const inicio = bar.getAttribute('data-inicio');
            const fin = bar.getAttribute('data-fin');
            const delay = parseFloat(bar.getAttribute('data-delay') || 0);

            const subtitulo = tipoAttr === 'baseline' ? '📅 Línea Base (Plan Original Inmutable)' : '🚀 Forecast (Ejecución y Reprogramación)';
            let delayHtml = '';

            if (tipoAttr === 'forecast' && delay > 0) {
                delayHtml = `<p>Retraso Identificado: <span class="delay-val">+${delay}h</span></p>`;
            } else if (tipoAttr === 'forecast' && delay === 0) {
                delayHtml = `<p>Estado de Tiempo: <span style="color:var(--success)">En tiempo</span></p>`;
            }

            tooltip.innerHTML = `
                <h4>📁 ${nombre}</h4>
                <span class="badge-tipo">${subtitulo}</span>
                <p>Inicio GxP: <span class="val">${inicio}</span></p>
                <p>Fin GxP: <span class="val">${fin}</span></p>
                ${delayHtml}
            `;

            tooltip.style.display = 'block';
            setTimeout(() => tooltip.style.opacity = '1', 10);
        });

        bar.addEventListener('mousemove', (e) => {
            let leftPos = e.clientX + 15;
            let topPos = e.clientY + 15;

            const tooltipRect = tooltip.getBoundingClientRect();
            if (leftPos + tooltipRect.width > window.innerWidth) {
                leftPos = e.clientX - tooltipRect.width - 15;
            }
            if (topPos + tooltipRect.height > window.innerHeight) {
                topPos = e.clientY - tooltipRect.height - 15;
            }

            tooltip.style.left = leftPos + 'px';
            tooltip.style.top = topPos + 'px';
        });

        bar.addEventListener('mouseleave', () => {
            tooltip.style.opacity = '0';
            setTimeout(() => { 
                if (tooltip.style.opacity === '0') tooltip.style.display = 'none'; 
            }, 100); 
        });
    });
}

window.onload = () => {
    document.getElementById('chkGanttTodos')?.addEventListener('change', initGantt);
    initGantt();
};
