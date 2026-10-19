// roster/static/roster/js/bisemanal.js

const diasSemanaNombres = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

function obtenerLunesActual(pivotDate = new Date()) {
    let d = new Date(pivotDate);
    let day = d.getDay();
    let diff = d.getDate() - day + (day === 0 ? -6 : 1);
    return new Date(d.setDate(diff));
}

let fechaLunesPivot = obtenerLunesActual(new Date());

function formatearFechaLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function obtenerRango14DiasDesdeLunes(lunesDate) {
    let start = new Date(lunesDate);
    let days = [];
    for (let i = 0; i < 14; i++) {
        let d = new Date(start);
        d.setDate(start.getDate() + i);
        days.push({
            fechaStr: formatearFechaLocal(d),
            nombreDia: diasSemanaNombres[d.getDay()],
            diaMes: `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
        });
    }
    return {
        start: days[0].fechaStr,
        end: days[days.length - 1].fechaStr,
        days: days
    };
}

async function fetchAllPages(url) {
    let results = [];
    let currentUrl = url;

    while (currentUrl) {
        const response = await fetch(currentUrl, { cache: 'no-store' });
        if (!response.ok) throw new Error(`Error HTTP: ${response.status}`);
        const data = await response.json();

        if (data && data.results && Array.isArray(data.results)) {
            results = results.concat(data.results);
            currentUrl = data.next;
        } else if (Array.isArray(data)) {
            results = results.concat(data);
            break; 
        } else {
            break;
        }
    }
    return results;
}

// Función para renderizar la leyenda dinámica
function renderizarLeyenda(tiposTurno) {
    const contenedor = document.getElementById('leyendaGxpContainer');
    if (!tiposTurno || tiposTurno.length === 0) {
        contenedor.innerHTML = '<span style="font-style: italic;">No hay tipos de turno activos configurados.</span>';
        return;
    }

    let html = '';
    tiposTurno.filter(t => t.activo && t.codigo).forEach(t => {
        html += `
            <div class="leyenda-item">
                <div class="leyenda-color-box" style="background-color: ${t.color_fondo}; border: 1px solid ${t.color_texto};"></div>
                <span style="color: var(--text); font-weight: bold;">${t.codigo}:</span>
                <span>${t.nombre}</span>
            </div>
        `;
    });
    contenedor.innerHTML = html;
}

async function cargarVistaBisemanal() {
    const rango = obtenerRango14DiasDesdeLunes(fechaLunesPivot);

    try {
        const [cuadrillas, tiposTurno] = await Promise.all([
            fetchAllPages('/api/cuadrillas/'),
            fetchAllPages('/api/tipos-turno/')
        ]);

        // 1. Pintamos la leyenda dinámica
        renderizarLeyenda(tiposTurno);

        // 2. Pintamos la tabla de turnos
        renderizarTabla(rango.days, cuadrillas);
    } catch (error) {
        console.error("Error al cargar la matriz:", error);
        document.getElementById('tableBody').innerHTML = `<tr><td colspan="15" style="text-align:center; color: #ef4444; padding: 2rem;">Error al cargar datos: ${error.message}</td></tr>`;
    }
}

function renderizarTabla(daysObjArray, cuadrillas) {
    const headerRow = document.getElementById('tableHeaders');
    const tbody = document.getElementById('tableBody');

    let headerHTML = `<th class="operator-col" style="min-width: 180px;">Colaborador</th>`;
    daysObjArray.forEach(d => {
        headerHTML += `<th style="text-align: center;"><div style="font-size: 0.65rem; color: var(--accent);">${d.nombreDia}</div><div>${d.diaMes}</div></th>`;
    });
    headerRow.innerHTML = headerHTML;

    if (!cuadrillas || cuadrillas.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${daysObjArray.length + 1}" style="text-align:center; color: var(--muted); padding: 2rem;">No hay cuadrillas registradas.</td></tr>`;
        return;
    }

    let bodyHTML = '';
    cuadrillas.forEach(cuadrilla => {
        bodyHTML += `<tr class="cuadrilla-header-row">`;
        bodyHTML += `<td colspan="${daysObjArray.length + 1}">📁 Cuadrilla: ${cuadrilla.nombre || cuadrilla.identificador}</td>`;
        bodyHTML += `</tr>`;

        const operadores = cuadrilla.operadores || [];
        if (operadores.length === 0) {
            bodyHTML += `<tr><td colspan="${daysObjArray.length + 1}" style="color: var(--muted); padding-left: 20px;">Sin operadores asignados a esta cuadrilla.</td></tr>`;
        } else {
            operadores.forEach(op => {
                bodyHTML += `<tr class="hover:bg-slate-800/30 transition-colors">`;
                bodyHTML += `<td class="operator-col" style="padding-left: 15px;">`;
                bodyHTML += `<span class="operator-name">👤 ${op.nombre}</span>`;
                bodyHTML += `</td>`;

                daysObjArray.forEach(d => {
                    const turnoObj = op.turnos ? op.turnos.find(t => t.fecha === d.fechaStr) : null;
                    const codigoTurno = turnoObj ? (turnoObj.codigo_turno || turnoObj.codigo) : '';

                    if (turnoObj && codigoTurno) {
                        let bg = turnoObj.color_fondo || '#3b82f6';
                        let fg = turnoObj.color_texto || '#ffffff';

                        // APLICAMOS EL ESTILO DIRECTAMENTE A LA CELDA <td>
                        bodyHTML += `<td style="text-align:center; cursor: default; background-color: ${bg}; color: ${fg}; font-weight: bold; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.1);">
                                        ${codigoTurno}
                                     </td>`;
                    } else {
                        bodyHTML += `<td style="text-align:center; color: #475569; font-weight: bold; background-color: transparent;">-</td>`;
                    }
                });

                bodyHTML += `</tr>`;
            });
        }
    });

    tbody.innerHTML = bodyHTML;
}

function cambiarBloque(dias) {
    fechaLunesPivot.setDate(fechaLunesPivot.getDate() + dias);
    cargarVistaBisemanal();
}

function irSemanaActual() {
    fechaLunesPivot = obtenerLunesActual(new Date());
    cargarVistaBisemanal();
}

cargarVistaBisemanal();
