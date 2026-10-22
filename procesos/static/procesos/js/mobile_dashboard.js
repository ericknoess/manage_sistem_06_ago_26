// procesos/static/procesos/js/mobile_dashboard.js

// Utilidad: Leer token CSRF

let session = JSON.parse(localStorage.getItem('ebr_session')) || null;

document.addEventListener('DOMContentLoaded', async () => {
    if (session && session.operador_id && await terminalVigente()) {
        mostrarDashboard();
    } else {
        mostrarLogin();
    }
});

// La tablet guarda al operador en el navegador, pero quien firma es la sesión del servidor. Si en este navegador
// se inició sesión web (o la sesión venció), la terminal ya no es del operador: se pide volver a ingresar.
async function terminalVigente() {
    try {
        const res = await fetch('/api/mobile/sesion/');
        const datos = await res.json();
        if (datos.operador_id === session.operador_id) return true;
        terminalCerrada(datos.usuario_web
            ? `En este navegador se inició sesión web como «${datos.usuario_web}» y eso cerró la terminal. Vuelve a ingresar con tu PIN.`
            : 'Tu sesión en la terminal terminó. Vuelve a ingresar con tu número de empleado y PIN.', false);
        return false;
    } catch (e) {
        return true;  // sin red: se deja ver; el servidor valida al firmar
    }
}

function terminalCerrada(mensaje, avisar = true) {
    localStorage.removeItem('ebr_session');
    session = null;
    document.getElementById('taskListContainer').innerHTML = '';
    document.getElementById('surtirContainer').innerHTML = '';
    document.getElementById('recibirContainer').innerHTML = '';
    const aviso = document.getElementById('avisoTerminal');
    aviso.textContent = '🔒 ' + mensaje;
    aviso.hidden = false;
    mostrarLogin();
    if (avisar) alert('🔒 ' + mensaje);
}

function mostrarLoader(texto = "Procesando...") {
    document.getElementById('loaderText').innerText = texto;
    document.getElementById('globalLoader').style.display = 'flex';
}

function ocultarLoader() {
    document.getElementById('globalLoader').style.display = 'none';
}

function mostrarLogin() {
    document.getElementById('dashboardView').style.display = 'none';
    const loginView = document.getElementById('loginView');
    loginView.style.display = 'flex';
    gsap.fromTo(loginView, {opacity: 0, scale: 0.95}, {opacity: 1, scale: 1, duration: 0.4, ease: "back.out(1.2)"});
}

function mostrarDashboard() {
    document.getElementById('loginView').style.display = 'none';
    document.getElementById('uiOpNombre').innerText = session.nombre;
    document.getElementById('uiOpCuadrilla').innerText = `${session.codigo_empleado} | ${session.rol}`;

    const dashView = document.getElementById('dashboardView');
    dashView.style.display = 'flex';
    gsap.fromTo(dashView, {opacity: 0}, {opacity: 1, duration: 0.3});

    prepararPestanasSurtido();
    cargarTareasPendientes();
}

// --- AUTHENTICATION ---
async function handleLogin(e) {
    e.preventDefault();
    const codigo = document.getElementById('inputCodigo').value.trim();
    const pin = document.getElementById('inputPin').value.trim();

    mostrarLoader("Autenticando firma...");

    try {
        const res = await fetch('/api/mobile/login/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ codigo_empleado: codigo, pin_acceso: pin })
        });

        const data = await res.json();

        if (res.ok) {
            document.getElementById('avisoTerminal').hidden = true;
            session = data;
            localStorage.setItem('ebr_session', JSON.stringify(session));
            document.getElementById('loginForm').reset();
            ocultarLoader();
            mostrarDashboard();
        } else {
            ocultarLoader();
            alert("Acceso Denegado: " + (data.error || "Credenciales inválidas."));
        }
    } catch (err) {
        ocultarLoader();
        alert("Error de conexión con el servidor.");
    }
}

function handleLogout() {
    // Cierra también la sesión del operador en el servidor
    fetch('/api/mobile/logout/', { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } }).catch(() => {});
    localStorage.removeItem('ebr_session');
    session = null;
    document.getElementById('taskListContainer').innerHTML = '';
    document.getElementById('surtirContainer').innerHTML = '';
    document.getElementById('recibirContainer').innerHTML = '';
    mostrarLogin();
}

