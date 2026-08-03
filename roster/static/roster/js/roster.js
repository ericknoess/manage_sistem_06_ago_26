// roster/static/roster/js/roster.js

document.addEventListener('DOMContentLoaded', () => {
    const today = new Date();
    let currentYear = today.getFullYear();
    let currentMonth = today.getMonth() + 1; // 1-12

    const tbody = document.getElementById('tbodyRoster');
    const currentDateDisplay = document.getElementById('currentDateDisplay');
    const prevMonthBtn = document.getElementById('prevMonth');
    const nextMonthBtn = document.getElementById('nextMonth');

    const modalCuadrilla = document.getElementById('modalCuadrilla');
    const modalOperador = document.getElementById('modalOperador');
    const btnOpenCuadrillaModal = document.getElementById('btnOpenCuadrillaModal');
    const btnOpenOperadorModal = document.getElementById('btnOpenOperadorModal');
    const btnCloseCuadrillaModal = document.getElementById('btnCloseCuadrillaModal');
    const btnCloseOperadorModal = document.getElementById('btnCloseOperadorModal');
    const formCuadrilla = document.getElementById('formCuadrilla');
    const formOperador = document.getElementById('formOperador');
    const operadorCuadrillaSelect = document.getElementById('operadorCuadrillaSelect');

    const TURNOS_CICLO = ['--', 'M', 'T', 'N', 'TR', 'OFF', 'INC', 'F'];
    let cachedCuadrillas = [];

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

    async function loadRosterData(year, month) {
        try {
            currentDateDisplay.textContent = `${getMonthName(month)} ${year}`;
            tbody.innerHTML = `<tr><td colspan="32" class="p-12 text-center text-slate-500 font-mono animate-pulse">Sincronizando con PostgreSQL...</td></tr>`;

            const response = await fetch(`/api/roster/cuadrillas/?month=${month}&year=${year}`);
            if (!response.ok) throw new Error('Error al conectar con la API de Cuadrillas');
            
            cachedCuadrillas = await response.json();
            renderMatrix(cachedCuadrillas, year, month);
        } catch (error) {
            console.error(error);
            tbody.innerHTML = `<tr><td colspan="32" class="p-12 text-center text-red-400 font-mono">Error crítico al cargar datos operacionales.</td></tr>`;
        }
    }

    function renderMatrix(cuadrillas, year, month) {
        tbody.innerHTML = '';
        const daysInMonth = new Date(year, month, 0).getDate();

        if (cuadrillas.length === 0) {
            tbody.innerHTML = `<tr><td colspan="32" class="p-12 text-center text-slate-500 font-mono">No hay cuadrillas registradas en el sistema.</td></tr>`;
            return;
        }

        cuadrillas.forEach(cuadrilla => {
            const trHeader = document.createElement('tr');
            trHeader.className = 'bg-slate-950 border-t-2 border-cyan-900/50 transition-colors drop-zone shadow-md';
            trHeader.setAttribute('data-cuadrilla-id', cuadrilla.id);
            trHeader.innerHTML = `
                <td colspan="${daysInMonth + 1}" class="p-3 font-bold text-cyan-400 text-xs tracking-wider flex justify-between items-center pointer-events-none">
                    <span>${cuadrilla.nombre} (${cuadrilla.operadores.length} Operadores) - <span class="text-cyan-300 font-normal italic">Arrastra el asa ⠿ o usa el selector 🔄</span></span>
                    <span class="text-[10px] font-mono px-2 py-0.5 bg-cyan-950 border border-cyan-800 rounded text-cyan-300">Área Upstream GxP Ready</span>
                </td>
            `;
            tbody.appendChild(trHeader);

            setupDropZone(trHeader, cuadrilla.id);

            if (cuadrilla.operadores.length === 0) {
                const trEmpty = document.createElement('tr');
                trEmpty.innerHTML = `<td colspan="${daysInMonth + 1}" class="p-4 text-center text-slate-600 italic text-xs">Sin operadores asignados a esta cuadrilla.</td>`;
                tbody.appendChild(trEmpty);
                return;
            }

            cuadrilla.operadores.forEach(operador => {
                const trOp = document.createElement('tr');
                trOp.className = 'border-b border-slate-800 hover:bg-slate-800/30 transition-colors';

                let html = `
                    <td class="p-3 sticky left-0 bg-slate-900 z-10 border-r border-slate-700 text-xs font-medium text-slate-300 w-52 truncate shadow-[2px_0_5px_rgba(0,0,0,0.3)] select-none">
                        <div class="flex items-center justify-between">
                            <span class="truncate" title="${operador.nombre}">${operador.nombre}</span>
                            <div class="flex items-center space-x-1.5">
                                <button type="button" class="text-slate-400 hover:text-cyan-400 p-1 text-[10px] bg-slate-800 rounded border border-slate-700 transition-colors reassign-btn cursor-pointer" title="Seleccionar nueva cuadrilla" data-reassign-id="${operador.id}" data-current-cuadrilla="${cuadrilla.id}">
                                    🔄
                                </button>
                                <span class="text-slate-500 hover:text-cyan-300 text-xs font-mono cursor-grab active:cursor-grabbing p-0.5 rounded hover:bg-slate-800 drag-handle transition-colors"
                                    draggable="true"
                                    data-operador-drag-id="${operador.id}"
                                    title="Arrastra desde aquí para reasignar">
                                    ⠿
                                </span>
                            </div>
                        </div>
                    </td>
                `;

                for (let day = 1; day <= 31; day++) {
                    if (day <= daysInMonth) {
                        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                        const turnoObj = operador.turnos.find(t => t.fecha === dateStr);
                        const codigo = turnoObj ? turnoObj.codigo_turno : '--';
                        const turnoId = turnoObj ? turnoObj.id : '';

                        html += `
                            <td class="p-1 border-r border-slate-800 text-center font-mono text-xs cursor-pointer select-none" 
                                data-operador-id="${operador.id}" 
                                data-fecha="${dateStr}" 
                                data-turno-id="${turnoId}"
                                data-codigo="${codigo}"
                                title="Clic para cambiar turno (${operador.nombre} - ${dateStr})">
                                <div class="w-7 h-7 mx-auto rounded flex items-center justify-center font-bold text-[10px] transition-transform hover:scale-110 ${getBadgeClass(codigo)}">
                                    ${codigo}
                                </div>
                            </td>
                        `;
                    } else {
                        html += `<td class="p-1 border-r border-slate-800 bg-slate-950/20"></td>`;
                    }
                }

                trOp.innerHTML = html;
                tbody.appendChild(trOp);
            });
        });

        attachCellClickEvents();
        attachDragEvents();
        attachReassignDropdowns();
    }

    function attachDragEvents() {
        const dragHandles = tbody.querySelectorAll('.drag-handle');
        dragHandles.forEach(handle => {
            handle.addEventListener('dragstart', (e) => {
                const operadorId = handle.getAttribute('data-operador-drag-id');
                e.dataTransfer.setData('text/plain', operadorId);
                const tr = handle.closest('tr');
                if (tr) tr.classList.add('opacity-50', 'bg-cyan-950/50');
            });

            handle.addEventListener('dragend', (e) => {
                const tr = handle.closest('tr');
                if (tr) tr.classList.remove('opacity-50', 'bg-cyan-950/50');
            });
        });
    }

    function setupDropZone(trHeader, targetCuadrillaId) {
        trHeader.addEventListener('dragover', (e) => {
            e.preventDefault();
            trHeader.classList.add('bg-cyan-900/60', 'border-cyan-400');
        });

        trHeader.addEventListener('dragleave', () => {
            trHeader.classList.remove('bg-cyan-900/60', 'border-cyan-400');
        });

        trHeader.addEventListener('drop', async (e) => {
            e.preventDefault();
            trHeader.classList.remove('bg-cyan-900/60', 'border-cyan-400');

            const operadorId = e.dataTransfer.getData('text/plain');
            if (!operadorId) return;

            await updateOperadorCuadrilla(operadorId, targetCuadrillaId);
        });
    }

    function attachReassignDropdowns() {
        const buttons = tbody.querySelectorAll('.reassign-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                
                // Remover cualquier dropdown existente
                document.querySelectorAll('.reassign-dropdown').forEach(el => el.remove());

                const operadorId = btn.getAttribute('data-reassign-id');
                const currentCuadrillaId = parseInt(btn.getAttribute('data-current-cuadrilla'));
                const rect = btn.getBoundingClientRect();

                const dropdown = document.createElement('div');
                dropdown.className = 'reassign-dropdown fixed bg-slate-900 border border-cyan-800 rounded-xl shadow-2xl p-3 z-50 text-xs font-sans';
                dropdown.style.width = '250px';
                dropdown.style.visibility = 'hidden'; // Oculto temporalmente para medición precisa de altura

                dropdown.innerHTML = `
                    <div class="font-bold text-cyan-400 mb-2 border-b border-slate-800 pb-1 flex justify-between items-center">
                        <span>Seleccionar Cuadrilla</span>
                        <span class="text-[9px] text-slate-500 font-mono">GxP Secure</span>
                    </div>
                    <div class="space-y-1 max-h-48 overflow-y-auto">
                        ${cachedCuadrillas.map(c => `
                            <button type="button" class="w-full text-left px-2 py-1.5 rounded transition-colors flex items-center justify-between ${c.id === currentCuadrillaId ? 'bg-cyan-950/60 text-cyan-300 font-semibold cursor-default' : 'hover:bg-slate-800 text-slate-300'}"
                                ${c.id === currentCuadrillaId ? 'disabled' : `data-target-cuadrilla="${c.id}"`}>
                                <span class="truncate">${c.identificador} - ${c.nombre}</span>
                                ${c.id === currentCuadrillaId ? '<span class="text-[9px] text-cyan-500 font-mono">Actual</span>' : ''}
                            </button>
                        `).join('')}
                    </div>
                `;

                document.body.appendChild(dropdown);

                // Cálculo inteligente de colisión con los bordes de la pantalla
                const dropdownHeight = dropdown.offsetHeight;
                const dropdownWidth = 250;
                const margin = 6;

                // 1. Evaluación Eje Vertical (Top/Bottom)
                let topPos = rect.bottom + margin;
                if (topPos + dropdownHeight > window.innerHeight) {
                    // Si sobrepasa el límite inferior de la pantalla, se despliega HACIA ARRIBA
                    topPos = Math.max(10, rect.top - dropdownHeight - margin);
                }

                // 2. Evaluación Eje Horizontal (Left/Right)
                let leftPos = rect.left;
                if (leftPos + dropdownWidth > window.innerWidth) {
                    leftPos = window.innerWidth - dropdownWidth - margin;
                }
                leftPos = Math.max(10, leftPos); // Evitar desbordamiento en el borde izquierdo

                dropdown.style.top = `${topPos}px`;
                dropdown.style.left = `${leftPos}px`;
                dropdown.style.visibility = 'visible'; // Renderizar tras la calibración de coordenadas

                dropdown.querySelectorAll('button[data-target-cuadrilla]').forEach(optionBtn => {
                    optionBtn.addEventListener('click', async (ev) => {
                        ev.stopPropagation();
                        const targetId = optionBtn.getAttribute('data-target-cuadrilla');
                        dropdown.remove();
                        await updateOperadorCuadrilla(operadorId, targetId);
                    });
                });

                const closeDropdown = (ev) => {
                    if (!dropdown.contains(ev.target) && ev.target !== btn) {
                        dropdown.remove();
                        document.removeEventListener('click', closeDropdown);
                    }
                };
                setTimeout(() => document.addEventListener('click', closeDropdown), 10);
            });
        });
    }

    async function updateOperadorCuadrilla(operadorId, targetCuadrillaId) {
        try {
            const response = await fetch(`/api/roster/operadores/${operadorId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ cuadrilla: parseInt(targetCuadrillaId) })
            });

            if (response.ok) {
                loadRosterData(currentYear, currentMonth);
            } else {
                const errData = await response.json();
                alert("Error al reasignar operador: " + JSON.stringify(errData));
            }
        } catch (error) {
            console.error("Error de red en reasignación:", error);
            alert("Error de red al reasignar el operador.");
        }
    }

    function getBadgeClass(codigo) {
        if (codigo === 'M') return 'bg-amber-500/20 text-amber-300 border border-amber-500/40';
        if (codigo === 'T') return 'bg-blue-500/20 text-blue-300 border border-blue-500/40';
        if (codigo === 'N') return 'bg-purple-500/20 text-purple-300 border border-purple-500/40';
        if (codigo === 'TR') return 'bg-teal-500/20 text-teal-300 border border-teal-500/40';
        if (codigo === 'OFF') return 'bg-slate-800 text-slate-400 border border-slate-700';
        if (codigo === 'INC') return 'bg-orange-500/20 text-orange-300 border border-orange-500/40';
        if (codigo === 'F') return 'bg-red-500/20 text-red-300 border border-red-500/40';
        return 'text-slate-600 bg-slate-950/40 border border-slate-800';
    }

    function attachCellClickEvents() {
        const cells = tbody.querySelectorAll('td[data-fecha]');
        cells.forEach(cell => {
            cell.addEventListener('click', async () => {
                const operadorId = cell.getAttribute('data-operador-id');
                const fecha = cell.getAttribute('data-fecha');
                let turnoId = cell.getAttribute('data-turno-id');
                const codigoActual = cell.getAttribute('data-codigo');

                const currentIndex = TURNOS_CICLO.indexOf(codigoActual);
                const nextIndex = (currentIndex + 1) % TURNOS_CICLO.length;
                const nuevoCodigo = TURNOS_CICLO[nextIndex];

                try {
                    let response;
                    let responseData = null;

                    if (turnoId && turnoId !== "null" && turnoId !== "") {
                        if (nuevoCodigo === '--') {
                            response = await fetch(`/api/roster/turnos/${turnoId}/`, {
                                method: 'DELETE',
                                headers: { 'X-CSRFToken': getCookie('csrftoken') }
                            });
                        } else {
                            response = await fetch(`/api/roster/turnos/${turnoId}/`, {
                                method: 'PATCH',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'X-CSRFToken': getCookie('csrftoken')
                                },
                                body: JSON.stringify({ codigo_turno: nuevoCodigo })
                            });
                            if (response.ok) responseData = await response.json();
                        }
                    } else {
                        if (nuevoCodigo !== '--') {
                            response = await fetch('/api/roster/turnos/', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'X-CSRFToken': getCookie('csrftoken')
                                },
                                body: JSON.stringify({
                                    fecha: fecha,
                                    codigo_turno: nuevoCodigo,
                                    operador: parseInt(operadorId)
                                })
                            });
                            if (response.ok) responseData = await response.json();
                        } else {
                            return;
                        }
                    }

                    if (response && !response.ok) {
                        const errData = await response.json();
                        console.error("Error devuelto por el servidor:", errData);
                        alert("Error al actualizar turno: " + JSON.stringify(errData));
                        return;
                    }

                    cell.setAttribute('data-codigo', nuevoCodigo);
                    if (nuevoCodigo === '--') {
                        cell.setAttribute('data-turno-id', '');
                    } else if (responseData && responseData.id) {
                        cell.setAttribute('data-turno-id', responseData.id);
                    }

                    const badgeDiv = cell.querySelector('div');
                    badgeDiv.className = `w-7 h-7 mx-auto rounded flex items-center justify-center font-bold text-[10px] transition-transform hover:scale-110 ${getBadgeClass(nuevoCodigo)}`;
                    badgeDiv.textContent = nuevoCodigo;

                } catch (error) {
                    console.error("Excepción al actualizar turno:", error);
                    alert("Error de red al actualizar el turno operacional.");
                }
            });
        });
    }

    function getMonthName(m) {
        const names = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
        return names[m - 1];
    }

    function openModal(modal) {
        modal.classList.remove('hidden');
        gsap.fromTo(modal.querySelector('div > div'), 
            { scale: 0.9, opacity: 0 }, 
            { scale: 1, opacity: 1, duration: 0.3, ease: "power2.out" }
        );
    }

    function closeModal(modal) {
        gsap.to(modal.querySelector('div > div'), {
            scale: 0.9, opacity: 0, duration: 0.2, ease: "power2.in",
            onComplete: () => modal.classList.add('hidden')
        });
    }

    async function populateCuadrillasSelect() {
        try {
            const response = await fetch('/api/roster/cuadrillas/');
            const cuadrillas = await response.json();
            operadorCuadrillaSelect.innerHTML = '';
            cuadrillas.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = `${c.identificador} - ${c.nombre}`;
                operadorCuadrillaSelect.appendChild(opt);
            });
        } catch (e) {
            console.error("No se pudieron cargar las cuadrillas para el selector", e);
        }
    }

    btnOpenCuadrillaModal.addEventListener('click', () => openModal(modalCuadrilla));
    btnCloseCuadrillaModal.addEventListener('click', () => closeModal(modalCuadrilla));
    
    btnOpenOperadorModal.addEventListener('click', async () => {
        await populateCuadrillasSelect();
        openModal(modalOperador);
    });
    btnCloseOperadorModal.addEventListener('click', () => closeModal(modalOperador));

    formCuadrilla.addEventListener('submit', async (e) => {
        e.preventDefault();
        const identificador = document.getElementById('cuadrillaIdentificador').value.toUpperCase();
        const nombre = document.getElementById('cuadrillaNombre').value;

        try {
            const res = await fetch('/api/roster/cuadrillas/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ identificador, nombre, activa: true })
            });

            if (res.ok) {
                closeModal(modalCuadrilla);
                formCuadrilla.reset();
                loadRosterData(currentYear, currentMonth);
            } else {
                const err = await res.json();
                alert("Error al crear cuadrilla: " + JSON.stringify(err));
            }
        } catch (error) {
            console.error(error);
            alert("Error de red al crear cuadrilla.");
        }
    });

    formOperador.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nombre = document.getElementById('operadorNombre').value;
        const cuadrillaId = operadorCuadrillaSelect.value;

        try {
            const res = await fetch('/api/roster/operadores/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ nombre, cuadrilla: cuadrillaId, activo: true })
            });

            if (res.ok) {
                closeModal(modalOperador);
                formOperador.reset();
                loadRosterData(currentYear, currentMonth);
            } else {
                const err = await res.json();
                alert("Error al crear operador: " + JSON.stringify(err));
            }
        } catch (error) {
            console.error(error);
            alert("Error de red al crear operador.");
        }
    });

    prevMonthBtn.addEventListener('click', () => {
        currentMonth--;
        if (currentMonth < 1) { currentMonth = 12; currentYear--; }
        loadRosterData(currentYear, currentMonth);
    });

    nextMonthBtn.addEventListener('click', () => {
        currentMonth++;
        if (currentMonth > 12) { currentMonth = 1; currentYear++; }
        loadRosterData(currentYear, currentMonth);
    });

    loadRosterData(currentYear, currentMonth);
});