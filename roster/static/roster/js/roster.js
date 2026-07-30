// --- ESTADO GLOBAL ---
let dataApp = {
    cuadrillas: [],
    operadores: []
};

// --- ESTADO DE NAVEGACIÓN ---
let currentDate = new Date(); 

// --- INICIALIZACIÓN ---
document.addEventListener('DOMContentLoaded', () => {
    actualizarVista();
});

// --- HELPER: GESTIÓN DE COLORES ---
function aplicarColorTurno(celda, codigo) {
    // 1. Limpiar clases previas
    celda.classList.remove('turno-M', 'turno-T', 'turno-N', 'turno-TR', 'turno-OFF', 'turno-INC', 'turno-F');
    
    // 2. Si hay código válido, aplicar clase
    if (codigo && codigo !== '--') {
        celda.classList.add(`turno-${codigo.toUpperCase()}`);
    }
}

// --- LÓGICA DE CARGA ---
async function cargarDatos(month, year) {
    try {
        const response = await fetch(`/roster/api/cuadrillas/?month=${month}&year=${year}`);
        if (!response.ok) throw new Error('Error al conectar con el servidor');
        
        const data = await response.json();
        dataApp.cuadrillas = data;
        
        dataApp.operadores = [];
        data.forEach(c => {
            c.operadores.forEach(op => {
                dataApp.operadores.push({
                    ...op,
                    cuadrilla: c.identificador
                });
            });
        });
        
        renderizarTabla();
    } catch (error) {
        console.error("Error crítico de carga:", error);
    }
}

// --- RENDERIZADO ---
function renderizarTabla() {
    const tbody = document.getElementById('tbodyRoster');
    tbody.innerHTML = '';
    
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth() + 1; 

    dataApp.cuadrillas.forEach(c => {
        let opsEnCuadrilla = dataApp.operadores.filter(o => o.cuadrilla === c.identificador);

        const trHead = document.createElement('tr');
        trHead.className = `row-cuadrilla cuadrilla-${c.identificador}`;
        trHead.innerHTML = `<td class="col-fixed">${c.nombre} (${opsEnCuadrilla.length} Op) <span class="tag-status st-ok">Cargada</span></td><td colspan="31"></td>`;
        tbody.appendChild(trHead);

        opsEnCuadrilla.forEach(op => {
            const trOp = document.createElement('tr');
            trOp.className = `cuadrilla-${c.identificador} draggable-row`;
            
            let tdFija = document.createElement('td');
            tdFija.className = 'col-fixed';
            tdFija.innerHTML = `<span><span class="drag-handle">⣿</span>${op.nombre}</span>`;
            trOp.appendChild(tdFija);
            
            for(let dia = 1; dia <= 31; dia++) {
                const fechaStr = `${year}-${month.toString().padStart(2, '0')}-${dia.toString().padStart(2, '0')}`;
                const turnoObj = op.turnos.find(t => t.fecha === fechaStr);
                
                let tdTurno = document.createElement('td');
                tdTurno.className = `cell-turno`;
                tdTurno.textContent = turnoObj ? turnoObj.codigo_turno : '--';
                
                // Aplicar estilo inicial
                if(turnoObj) aplicarColorTurno(tdTurno, turnoObj.codigo_turno);
                
                tdTurno.setAttribute('data-fecha', fechaStr);
                tdTurno.setAttribute('data-operador-id', op.id);
                if (turnoObj) {
                    tdTurno.setAttribute('data-id', turnoObj.id);
                }
                
                trOp.appendChild(tdTurno);
            }
            tbody.appendChild(trOp);
        });
    });
}

// --- EVENTOS INTERACCIÓN (CLICK) ---
document.getElementById('tbodyRoster').addEventListener('click', async (event) => {
    if (!event.target.classList.contains('cell-turno')) return;
    
    event.stopPropagation();
    const celda = event.target;
    
    const menuExistente = document.querySelector('.turno-selector');
    if (menuExistente) menuExistente.remove();

    const codigos = ['M', 'T', 'N', 'TR', 'OFF', 'INC', 'F'];
    const menu = document.createElement('div');
    menu.className = 'turno-selector';
    
    menu.style.top = `${event.pageY + 10}px`;
    menu.style.left = `${event.pageX + 10}px`;

    codigos.forEach(codigo => {
        const btn = document.createElement('button');
        btn.textContent = codigo;
        btn.onclick = () => procesarCambio(celda, codigo);
        menu.appendChild(btn);
    });

    document.body.appendChild(menu);

    const cerrarMenu = () => {
        const menuActual = document.querySelector('.turno-selector');
        if (menuActual) {
            menuActual.remove();
            document.removeEventListener('click', cerrarMenu);
        }
    };

    setTimeout(() => {
        document.addEventListener('click', cerrarMenu);
    }, 0);
});

async function procesarCambio(celda, nuevoValor) {
    const turnoId = celda.getAttribute('data-id');
    const fecha = celda.getAttribute('data-fecha');
    const operadorId = celda.getAttribute('data-operador-id');
    const valorActual = celda.textContent === '--' ? '' : celda.textContent;

    if (nuevoValor === valorActual) {
        document.querySelector('.turno-selector').remove();
        return;
    }

    try {
        let response;
        if (turnoId) {
            response = await fetch(`/roster/api/turnos/${turnoId}/`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken')},
                body: JSON.stringify({ codigo_turno: nuevoValor })
            });
        } else {
            response = await fetch(`/roster/api/turnos/`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken')},
                body: JSON.stringify({ codigo_turno: nuevoValor, fecha: fecha, operador: operadorId })
            });
        }

        if (response.ok) {
            const data = await response.json();
            celda.textContent = nuevoValor;
            // Aplicar estilo tras cambio
            aplicarColorTurno(celda, nuevoValor);
            
            if (data.id) celda.setAttribute('data-id', data.id);
            const menu = document.querySelector('.turno-selector');
            if(menu) menu.remove();
        } else {
            const errData = await response.json();
            alert("Error del servidor: " + JSON.stringify(errData));
        }
    } catch (err) {
        console.error("Error en operación:", err);
    }
}

// --- NAVEGACIÓN ---
document.getElementById('prevMonth').addEventListener('click', () => {
    currentDate.setMonth(currentDate.getMonth() - 1);
    actualizarVista();
});

document.getElementById('nextMonth').addEventListener('click', () => {
    currentDate.setMonth(currentDate.getMonth() + 1);
    actualizarVista();
});

function actualizarVista() {
    const month = currentDate.getMonth() + 1;
    const year = currentDate.getFullYear();
    
    const monthNames = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
    document.getElementById('currentDateDisplay').textContent = `${monthNames[currentDate.getMonth()]} ${year}`;
    
    cargarDatos(month, year);
}

// --- UTILS ---
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}