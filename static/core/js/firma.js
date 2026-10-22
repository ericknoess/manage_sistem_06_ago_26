// static/core/js/firma.js — Firma electrónica (21 CFR Part 11) para acciones críticas.
//
//   const r = await ejecutarConFirma({
//       accion: 'ABORTAR_LOTE', titulo: 'Abortar lote', detalle: 'Lote L-001',
//       url: '/api/lotes/3/abortar/', metodo: 'POST', cuerpo: { motivo_aborto: '...' },
//   });
//   // r = null si se canceló; si no, { ok, status, data }
//
// Pide la contraseña, la manda con la petición (firma_password, firma_comentario) y, si es incorrecta,
// deja reintentar en el mismo modal. El significado de cada firma viene del servidor (/api/sesion/).
// `avisoDesviacion` (texto) muestra el aviso y pide un motivo obligatorio, que viaja como `motivo_desviacion`;
// si el servidor responde MOTIVO_REQUERIDO, el modal muestra ese campo y deja reintentar.
// Necesita sesion.js (SESION) y su CSS en static/core/css/firma.css.

const SIGNIFICADOS_POR_DEFECTO = {
    ABORTAR_LOTE: 'Autorizo el aborto del lote',
    ELIMINAR_LOTE: 'Autorizo la eliminación del lote planeado',
    ARCHIVAR_LOTE: 'Autorizo el archivo del lote completado',
    FASE_EN_PROGRESO: 'Inicio la ejecución de la fase',
    FASE_COMPLETADA: 'Ejecución completada y verificada',
    CAMBIAR_EQUIPO: 'Autorizo el cambio de equipo durante la ejecución',
};

function escaparFirma(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function ejecutarConFirma({ accion, titulo, detalle = '', url, metodo = 'POST', cuerpo = {}, avisoDesviacion = '' }) {
    const sesion = window.SESION || {};
    const significado = (sesion.firmas && sesion.firmas[accion]) || SIGNIFICADOS_POR_DEFECTO[accion] || titulo;

    return new Promise(resolver => {
        const fondo = document.createElement('div');
        fondo.className = 'firma-fondo';
        fondo.innerHTML = `
            <form class="firma-modal" role="dialog" aria-modal="true" aria-labelledby="firmaTitulo" autocomplete="off">
                <h3 id="firmaTitulo">✍️ Firma electrónica</h3>
                <div class="firma-accion">
                    <strong>${escaparFirma(titulo)}</strong>
                    ${detalle ? `<span>${escaparFirma(detalle)}</span>` : ''}
                </div>
                <div class="firma-significado">
                    <span>Significado de tu firma</span>
                    «${escaparFirma(significado)}»
                </div>
                <div class="firma-desviacion" hidden>
                    <div class="firma-desviacion__aviso"></div>
                    <label class="firma-campo">
                        <span>Motivo de la desviación (obligatorio)</span>
                        <textarea name="motivo_desviacion" rows="2" maxlength="500" placeholder="¿Por qué se inicia fuera de la ventana programada?"></textarea>
                    </label>
                </div>
                <div class="firma-firmante">Firmas como <strong>${escaparFirma(sesion.nombre || '')}</strong> (${escaparFirma(sesion.usuario || '')})</div>
                <label class="firma-campo">
                    <span>Contraseña</span>
                    <input type="password" name="firma_password" required autocomplete="current-password">
                </label>
                <label class="firma-campo">
                    <span>Comentario (opcional)</span>
                    <textarea name="firma_comentario" rows="2" maxlength="500" placeholder="Observaciones de la firma…"></textarea>
                </label>
                <div class="firma-error" role="alert" hidden></div>
                <p class="firma-legal">Tu firma electrónica equivale a tu firma autógrafa y queda registrada con tu nombre, fecha y hora (21 CFR Part 11).</p>
                <div class="firma-botones">
                    <button type="button" class="firma-cancelar">Cancelar</button>
                    <button type="submit" class="firma-firmar">Firmar</button>
                </div>
            </form>`;
        document.body.appendChild(fondo);

        const formulario = fondo.querySelector('form');
        const campoClave = formulario.elements.firma_password;
        const cajaError = fondo.querySelector('.firma-error');
        const botonFirmar = fondo.querySelector('.firma-firmar');
        const cajaDesviacion = fondo.querySelector('.firma-desviacion');
        const campoMotivo = formulario.elements.motivo_desviacion;
        const pedirMotivo = (aviso) => {
            fondo.querySelector('.firma-desviacion__aviso').textContent = aviso;
            cajaDesviacion.hidden = false;
            campoMotivo.required = true;
            campoMotivo.minLength = 10;
        };
        if (avisoDesviacion) pedirMotivo(avisoDesviacion);
        (avisoDesviacion ? campoMotivo : campoClave).focus();

        const cerrar = (resultado) => {
            document.removeEventListener('keydown', alEscape);
            fondo.remove();
            resolver(resultado);
        };
        const alEscape = (e) => { if (e.key === 'Escape' && !botonFirmar.disabled) cerrar(null); };
        document.addEventListener('keydown', alEscape);
        fondo.querySelector('.firma-cancelar').addEventListener('click', () => cerrar(null));

        formulario.addEventListener('submit', async (evento) => {
            evento.preventDefault();
            botonFirmar.disabled = true;
            botonFirmar.textContent = 'Firmando…';
            cajaError.hidden = true;
            try {
                const respuesta = await fetch(url, {
                    method: metodo,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ...cuerpo,
                        firma_password: campoClave.value,
                        firma_comentario: formulario.elements.firma_comentario.value.trim(),
                        ...(cajaDesviacion.hidden ? {} : { motivo_desviacion: campoMotivo.value.trim() }),
                    }),
                });
                let datos = {};
                try { datos = await respuesta.json(); } catch (e) { /* 204 sin cuerpo */ }

                if (!respuesta.ok && ['FIRMA_INVALIDA', 'FIRMA_REQUERIDA'].includes(datos.codigo)) {
                    cajaError.textContent = datos.error;
                    cajaError.hidden = false;
                    campoClave.value = '';
                    campoClave.focus();
                    botonFirmar.disabled = false;
                    botonFirmar.textContent = 'Firmar';
                    return;
                }
                if (!respuesta.ok && datos.codigo === 'MOTIVO_REQUERIDO') {
                    pedirMotivo(datos.error);
                    campoMotivo.focus();
                    botonFirmar.disabled = false;
                    botonFirmar.textContent = 'Firmar';
                    return;
                }
                if (datos.codigo === 'CUENTA_BLOQUEADA') {
                    cajaError.textContent = datos.error;
                    cajaError.hidden = false;
                    setTimeout(() => { location.href = '/login/'; }, 3000);
                    return;
                }
                cerrar({ ok: respuesta.ok, status: respuesta.status, data: datos });
            } catch (e) {
                cajaError.textContent = 'Error de red. Intenta de nuevo.';
                cajaError.hidden = false;
                botonFirmar.disabled = false;
                botonFirmar.textContent = 'Firmar';
            }
        });
    });
}
