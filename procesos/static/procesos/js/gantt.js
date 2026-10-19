// procesos/static/procesos/js/gantt.js

const PIXELS_PER_HOUR = 3;
const MS_PER_HOUR = 60 * 60 * 1000;

let globalMinDate = null;
let globalMaxDate = null;

async function initGantt() {
    try {
        const response = await fetch('/api/lotes/');
        if (!response.ok) throw new Error("Error fetching data");
        const lotes = await response.json();

        procesarYRenderizar(lotes);
    } catch (error) {
        document.getElementById('loadingState').innerHTML = `<span style="color:var(--danger)">Error al cargar datos: ${error.message}</span>`;
    }
}

function procesarYRenderizar(lotes) {
    const lotesProcesados = lotes.map(lote => {
        const etapasDict = {};

        lote.fases.forEach(f => {
            const eNombre = f.etapa_nombre || 'Sin Etapa';
            const eOrden = f.etapa_orden || 999;
            if (!etapasDict[eNombre]) {
                etapasDict[eNombre] = { nombre: eNombre, orden: eOrden, fases: [] };
            }
            etapasDict[eNombre].fases.push(f);
        });

        const etapasArray = Object.values(etapasDict).map(etapa => {
            let baseStart = null, baseEnd = null;
            let progStart = null, progEnd = null;

            etapa.fases.forEach(f => {
                if (f.inicio_programado && f.fin_programado) {
                    let start = new Date(f.inicio_programado);
                    let end = new Date(f.fin_programado);

                    if (!progStart || start < progStart) progStart = start;
                    if (!progEnd || end > progEnd) progEnd = end;
                }

                if (f.inicio_base_cpm && f.fin_base_cpm) {
                    let start = new Date(f.inicio_base_cpm);
                    let end = new Date(f.fin_base_cpm);

                    if (!baseStart || start < baseStart) baseStart = start;
                    if (!baseEnd || end > baseEnd) baseEnd = end;
                }
            });

            if (baseStart && (!globalMinDate || baseStart < globalMinDate)) globalMinDate = new Date(baseStart);
            if (progStart && (!globalMinDate || progStart < globalMinDate)) globalMinDate = new Date(progStart);
            if (baseEnd && (!globalMaxDate || baseEnd > globalMaxDate)) globalMaxDate = new Date(baseEnd);
            if (progEnd && (!globalMaxDate || progEnd > globalMaxDate)) globalMaxDate = new Date(progEnd);

            let delayHours = 0;
            if (baseEnd && progEnd) delayHours = (progEnd - baseEnd) / MS_PER_HOUR;

            return { ...etapa, baseStart, baseEnd, progStart, progEnd, delayHours };
        });

        etapasArray.sort((a, b) => a.orden - b.orden);
        return { ...lote, etapasSummary: etapasArray };
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
        sidebarHtml += `<div class="lote-group-header">📦 ${lote.identificador_lote} <span style="font-size:0.6rem; color:var(--${badgeLote}); border:1px solid; border-radius:3px; padding:1px 3px; float:right;">${lote.estado}</span></div>`;
        rowsHtml += `<div class="lote-row-spacer"></div>`;

        lote.etapasSummary.forEach(etapa => {
            sidebarHtml += `<div class="etapa-label" title="${etapa.nombre}">📁 ${etapa.nombre}</div>`;

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

window.onload = initGantt;
