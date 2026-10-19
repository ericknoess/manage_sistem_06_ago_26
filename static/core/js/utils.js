// static/core/js/utils.js — utilidades compartidas por todas las pantallas

// Lee una cookie por nombre (se usa para enviar el token CSRF en las peticiones a la API).
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

// Formatea la ventana de una fase ("08:00 - 14:00", o "08:00 - 14:00 (+3d)" si termina otro día).
// Recibe fecha-hora ISO (ej. inicio_programado / fin_programado de la API).
function formatearRangoFase(inicioIso, finIso) {
    if (!inicioIso) return '--:-- - --:--';
    const hora = (d) => d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: false });
    const inicio = new Date(inicioIso);
    if (!finIso) return `${hora(inicio)} - --:--`;
    const fin = new Date(finIso);
    const dias = Math.round((new Date(fin.toDateString()) - new Date(inicio.toDateString())) / 86400000);
    return `${hora(inicio)} - ${hora(fin)}${dias > 0 ? ` (+${dias}d)` : ''}`;
}