// --- CARGA DE DATOS ---
async function cargarTareasPendientes() {
    if (!session) return;
    mostrarLoader("Obteniendo plan de trabajo...");

    try {
        const res = await fetch(`/api/mobile/${session.operador_id}/tareas-pendientes/`);
        if (res.ok) {
            const data = await res.json();
            renderizarTareas(data.tareas_pendientes, data.sobrantes);
        } else {
            alert("Error al cargar tareas. Inicie sesión nuevamente.");
            handleLogout();
        }
    } catch (err) {
        alert("Error de red al consultar tareas.");
    } finally {
        ocultarLoader();
    }
}

// --- AGRUPACIÓN POR DÍA ---
// "Hoy" incluye lo atrasado y lo que está en progreso, para que no quede escondido en un día plegado.
// Los demás días se muestran plegados; lo que el operador abre se conserva al recargar la lista.
const gruposAbiertos = new Set(['hoy']);
const DIAS_SEMANA = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

function inicioDelDiaLocal(fecha) {
    const d = new Date(fecha);
    d.setHours(0, 0, 0, 0);
    return d;
}

function claveGrupoTarea(t) {
    if (!t.inicio_programado || t.estado === 'EN_PROGRESO') return 'hoy';
    const dias = Math.round((inicioDelDiaLocal(t.inicio_programado) - inicioDelDiaLocal(new Date())) / 86400000);
    if (dias <= 0) return 'hoy';
    const d = inicioDelDiaLocal(t.inicio_programado);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function tituloGrupo(clave) {
    if (clave === 'hoy') return 'Hoy';
    const [a, m, d] = clave.split('-').map(Number);
    const fecha = new Date(a, m - 1, d);
    const dias = Math.round((fecha - inicioDelDiaLocal(new Date())) / 86400000);
    const etiqueta = fecha.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
    return dias === 1 ? `Mañana · ${etiqueta}` : `${DIAS_SEMANA[fecha.getDay()]} · ${etiqueta}`;
}

function agruparTareasPorDia(tareas) {
    const grupos = new Map();
    tareas.forEach(t => {
        const clave = claveGrupoTarea(t);
        if (!grupos.has(clave)) grupos.set(clave, { clave, titulo: tituloGrupo(clave), tareas: [] });
        grupos.get(clave).tareas.push(t);
    });
    // "Hoy" primero; luego los días en orden
    return [...grupos.values()].sort((x, y) => (x.clave === 'hoy' ? -1 : y.clave === 'hoy' ? 1 : x.clave.localeCompare(y.clave)));
}

function renderizarTareas(tareas, sobrantes = []) {
    window.tareasActuales = tareas;  // para mostrar la tarea en el modal de firma
    const container = document.getElementById('taskListContainer');
    container.innerHTML = htmlSobrantes(sobrantes);

    if (!tareas || tareas.length === 0) {
        container.innerHTML += `
            <div class="empty-state">
                <div style="font-size: 3rem; margin-bottom: 1rem;">🎉</div>
                <h3>¡Excelente trabajo!</h3>
                <p>No tienes tareas operativas pendientes para tu turno actual en este momento.</p>
            </div>
        `;
        return;
    }

    const grupos = agruparTareasPorDia(tareas);
    if (!grupos.some(g => g.clave === 'hoy')) {
        grupos.unshift({ clave: 'hoy', titulo: 'Hoy', tareas: [] });
    }
    const cuerpos = {};
    grupos.forEach(g => {
        const grupo = document.createElement('details');
        grupo.className = 'grupo-dia';
        grupo.open = gruposAbiertos.has(g.clave);
        grupo.addEventListener('toggle', () => {
            if (grupo.open) gruposAbiertos.add(g.clave); else gruposAbiertos.delete(g.clave);
        });
        const enProgreso = g.tareas.filter(t => t.estado === 'EN_PROGRESO').length;
        grupo.innerHTML = `
            <summary class="grupo-dia__titulo">
                <span>${escaparTexto(g.titulo)}</span>
                <span class="grupo-dia__conteo">${g.tareas.length} tarea${g.tareas.length === 1 ? '' : 's'}${enProgreso ? ` · ${enProgreso} en progreso` : ''}</span>
            </summary>
            <div class="grupo-dia__tareas">${g.tareas.length ? '' : '<div class="grupo-dia__vacio">Sin tareas para hoy.</div>'}</div>`;
        container.appendChild(grupo);
        cuerpos[g.clave] = grupo.querySelector('.grupo-dia__tareas');
    });

    tareas.forEach(t => {
        const card = document.createElement('div');
        card.className = `task-card ${t.estado === 'EN_PROGRESO' ? 'en-progreso' : ''}`;
        card.id = `task-card-${t.fase_id}`;

        let badgeClass = t.estado === 'EN_PROGRESO' ? 'badge-progreso' : 'badge-pendiente';
        let badgeText = t.estado.replace('_', ' ');

        let accionHtml = '';
        if (t.estado === 'PENDIENTE') {
            // La tarea solo se inicia cuando su dependencia se cumple y ya entró en su ventana de tolerancia
            if (t.bloqueo) {
                accionHtml = `<div class="task-aviso task-aviso--espera">🔒 ${escaparTexto(t.bloqueo)}</div>
                    <button class="btn-massive btn-primary" disabled>▶ INICIAR ACTIVIDAD</button>`;
            } else if (t.desviacion === 'ADELANTO') {
                accionHtml = `<div class="task-aviso task-aviso--espera">⏳ Disponible a partir de las ${formatearMomento(t.disponible_desde)}</div>
                    <button class="btn-massive btn-primary" disabled>▶ INICIAR ACTIVIDAD</button>`;
            } else {
                const avisoRetraso = t.desviacion === 'RETRASO'
                    ? `<div class="task-aviso task-aviso--retraso">⏰ Fuera de horario: al iniciarla deberás escribir el motivo.</div>` : '';
                accionHtml = `${avisoRetraso}<button class="btn-massive btn-primary" onclick="cambiarEstadoFase(${t.fase_id}, 'EN_PROGRESO')">▶ INICIAR ACTIVIDAD</button>`;
            }
        } else if (t.estado === 'EN_PROGRESO') {
            accionHtml = `<button class="btn-massive btn-success" onclick="cambiarEstadoFase(${t.fase_id}, 'COMPLETADA')">✔ MARCAR COMPLETADA</button>`;
        }

        const tFecha = t.inicio_programado ? new Date(t.inicio_programado).toLocaleDateString('es-MX') : 'N/A';
        const tRango = formatearRangoFase(t.inicio_programado, t.fin_programado);

        card.innerHTML = `
            <div class="task-header">
                <div style="flex: 1; padding-right: 1rem;">
                    <h4 class="task-title">[${t.identificador_paso}] ${t.tarea_nombre}</h4>
                    <div class="task-lote">Lote: ${t.lote_identificador} | ${t.proceso_nombre}</div>
                </div>
                <span class="badge ${badgeClass}">${badgeText}</span>
            </div>

            <div class="task-details">
                <div class="detail-item"><strong>📅 Programado</strong><span>${tFecha}</span></div>
                <div class="detail-item"><strong>⏱ Forecast</strong><span>${tRango} hrs</span></div>
                <div class="detail-item"><strong>👤 Rol Requerido</strong><span>${t.rol_asignado}</span></div>
                <div class="detail-item"><strong>⚙️ Tipo</strong><span>${t.tipo_operacion}</span></div>
                ${t.equipos && t.equipos.length ? `<div class="detail-item detail-item--ancho"><strong>🏗️ Equipo</strong><span>${t.equipos.map(escaparTexto).join(', ')}</span></div>` : ''}
            </div>

            ${htmlMaterialesTarea(t)}
            ${accionHtml}
        `;
        cuerpos[claveGrupoTarea(t)].appendChild(card);
    });

    // Animación de cascada suave (Stagger), solo en los días abiertos
    gsap.from(".grupo-dia[open] .task-card", {
        y: 30, 
        opacity: 0, 
        duration: 0.4, 
        stagger: 0.1, 
        ease: "power2.out",
        clearProps: "all"
    });
}

// --- ACTUALIZACIÓN TRANSACCIONAL eBR (firmada con PIN) ---
const SIGNIFICADOS_FIRMA = {
    EN_PROGRESO: 'Inicio la ejecución de la fase',
    COMPLETADA: 'Ejecución completada y verificada',
};
let firmaPendiente = null;

function cambiarEstadoFase(faseId, nuevoEstado) {
    const tarea = (window.tareasActuales || []).find(t => t.fase_id === faseId);
    const significados = (session && session.firmas) || {};
    firmaPendiente = { faseId, nuevoEstado };
    document.getElementById('firmaPinTarea').textContent = tarea
        ? `${nuevoEstado === 'EN_PROGRESO' ? '▶ Iniciar' : '✔ Completar'}: [${tarea.identificador_paso}] ${tarea.tarea_nombre} · Lote ${tarea.lote_identificador}`
        : '';
    document.getElementById('firmaPinSignificado').textContent = `«${significados['FASE_' + nuevoEstado] || SIGNIFICADOS_FIRMA[nuevoEstado]}»`;
    document.getElementById('firmaPinFirmante').textContent = session ? `${session.nombre} (${session.codigo_empleado})` : '';
    document.getElementById('firmaPinError').hidden = true;
    document.getElementById('firmaPinInput').value = '';
    document.getElementById('firmaPinMotivo').value = '';
    if (nuevoEstado === 'EN_PROGRESO' && tarea && tarea.desviacion === 'RETRASO') pedirMotivoPin(tarea.mensaje);
    else ocultarMotivoPin();
    document.getElementById('modalFirmaPin').hidden = false;
    (motivoPinVisible() ? document.getElementById('firmaPinMotivo') : document.getElementById('firmaPinInput')).focus();
}

function pedirMotivoPin(aviso) {
    document.getElementById('firmaPinAviso').textContent = aviso;
    document.getElementById('firmaPinDesviacion').hidden = false;
    document.getElementById('firmaPinMotivo').required = true;
    document.getElementById('firmaPinMotivo').minLength = 10;
}

function ocultarMotivoPin() {
    document.getElementById('firmaPinDesviacion').hidden = true;
    document.getElementById('firmaPinMotivo').required = false;
}

function motivoPinVisible() {
    return !document.getElementById('firmaPinDesviacion').hidden;
}

function formatearMomento(iso) {
    if (!iso) return '--';
    return new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function escaparTexto(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function cerrarFirmaPin() {
    document.getElementById('modalFirmaPin').hidden = true;
    firmaPendiente = null;
}

function mostrarErrorFirmaPin(texto) {
    const caja = document.getElementById('firmaPinError');
    caja.textContent = texto;
    caja.hidden = false;
    document.getElementById('firmaPinInput').value = '';
    document.getElementById('firmaPinInput').focus();
}

async function enviarFirmaPin(evento) {
    evento.preventDefault();
    if (!firmaPendiente) return;
    const { faseId, nuevoEstado } = firmaPendiente;
    const boton = document.getElementById('firmaPinBoton');
    boton.disabled = true;

    try {
        const res = await fetch(`/api/fases-lote/${faseId}/cambiar-estado/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({
                estado: nuevoEstado, firma_pin: document.getElementById('firmaPinInput').value,
                ...(motivoPinVisible() ? { motivo_desviacion: document.getElementById('firmaPinMotivo').value.trim() } : {}),
            })
        });
        let data = {};
        try { data = await res.json(); } catch (e) { /* sin cuerpo */ }

        if (res.ok) {
            cerrarFirmaPin();
            const card = document.getElementById(`task-card-${faseId}`);
            gsap.to(card, {
                x: -50, opacity: 0, height: 0, marginBottom: 0, padding: 0, duration: 0.3,
                onComplete: () => {
                    if (data.advertencia_materiales) alert("⚠️ Iniciaste con material incompleto:\n\n" + data.advertencia_materiales.join("\n"));
                    if (data.mensaje_cascada) alert("✨ Inteligencia Operativa MES:\n\n" + data.mensaje_cascada);
                    cargarTareasPendientes();
                }
            });
        } else if (['FIRMA_INVALIDA', 'FIRMA_REQUERIDA'].includes(data.codigo)) {
            mostrarErrorFirmaPin(data.error);
        } else if (data.codigo === 'MOTIVO_REQUERIDO') {
            pedirMotivoPin(data.error);
            document.getElementById('firmaPinMotivo').focus();
        } else if (['FUERA_DE_VENTANA', 'DEPENDENCIA_PENDIENTE'].includes(data.codigo)) {
            cerrarFirmaPin();
            alert("⏳ " + data.error);
            cargarTareasPendientes();
        } else if (data.codigo === 'TERMINAL_CERRADA') {
            cerrarFirmaPin();
            terminalCerrada(data.error);
        } else if (data.codigo === 'CUENTA_BLOQUEADA') {
            cerrarFirmaPin();
            alert("🔒 " + data.error);
            handleLogout();
        } else if (res.status === 401 || (res.status === 403 && !data.error)) {
            // Sesión vencida o la tarea no es suya: el servidor lo explica en "detail"
            cerrarFirmaPin();
            alert("🔒 " + (data.detail || "Tu sesión expiró. Vuelve a ingresar."));
            if (!data.detail || data.detail.includes('sesión')) handleLogout();
        } else {
            cerrarFirmaPin();
            alert("⚠️ Bloqueo GxP:\n\n" + (data.error || "No se puede procesar la solicitud."));
        }
    } catch (err) {
        mostrarErrorFirmaPin("Error de red. Verifique la conexión WiFi de la Tablet.");
    } finally {
        boton.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('formFirmaPin').addEventListener('submit', enviarFirmaPin);
});
