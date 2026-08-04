/**
 * user_management.js
 * Módulo de Frontend para la gestión y alta de usuarios del sistema GxP.
 * Utiliza Vanilla JavaScript, Fetch API y GSAP para animaciones fluidas.
 */

document.addEventListener('DOMContentLoaded', () => {
    const userForm = document.getElementById('user-registration-form');
    
    if (!userForm) return;

    userForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = {
            username: document.getElementById('reg-username').value.trim(),
            email: document.getElementById('reg-email').value.trim(),
            password: document.getElementById('reg-password').value,
            password_confirm: document.getElementById('reg-password-confirm').value,
            operador_id: document.getElementById('reg-operador-id').value ? parseInt(document.getElementById('reg-operador-id').value) : null
        };

        const feedbackElement = document.getElementById('form-feedback');

        // Validación local de contraseñas
        if (formData.password !== formData.password_confirm) {
            showFeedback(feedbackElement, 'Las contraseñas no coinciden.', 'error');
            return;
        }

        try {
            // Obtener el token CSRF de las cookies de Django
            const csrftoken = getCookie('csrftoken');

            const response = await fetch('/roster/api/usuarios/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken
                },
                body: JSON.stringify(formData)
            });

            const data = await response.json();

            if (response.ok) {
                showFeedback(feedbackElement, `¡Usuario "${data.username}" creado exitosamente!`, 'success');
                userForm.reset();
                
                // Animación de éxito con GSAP
                if (typeof gsap !== 'undefined') {
                    gsap.fromTo(feedbackElement, { scale: 0.9 }, { scale: 1, duration: 0.3, ease: 'back.out(1.7)' });
                }
            } else {
                // Formatear errores devueltos por el backend
                const errorMsg = formatBackendErrors(data);
                showFeedback(feedbackElement, errorMsg, 'error');
            }
        } catch (error) {
            console.error('Error de red:', error);
            showFeedback(feedbackElement, 'Error de conexión con el servidor.', 'error');
        }
    });
});

/**
 * Muestra mensajes de retroalimentación visual al operador.
 */
function showFeedback(element, message, type) {
    if (!element) return;
    element.textContent = message;
    element.className = `feedback-message ${type}`;
    element.style.display = 'block';

    if (typeof gsap !== 'undefined') {
        gsap.fromTo(element, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.4 });
    }
}

/**
 * Traduce los errores estructurados de DRF a un texto legible.
 */
function formatBackendErrors(errors) {
    let messages = [];
    for (const [key, value] of Object.entries(errors)) {
        if (Array.isArray(value)) {
            messages.push(`${key}: ${value.join(' ')}`);
        } else {
            messages.push(`${key}: ${value}`);
        }
    }
    return messages.join(' | ');
}

/**
 * Utilidad para extraer la cookie CSRF requerida por Django.
 */
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