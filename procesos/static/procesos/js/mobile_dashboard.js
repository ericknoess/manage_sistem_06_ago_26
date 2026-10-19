// procesos/static/procesos/js/mobile_dashboard.js

// Utilidad: Leer token CSRF

let session = JSON.parse(localStorage.getItem('ebr_session')) || null;

document.addEventListener('DOMContentLoaded', () => {
    if (session && session.operador_id) {
        mostrarDashboard();
    } else {
        mostrarLogin();
    }
});

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
    localStorage.removeItem('ebr_session');
    session = null;
    document.getElementById('taskListContainer').innerHTML = '';
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
            renderizarTareas(data.tareas_pendientes);
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

function renderizarTareas(tareas) {
    const container = document.getElementById('taskListContainer');
    container.innerHTML = '';

    if (!tareas || tareas.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div style="font-size: 3rem; margin-bottom: 1rem;">🎉</div>
                <h3>¡Excelente trabajo!</h3>
                <p>No tienes tareas operativas pendientes para tu turno actual en este momento.</p>
            </div>
        `;
        return;
    }

    tareas.forEach(t => {
        const card = document.createElement('div');
        card.className = `task-card ${t.estado === 'EN_PROGRESO' ? 'en-progreso' : ''}`;
        card.id = `task-card-${t.fase_id}`;

        let badgeClass = t.estado === 'EN_PROGRESO' ? 'badge-progreso' : 'badge-pendiente';
        let badgeText = t.estado.replace('_', ' ');

        let accionHtml = '';
        if (t.estado === 'PENDIENTE') {
            accionHtml = `<button class="btn-massive btn-primary" onclick="cambiarEstadoFase(${t.fase_id}, 'EN_PROGRESO')">▶ INICIAR ACTIVIDAD</button>`;
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
            </div>

            ${accionHtml}
        `;
        container.appendChild(card);
    });

    // Animación de cascada suave (Stagger)
    gsap.from(".task-card", {
        y: 30, 
        opacity: 0, 
        duration: 0.4, 
        stagger: 0.1, 
        ease: "power2.out",
        clearProps: "all"
    });
}

// --- ACTUALIZACIÓN TRANSACCIONAL eBR ---
async function cambiarEstadoFase(faseId, nuevoEstado) {
    let accionTxt = nuevoEstado === 'EN_PROGRESO' ? 'iniciar' : 'completar';
    if (!confirm(`¿Firma electrónicamente que desea ${accionTxt} esta actividad bajo las normas GxP?`)) return;

    mostrarLoader("Registrando firma electrónica...");

    try {
        const res = await fetch(`/api/fases-lote/${faseId}/cambiar-estado/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ estado: nuevoEstado })
        });

        if (res.ok) {
            const data = await res.json();
            const card = document.getElementById(`task-card-${faseId}`);

            // Animación de éxito
            gsap.to(card, {
                x: -50, opacity: 0, height: 0, marginBottom: 0, padding: 0, duration: 0.3, 
                onComplete: () => {
                    // [NUEVO] Si el backend inyectó el mensaje del Efecto Cascada, avisamos al operador
                    if (data.mensaje_cascada) {
                        alert("✨ Inteligencia Operativa MES:\n\n" + data.mensaje_cascada);
                    }
                    cargarTareasPendientes();
                } 
            });
        } else {
            const errorData = await res.json();
            alert("⚠️ Bloqueo GxP:\n\n" + (errorData.error || "No se puede procesar la solicitud."));
            ocultarLoader();
        }
    } catch (err) {
        alert("Error de red. Verifique la conexión WiFi de la Tablet.");
        ocultarLoader();
    }
}
