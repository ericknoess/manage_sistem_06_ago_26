// roster/static/roster/js/roster.js

document.addEventListener('DOMContentLoaded', () => {
    // --- ESTADO GLOBAL DE LA APLICACIÓN ---
    let fechaActual = new Date();
    let currentYear = fechaActual.getFullYear();
    let currentMonth = fechaActual.getMonth() + 1; // 1-12
    let secuenciasCache = [];

    const mesesNombres = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ];

    // --- ELEMENTOS DOM PRINCIPALES ---
    const tbodyRoster = document.getElementById('tbodyRoster');
    const currentDateDisplay = document.getElementById('currentDateDisplay');
    const btnPrevMonth = document.getElementById('prevMonth');
    const btnNextMonth = document.getElementById('nextMonth');

    // Modales y Botones
    const btnOpenCuadrilla = document.getElementById('btnOpenCuadrillaModal');
    const modalCuadrilla = document.getElementById('modalCuadrilla');
    const btnCloseCuadrilla = document.getElementById('btnCloseCuadrillaModal');
    const formCuadrilla = document.getElementById('formCuadrilla');

    const btnOpenOperador = document.getElementById('btnOpenOperadorModal');
    const modalOperador = document.getElementById('modalOperador');
    const btnCloseOperador = document.getElementById('btnCloseOperadorModal');
    const formOperador = document.getElementById('formOperador');
    const operadorCuadrillaSelect = document.getElementById('operadorCuadrillaSelect');
    const operadorFeedback = document.getElementById('operador-form-feedback');

    const btnOpenCargaMasiva = document.getElementById('btnOpenCargaMasivaModal');
    const modalCargaMasiva = document.getElementById('modalCargaMasiva');
    const btnCloseCargaMasiva1 = document.getElementById('btnCloseCargaMasivaModal');
    const btnCloseCargaMasiva2 = document.getElementById('btnCloseCargaMasivaModal2');
    const formCargaMasiva = document.getElementById('formCargaMasiva');

    const cmTipoAsignacion = document.getElementById('cmTipoAsignacion');
    const cmContenedorSelector = document.getElementById('cmContenedorSelector');
    const cmLabelSelector = document.getElementById('cmLabelSelector');
    const cmSelectReferencia = document.getElementById('cmSelectReferencia');
    const cmInfoCuadrilla = document.getElementById('cmInfoCuadrilla');
    const cmSelectSecuencia = document.getElementById('cmSelectSecuencia');
    const cmVisualizadorSecuencia = document.getElementById('cmVisualizadorSecuencia');
    const cmPatronVisualSteps = document.getElementById('cmPatronVisualSteps');
    const btnPrevisualizarCarga = document.getElementById('btnPrevisualizarCarga');
    const btnConfirmarCarga = document.getElementById('btnConfirmarCarga');
    const cmContenedorPrevisualizacion = document.getElementById('cmContenedorPrevisualizacion');
    const cmResumenInfo = document.getElementById('cmResumenInfo');
    const cmPreviewHeadRow = document.getElementById('cmPreviewHeadRow');
    const cmPreviewBody = document.getElementById('cmPreviewBody');
    const cmFeedback = document.getElementById('cmFeedback');

    // --- FUNCIONES DE SOPORTE Y CARGA ---

    function actualizarDisplayFecha() {
        if (currentDateDisplay) {
            currentDateDisplay.textContent = `${mesesNombres[currentMonth - 1]} ${currentYear}`;
        }
    }

    async function loadRosterData() {
        try {
            tbodyRoster.innerHTML = `<tr><td colspan="32" class="p-12 text-center text-cyan-400 font-mono animate-pulse">Sincronizando matriz operacional (${mesesNombres[currentMonth - 1]} ${currentYear})...</td></tr>`;
            
            const response = await fetch(`/api/cuadrillas/?month=${currentMonth}&year=${currentYear}`);
            if (!response.ok) throw new Error('Error al conectar con el servidor para obtener la cuadrilla.');
            
            const cuadrillas = await response.json();
            renderRosterGrid(cuadrillas);
        } catch (error) {
            tbodyRoster.innerHTML = `<tr><td colspan="32" class="p-12 text-center text-red-400 font-mono">Error crítico al cargar datos: ${error.message}</td></tr>`;
        }
    }
    window.loadRosterData = loadRosterData;

    function renderRosterGrid(cuadrillas) {
        if (!cuadrillas || cuadrillas.length === 0) {
            tbodyRoster.innerHTML = `<tr><td colspan="32" class="p-12 text-center text-slate-500 font-mono">No se encontraron cuadrillas ni operadores registrados. Utilice los botones superiores para comenzar.</td></tr>`;
            return;
        }

        let html = '';
        const diasEnMes = new Date(currentYear, currentMonth, 0).getDate();

        cuadrillas.forEach(cuadrilla => {
            html += `
                <tr class="bg-slate-950/80 border-b border-slate-700 font-mono text-xs">
                    <td colspan="32" class="p-2.5 text-cyan-400 font-bold tracking-wide flex items-center justify-between">
                        <span>CUADRILLA [${cuadrilla.identificador}]: ${cuadrilla.nombre}</span>
                        <span class="text-[10px] text-slate-400 font-normal">Operadores: ${cuadrilla.operadores ? cuadrilla.operadores.length : 0}</span>
                    </td>
                </tr>
            `;

            if (!cuadrilla.operadores || cuadrilla.operadores.length === 0) {
                html += `
                    <tr class="border-b border-slate-800/50">
                        <td class="p-3 sticky left-0 bg-slate-900/90 text-xs text-slate-500 font-mono italic shadow-[2px_0_5px_rgba(0,0,0,0.3)]">
                            (Sin operadores activos)
                        </td>
                        <td colspan="31" class="p-3 text-center text-xs text-slate-600 font-mono">--</td>
                    </tr>
                `;
                return;
            }

            cuadrilla.operadores.forEach(op => {
                html += `<tr class="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">`;
                
                html += `
                    <td class="p-2.5 sticky left-0 bg-slate-900 z-10 border-r border-slate-700 shadow-[2px_0_5px_rgba(0,0,0,0.3)]">
                        <div class="flex items-center gap-2">
                            ${op.foto ? `<img src="${op.foto}" class="w-7 h-7 rounded-full object-cover border border-slate-600">` : `<div class="w-7 h-7 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-[10px] font-bold text-slate-300">${op.nombre.substring(0,2).toUpperCase()}</div>`}
                            <div class="overflow-hidden">
                                <p class="text-xs font-bold text-slate-200 truncate" title="${op.nombre}">${op.nombre}</p>
                                <p class="text-[10px] font-mono text-cyan-400">${op.codigo_empleado || 'S/C'} | <span class="text-slate-400">${op.nivel_expertiz}</span></p>
                            </div>
                        </div>
                    </td>
                `;

                for (let dia = 1; dia <= 31; dia++) {
                    if (dia <= diasEnMes) {
                        const fechaStr = `${currentYear}-${String(currentMonth).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
                        const turnoObj = op.turnos ? op.turnos.find(t => t.fecha === fechaStr) : null;
                        const codigoTurno = turnoObj ? turnoObj.codigo_turno : '';
                        const cssClase = obtenerEstiloCeldaTurno(codigoTurno);

                        html += `
                            <td class="p-1 border-r border-slate-800/80 text-center font-mono text-[11px] h-10 w-8 min-w-[32px] cursor-pointer hover:bg-cyan-500/10 transition-colors"
                                data-operador-id="${op.id}"
                                data-fecha="${fechaStr}"
                                data-turno-actual="${codigoTurno}"
                                title="Clic para cambiar turno (${fechaStr}): ${codigoTurno || 'Libre'}">
                                <div class="w-full h-full rounded flex items-center justify-center font-bold ${cssClase}">
                                    ${codigoTurno}
                                </div>
                            </td>
                        `;
                    } else {
                        html += `<td class="p-1 border-r border-slate-800/30 bg-slate-950/40 text-center text-slate-700 font-mono text-[10px]">-</td>`;
                    }
                }

                html += `</tr>`;
            });
        });

        tbodyRoster.innerHTML = html;
    }

    function obtenerEstiloCeldaTurno(codigo) {
        switch (codigo) {
            case 'M': return 'bg-amber-500/20 border border-amber-500 text-amber-300';
            case 'T': return 'bg-blue-500/20 border border-blue-500 text-blue-300';
            case 'N': return 'bg-purple-500/20 border border-purple-500 text-purple-300';
            case 'TR': return 'bg-teal-500/20 border border-teal-500 text-teal-300';
            case 'OFF': return 'bg-slate-800 border border-slate-700 text-slate-400';
            case 'INC': return 'bg-orange-500/20 border border-orange-500 text-orange-300';
            case 'F': return 'bg-red-500/20 border border-red-500 text-red-300';
            default: return 'bg-slate-900/40 text-slate-600';
        }
    }

    // --- CONFIGURACIÓN DE EVENT LISTENERS Y MODALES ---
    function setupEventListeners() {
        // Navegación de meses
        if (btnPrevMonth) {
            btnPrevMonth.addEventListener('click', () => {
                currentMonth--;
                if (currentMonth < 1) {
                    currentMonth = 12;
                    currentYear--;
                }
                actualizarDisplayFecha();
                loadRosterData();
            });
        }

        if (btnNextMonth) {
            btnNextMonth.addEventListener('click', () => {
                currentMonth++;
                if (currentMonth > 12) {
                    currentMonth = 1;
                    currentYear++;
                }
                actualizarDisplayFecha();
                loadRosterData();
            });
        }

        // Cambio manual de turno al hacer clic en una celda de la gradilla (Optimizado sin parpadeos)
        if (tbodyRoster) {
            tbodyRoster.addEventListener('click', async (e) => {
                const td = e.target.closest('td[data-operador-id]');
                if (!td) return;

                const operadorId = td.dataset.operadorId;
                const fecha = td.dataset.fecha;
                const turnoActual = td.dataset.turnoActual || '';

                // Ciclar turnos: '' -> M -> T -> N -> TR -> OFF -> INC -> F -> ''
                const turnosCiclo = ['', 'M', 'T', 'N', 'TR', 'OFF', 'INC', 'F'];
                const currentIndex = turnosCiclo.indexOf(turnoActual);
                const nextIndex = (currentIndex + 1) % turnosCiclo.length;
                const nuevoTurno = turnosCiclo[nextIndex];

                try {
                    const response = await fetch('/api/turnos/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            operador: operadorId,
                            fecha: fecha,
                            codigo_turno: nuevoTurno
                        })
                    });

                    if (!response.ok) throw new Error('Error al actualizar el turno en el servidor.');

                    // ACTUALIZACIÓN QUIRÚRGICA DEL DOM (Sin parpadeos)
                    td.dataset.turnoActual = nuevoTurno;
                    td.title = `Clic para cambiar turno (${fecha}): ${nuevoTurno || 'Libre'}`;
                    
                    const divContenedor = td.querySelector('div');
                    if (divContenedor) {
                        divContenedor.className = `w-full h-full rounded flex items-center justify-center font-bold ${obtenerEstiloCeldaTurno(nuevoTurno)}`;
                        divContenedor.textContent = nuevoTurno;
                    }
                } catch (err) {
                    alert(err.message);
                }
            });
        }

        if (btnOpenCuadrilla) {
            btnOpenCuadrilla.addEventListener('click', () => {
                modalCuadrilla.classList.remove('hidden');
                gsap.fromTo(modalCuadrilla.querySelector('.bg-slate-900'), { scale: 0.9, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: 'power2.out' });
            });
        }
        if (btnCloseCuadrilla) {
            btnCloseCuadrilla.addEventListener('click', () => {
                modalCuadrilla.classList.add('hidden');
                formCuadrilla.reset();
            });
        }
        if (formCuadrilla) {
            formCuadrilla.addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = {
                    identificador: document.getElementById('cuadrillaIdentificador').value.toUpperCase(),
                    nombre: document.getElementById('cuadrillaNombre').value
                };
                try {
                    const res = await fetch('/api/cuadrillas/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                        body: JSON.stringify(formData)
                    });
                    if (!res.ok) throw new Error('No se pudo registrar la cuadrilla.');
                    modalCuadrilla.classList.add('hidden');
                    formCuadrilla.reset();
                    loadRosterData();
                } catch (err) {
                    alert(err.message);
                }
            });
        }

        if (btnOpenOperador) {
            btnOpenOperador.addEventListener('click', async () => {
                modalOperador.classList.remove('hidden');
                gsap.fromTo(modalOperador.querySelector('div.bg-slate-900'), { scale: 0.9, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: 'power2.out' });
                try {
                    const res = await fetch('/api/cuadrillas/');
                    const cuadrillas = await res.json();
                    operadorCuadrillaSelect.innerHTML = '<option value="">-- Seleccione Cuadrilla --</option>';
                    cuadrillas.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = `[${c.identificador}] ${c.nombre}`;
                        operadorCuadrillaSelect.appendChild(opt);
                    });
                } catch (err) {
                    console.error('Error cargando cuadrillas para operador', err);
                }
            });
        }
        if (btnCloseOperador) {
            btnCloseOperador.addEventListener('click', () => {
                modalOperador.classList.add('hidden');
                formOperador.reset();
                operadorFeedback.classList.add('hidden');
            });
        }
        if (formOperador) {
            formOperador.addEventListener('submit', async (e) => {
                e.preventDefault();
                const formDataObj = new FormData(formOperador);
                try {
                    const res = await fetch('/api/operadores/', {
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCookie('csrftoken') },
                        body: formDataObj
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || 'Error al registrar operador.');
                    
                    operadorFeedback.textContent = 'Operador registrado con éxito.';
                    operadorFeedback.className = 'mt-2 p-2 rounded text-xs text-center bg-emerald-900/50 text-emerald-300 border border-emerald-700';
                    operadorFeedback.classList.remove('hidden');
                    
                    setTimeout(() => {
                        modalOperador.classList.add('hidden');
                        formOperador.reset();
                        operadorFeedback.classList.add('hidden');
                        loadRosterData();
                    }, 1000);
                } catch (err) {
                    operadorFeedback.textContent = err.message;
                    operadorFeedback.className = 'mt-2 p-2 rounded text-xs text-center bg-red-900/50 text-red-300 border border-red-700';
                    operadorFeedback.classList.remove('hidden');
                }
            });
        }

        if (btnOpenCargaMasiva) {
            btnOpenCargaMasiva.addEventListener('click', () => {
                modalCargaMasiva.classList.remove('hidden');
                gsap.fromTo(modalCargaMasiva.querySelector('.bg-slate-900'), 
                    { scale: 0.9, opacity: 0 }, 
                    { scale: 1, opacity: 1, duration: 0.3, ease: 'power2.out' }
                );
                cargarSecuenciasDisponibles();
            });
        }

        function cerrarModalCarga() {
            gsap.to(modalCargaMasiva.querySelector('.bg-slate-900'), {
                scale: 0.9, opacity: 0, duration: 0.2, ease: 'power2.in',
                onComplete: () => {
                    modalCargaMasiva.classList.add('hidden');
                    formCargaMasiva.reset();
                    cmContenedorSelector.classList.add('hidden');
                    cmContenedorPrevisualizacion.classList.add('hidden');
                    cmVisualizadorSecuencia.classList.add('hidden');
                    btnConfirmarCarga.classList.add('hidden');
                    btnPrevisualizarCarga.classList.remove('hidden');
                    cmFeedback.classList.add('hidden');
                }
            });
        }

        if (btnCloseCargaMasiva1) btnCloseCargaMasiva1.addEventListener('click', cerrarModalCarga);
        if (btnCloseCargaMasiva2) btnCloseCargaMasiva2.addEventListener('click', cerrarModalCarga);

        async function cargarSecuenciasDisponibles() {
            try {
                const response = await fetch('/api/secuencias/');
                if (!response.ok) throw new Error('Error al obtener las secuencias de rol.');
                const data = await response.json();
                secuenciasCache = data;

                cmSelectSecuencia.innerHTML = '<option value="">-- Seleccione Secuencia --</option>';
                data.filter(s => s.activa).forEach(sec => {
                    const opt = document.createElement('option');
                    opt.value = sec.id;
                    opt.textContent = `${sec.nombre} (${sec.detalles.map(d => `${d.dias}${d.codigo_turno}`).join('-')})`;
                    cmSelectSecuencia.appendChild(opt);
                });
            } catch (error) {
                mostrarFeedbackCarga(error.message, 'error');
            }
        }

        if (cmSelectSecuencia) {
            cmSelectSecuencia.addEventListener('change', (e) => {
                const secId = e.target.value;
                if (!secId) {
                    cmVisualizadorSecuencia.classList.add('hidden');
                    return;
                }
                const secuencia = secuenciasCache.find(s => s.id == secId);
                if (secuencia && secuencia.detalles) {
                    cmPatronVisualSteps.innerHTML = '';
                    secuencia.detalles.forEach(det => {
                        for (let i = 0; i < det.dias; i++) {
                            const badge = document.createElement('span');
                            badge.className = `px-2 py-1 rounded text-[10px] font-bold border ${obtenerEstiloCeldaTurno(det.codigo_turno)}`;
                            badge.textContent = det.codigo_turno;
                            cmPatronVisualSteps.appendChild(badge);
                        }
                    });
                    cmVisualizadorSecuencia.classList.remove('hidden');
                }
            });
        }

        if (cmTipoAsignacion) {
            cmTipoAsignacion.addEventListener('change', async (e) => {
                const tipo = e.target.value;
                cmSelectReferencia.innerHTML = '<option value="">-- Cargando --</option>';
                cmInfoCuadrilla.classList.add('hidden');

                if (!tipo) {
                    cmContenedorSelector.classList.add('hidden');
                    return;
                }

                cmContenedorSelector.classList.remove('hidden');
                if (tipo === 'operador') {
                    cmLabelSelector.textContent = 'Seleccionar Colaborador';
                    try {
                        const res = await fetch('/api/operadores/?activo=true');
                        const operadores = await res.json();
                        cmSelectReferencia.innerHTML = '<option value="">-- Seleccione Colaborador --</option>';
                        operadores.forEach(op => {
                            const opt = document.createElement('option');
                            opt.value = op.id;
                            opt.textContent = `${op.codigo_empleado || 'S/C'} | ${op.nombre} (${op.cuadrilla_identificador || 'Sin Cuadrilla'})`;
                            cmSelectReferencia.appendChild(opt);
                        });
                    } catch (err) {
                        mostrarFeedbackCarga('Error al cargar operadores.', 'error');
                    }
                } else if (tipo === 'cuadrilla') {
                    cmLabelSelector.textContent = 'Seleccionar Cuadrilla';
                    try {
                        const res = await fetch('/api/cuadrillas/');
                        const cuadrillas = await res.json();
                        cmSelectReferencia.innerHTML = '<option value="">-- Seleccione Cuadrilla --</option>';
                        cuadrillas.filter(c => c.activa).forEach(c => {
                            const opt = document.createElement('option');
                            opt.value = c.id;
                            opt.textContent = `${c.identificador} | ${c.nombre} (${c.operadores.length} operadores)`;
                            opt.dataset.numOps = c.operadores.length;
                            cmSelectReferencia.appendChild(opt);
                        });
                    } catch (err) {
                        mostrarFeedbackCarga('Error al cargar cuadrillas.', 'error');
                    }
                }
            });
        }

        if (cmSelectReferencia) {
            cmSelectReferencia.addEventListener('change', (e) => {
                if (cmTipoAsignacion.value === 'cuadrilla') {
                    const selectedOpt = e.target.selectedOptions[0];
                    if (selectedOpt && selectedOpt.dataset.numOps) {
                        cmInfoCuadrilla.textContent = `Se aplicará la secuencia a ${selectedOpt.dataset.numOps} colaboradores activos de esta cuadrilla.`;
                        cmInfoCuadrilla.classList.remove('hidden');
                    } else {
                        cmInfoCuadrilla.classList.add('hidden');
                    }
                } else {
                    cmInfoCuadrilla.classList.add('hidden');
                }
            });
        }

        if (btnPrevisualizarCarga) {
            btnPrevisualizarCarga.addEventListener('click', async () => {
                const payload = {
                    tipo: cmTipoAsignacion.value,
                    id: cmSelectReferencia.value,
                    secuencia_id: cmSelectSecuencia.value,
                    fecha_inicio: document.getElementById('cmFechaInicio').value,
                    fecha_fin: document.getElementById('cmFechaFin').value
                };

                if (!payload.tipo || !payload.id || !payload.secuencia_id || !payload.fecha_inicio || !payload.fecha_fin) {
                    mostrarFeedbackCarga('Por favor complete todos los campos obligatorios antes de previsualizar.', 'error');
                    return;
                }

                try {
                    const response = await fetch('/api/turnos/previsualizar-carga-masiva/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify(payload)
                    });

                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || 'Error al generar la previsualización.');

                    cmResumenInfo.innerHTML = `
                        <div><b>Tipo:</b> ${payload.tipo.toUpperCase()}</div>
                        <div><b>Colaboradores:</b> ${data.total_colaboradores}</div>
                        <div><b>Secuencia:</b> ${data.secuencia_nombre}</div>
                        <div><b>Total Registros:</b> ${data.total_registros}</div>
                    `;

                    if (data.previsualizacion.length > 0) {
                        const sampleTurnos = data.previsualizacion[0].turnos;
                        cmPreviewHeadRow.innerHTML = '<th class="p-2 border-b border-slate-800">Colaborador</th>';
                        sampleTurnos.forEach(t => {
                            cmPreviewHeadRow.innerHTML += `<th class="p-2 border-b border-slate-800 text-center">${t.fecha.split('-').slice(1).join('/')}</th>`;
                        });

                        cmPreviewBody.innerHTML = '';
                        data.previsualizacion.forEach(item => {
                            let rowHtml = `<td class="p-2 border-b border-slate-800 font-bold">${item.operador_nombre}</td>`;
                            item.turnos.forEach(t => {
                                const colorClase = obtenerEstiloCeldaTurno(t.codigo);
                                rowHtml += `<td class="p-2 border-b border-slate-800 text-center"><span class="px-1.5 py-0.5 rounded text-[10px] border ${colorClase}">${t.codigo}</span></td>`;
                            });
                            const tr = document.createElement('tr');
                            tr.innerHTML = rowHtml;
                            cmPreviewBody.appendChild(tr);
                        });
                    }

                    cmContenedorPrevisualizacion.classList.remove('hidden');
                    btnPrevisualizarCarga.classList.add('hidden');
                    btnConfirmarCarga.classList.remove('hidden');
                    mostrarFeedbackCarga('Previsualización generada correctamente. Revise los datos y confirme.', 'success');
                } catch (err) {
                    mostrarFeedbackCarga(err.message, 'error');
                }
            });
        }

        if (formCargaMasiva) {
            formCargaMasiva.addEventListener('submit', async (e) => {
                e.preventDefault();
                const payload = {
                    tipo: cmTipoAsignacion.value,
                    id: cmSelectReferencia.value,
                    secuencia_id: cmSelectSecuencia.value,
                    fecha_inicio: document.getElementById('cmFechaInicio').value,
                    fecha_fin: document.getElementById('cmFechaFin').value,
                    estrategia: document.getElementById('cmEstrategia').value
                };

                try {
                    const response = await fetch('/api/turnos/carga-masiva/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify(payload)
                    });

                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || 'Error en la ejecución de la carga masiva.');

                    mostrarFeedbackCarga(data.mensaje, 'success');
                    setTimeout(() => {
                        cerrarModalCarga();
                        loadRosterData();
                    }, 1500);
                } catch (err) {
                    mostrarFeedbackCarga(err.message, 'error');
                }
            });
        }

        function mostrarFeedbackCarga(mensaje, tipo) {
            cmFeedback.textContent = mensaje;
            cmFeedback.classList.remove('hidden', 'bg-emerald-900/50', 'text-emerald-300', 'bg-red-900/50', 'text-red-300');
            if (tipo === 'success') {
                cmFeedback.classList.add('bg-emerald-900/50', 'text-emerald-300', 'border', 'border-emerald-700');
            } else {
                cmFeedback.classList.add('bg-red-900/50', 'text-red-300', 'border', 'border-red-700');
            }
        }
    }

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

    // --- INICIALIZACIÓN ---
    initRoster();

    function initRoster() {
        actualizarDisplayFecha();
        loadRosterData();
        setupEventListeners();
    }
});