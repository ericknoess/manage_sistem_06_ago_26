// static/core/js/sesion.js — Sesión del usuario en todas las pantallas (excepto /mobile/).
//
// - Muestra quién está conectado, con qué rol, y el botón "Salir".
// - Oculta lo que el rol no permite: cualquier elemento con data-permiso="codigo" (o "a|b" = cualquiera
//   de los dos) se muestra solo si el usuario tiene ese permiso. Funciona también con HTML que las
//   pantallas generan después, así que basta con poner el atributo en el template o en el JS.
// - Agrega el token CSRF a las peticiones que modifican datos y maneja la sesión vencida (401)
//   y las acciones rechazadas por rol (403).
// Ocultar es solo comodidad: la API vuelve a validar cada permiso.

(() => {
    const SESION = { cargada: false, permisos: new Set() };
    window.SESION = SESION;

    window.tienePermiso = (codigos) => String(codigos).split('|').some(c => SESION.permisos.has(c.trim()));

    const leerCookie = (nombre) => {
        const par = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith(nombre + '='));
        return par ? decodeURIComponent(par.slice(nombre.length + 1)) : null;
    };

    const irAlLogin = () => {
        const siguiente = encodeURIComponent(location.pathname + location.search);
        location.href = `/login/?next=${siguiente}`;
    };

    // --- Aviso flotante ---------------------------------------------------------------
    let temporizadorAviso = null;
    function avisar(texto) {
        let caja = document.getElementById('sesionAviso');
        if (!caja) {
            caja = document.createElement('div');
            caja.id = 'sesionAviso';
            caja.className = 'sesion-aviso';
            caja.setAttribute('role', 'alert');
            document.body.appendChild(caja);
        }
        caja.textContent = `🔒 ${texto}`;
        caja.classList.add('visible');
        clearTimeout(temporizadorAviso);
        temporizadorAviso = setTimeout(() => caja.classList.remove('visible'), 6000);
    }
    window.avisarSesion = avisar;

    // --- fetch con CSRF y manejo de 401/403 ---------------------------------------------
    const fetchOriginal = window.fetch.bind(window);
    window.fetch = async (recurso, opciones = {}) => {
        const url = new URL(typeof recurso === 'string' ? recurso : recurso.url, location.href);
        const metodo = (opciones.method || (recurso instanceof Request ? recurso.method : 'GET')).toUpperCase();
        const mismoOrigen = url.origin === location.origin;

        if (mismoOrigen && !['GET', 'HEAD', 'OPTIONS'].includes(metodo)) {
            const headers = new Headers(opciones.headers || (recurso instanceof Request ? recurso.headers : undefined));
            if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', leerCookie('csrftoken') || '');
            opciones = { ...opciones, headers, credentials: opciones.credentials || 'same-origin' };
        }

        const respuesta = await fetchOriginal(recurso, opciones);
        if (mismoOrigen && url.pathname.startsWith('/api/')) {
            if (respuesta.status === 401) {
                irAlLogin();
            } else if (respuesta.status === 403) {
                // Solo los rechazos por rol traen "detail"; las reglas GxP traen "error" y las muestra cada pantalla
                respuesta.clone().json()
                    .then(datos => { if (datos.detail) avisar(datos.detail); })
                    .catch(() => {});
            }
        }
        return respuesta;
    };

    // --- Mostrar u ocultar por permiso -------------------------------------------------
    function aplicarPermisos(raiz) {
        if (!SESION.cargada) return;
        const elementos = [];
        if (raiz.nodeType === 1 && raiz.matches('[data-permiso]')) elementos.push(raiz);
        if (raiz.querySelectorAll) elementos.push(...raiz.querySelectorAll('[data-permiso]'));
        elementos.forEach(el => el.classList.toggle('permitido', tienePermiso(el.dataset.permiso)));
    }

    new MutationObserver(cambios => {
        cambios.forEach(c => {
            if (c.type === 'attributes') aplicarPermisos(c.target);
            c.addedNodes.forEach(nodo => aplicarPermisos(nodo));
        });
    }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-permiso'] });

    // --- Chip de usuario ----------------------------------------------------------------
    function escapar(texto) {
        const div = document.createElement('div');
        div.textContent = texto ?? '';
        return div.innerHTML;
    }

    function pintarChip(datos) {
        const roles = datos.roles.length ? datos.roles.join(', ') : 'Sin rol asignado';
        const chip = document.createElement('div');
        chip.className = 'sesion-chip';
        chip.innerHTML = `
            <span class="sesion-chip__usuario" title="${escapar(datos.usuario)}">👤 ${escapar(datos.nombre)}</span>
            <span class="sesion-chip__rol">${escapar(roles)}</span>
            <form method="post" action="/logout/" class="sesion-chip__salir">
                <input type="hidden" name="csrfmiddlewaretoken" value="${escapar(leerCookie('csrftoken') || '')}">
                <button type="submit" title="Cerrar sesión">Salir</button>
            </form>`;

        // Lugar reservado en la pantalla (inicio) o, si no hay, junto al botón "Menú principal"
        const destino = document.querySelector('[data-sesion]');
        if (destino) {
            destino.appendChild(chip);
            return;
        }
        const botonInicio = document.querySelector('.btn-inicio');
        if (!botonInicio) {
            chip.classList.add('sesion-chip--flotante');
            document.body.appendChild(chip);
            return;
        }
        const fila = document.createElement('div');
        fila.className = 'sesion-fila';
        botonInicio.replaceWith(fila);
        fila.append(botonInicio, chip);
    }

    async function cargarSesion() {
        try {
            const respuesta = await fetchOriginal('/api/sesion/', { credentials: 'same-origin' });
            if (respuesta.status === 401 || respuesta.status === 403) return irAlLogin();
            if (!respuesta.ok) return;
            const datos = await respuesta.json();
            SESION.usuario = datos.usuario;
            SESION.nombre = datos.nombre;
            SESION.roles = datos.roles;
            SESION.permisos = new Set(datos.permisos);
            SESION.cargada = true;
            pintarChip(datos);
            aplicarPermisos(document.documentElement);
            document.dispatchEvent(new CustomEvent('sesion:lista', { detail: datos }));
        } catch (e) {
            console.warn('No se pudo leer la sesión', e);
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', cargarSesion);
    else cargarSesion();
})();
