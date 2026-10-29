// gestion/static/gestion/js/comun.js — Utilidades de las pantallas de proyectos (lista, Gantt y tablero).
// Fechas como texto 'AAAA-MM-DD' (días, sin hora): se convierten a número de día en UTC para no depender de la zona horaria.

const G = {};

// Petición JSON a la API: devuelve los datos o lanza Error con el mensaje del servidor
G.api = async function (url, { metodo = 'GET', datos } = {}) {
    const opciones = { method: metodo, headers: {} };
    if (datos !== undefined) {
        opciones.headers['Content-Type'] = 'application/json';
        opciones.body = JSON.stringify(datos);
    }
    const res = await fetch(url, opciones);
    if (res.status === 204) return null;
    const cuerpo = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(cuerpo.error || cuerpo.detail || 'No se pudo completar la operación.');
    return cuerpo;
};

// --- Fechas -------------------------------------------------------------------------
const MS_DIA = 86400000;
G.dia = (texto) => texto ? Math.round(Date.UTC(+texto.slice(0, 4), +texto.slice(5, 7) - 1, +texto.slice(8, 10)) / MS_DIA) : null;
G.texto = (dia) => new Date(dia * MS_DIA).toISOString().slice(0, 10);
G.hoy = () => { const d = new Date(); return Math.round(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / MS_DIA); };
G.diaSemana = (dia) => new Date(dia * MS_DIA).getUTCDay();          // 0 domingo … 6 sábado
G.esHabil = (dia) => { const s = G.diaSemana(dia); return s !== 0 && s !== 6; };
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const MESES_LARGOS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
G.MESES_LARGOS = MESES_LARGOS;
G.fechaCorta = (texto) => {
    if (!texto) return '—';
    const d = new Date(G.dia(texto) * MS_DIA);
    return `${d.getUTCDate()} ${MESES[d.getUTCMonth()]}`;
};
G.fechaLarga = (texto) => {
    if (!texto) return '—';
    const d = new Date(G.dia(texto) * MS_DIA);
    return `${d.getUTCDate()} ${MESES[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};
G.fechaHora = (iso) => iso ? new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
// Días que faltan (o pasaron) hasta una fecha, en texto corto
G.cuando = (texto) => {
    if (!texto) return '';
    const d = G.dia(texto) - G.hoy();
    if (d === 0) return 'hoy';
    if (d === 1) return 'mañana';
    if (d === -1) return 'ayer';
    return d > 0 ? `en ${d} días` : `hace ${-d} días`;
};

// --- Presentación -------------------------------------------------------------------
G.PRIORIDADES = { BAJA: 'Baja', MEDIA: 'Media', ALTA: 'Alta', URGENTE: 'Urgente' };
G.iniciales = (nombre) => String(nombre || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join('') || '?';
// Color estable por persona (para sus iniciales)
G.colorPersona = (id) => ['#2a78d6', '#1baf7a', '#eb6834', '#8b5cf6', '#e87ba4', '#0891b2', '#ca8a04', '#64748b'][(id || 0) % 8];
G.diasTexto = (n) => n === null || n === undefined ? '—' : `${n} d`;

// Aviso breve en una esquina (no bloquea)
G.aviso = function (texto, tipo = 'ok') {
    const caja = document.createElement('div');
    caja.className = `g-aviso g-aviso--${tipo}`;
    caja.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
    caja.textContent = texto;
    document.body.appendChild(caja);
    setTimeout(() => caja.classList.add('g-aviso--fuera'), tipo === 'error' ? 5500 : 3200);
    setTimeout(() => caja.remove(), tipo === 'error' ? 6000 : 3700);
};

// Preferencias del navegador (pestaña, escala, filas colapsadas); nunca rompe si el almacenamiento falla
G.leer = (clave, defecto) => { try { const v = localStorage.getItem(`gestion:${clave}`); return v === null ? defecto : JSON.parse(v); } catch (e) { return defecto; } };
G.guardar = (clave, valor) => { try { localStorage.setItem(`gestion:${clave}`, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ } };

// Ventana modal sencilla: devuelve { caja, cerrar }
G.modal = function (titulo, html, { ancho = 560, alCerrar = null } = {}) {
    const fondo = document.createElement('div');
    fondo.className = 'g-fondo';
    fondo.innerHTML = `
        <div class="g-modal" role="dialog" aria-modal="true" aria-label="${escaparHtml(titulo)}" style="width:${ancho}px">
            <header class="g-modal__cabecera"><h3>${escaparHtml(titulo)}</h3>
                <button type="button" class="g-cerrar" title="Cerrar (Esc)">✕</button></header>
            <div class="g-modal__cuerpo">${html}</div>
        </div>`;
    document.body.appendChild(fondo);
    const cerrar = () => { fondo.remove(); document.removeEventListener('keydown', teclado); if (alCerrar) alCerrar(); };
    const teclado = (e) => { if (e.key === 'Escape' && document.body.lastElementChild === fondo) cerrar(); };
    document.addEventListener('keydown', teclado);
    fondo.querySelector('.g-cerrar').addEventListener('click', cerrar);
    fondo.addEventListener('mousedown', (e) => { if (e.target === fondo) cerrar(); });
    return { caja: fondo.querySelector('.g-modal__cuerpo'), cerrar, fondo };
};

window.G = G;
