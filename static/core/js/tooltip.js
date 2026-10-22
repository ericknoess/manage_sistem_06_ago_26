// static/core/js/tooltip.js — Texto de ayuda inmediato para elementos con data-tooltip="…".
// Sustituye al atributo title, que el navegador muestra con retraso. Admite saltos de línea (\n).
// Requiere core/css/tooltip.css.

(function () {
    let globo = null;
    let actual = null;

    function asegurarGlobo() {
        if (!globo) {
            globo = document.createElement('div');
            globo.className = 'tooltip-globo';
            globo.setAttribute('role', 'tooltip');
            document.body.appendChild(globo);
        }
        return globo;
    }

    // Lo coloca junto al cursor sin salirse de la ventana
    function posicionar(x, y) {
        const margen = 12;
        const ancho = globo.offsetWidth;
        const alto = globo.offsetHeight;
        let izquierda = x + margen;
        let arriba = y + margen;
        if (izquierda + ancho > window.innerWidth - 4) izquierda = Math.max(4, x - ancho - margen);
        if (arriba + alto > window.innerHeight - 4) arriba = Math.max(4, y - alto - margen);
        globo.style.left = `${izquierda}px`;
        globo.style.top = `${arriba}px`;
    }

    function ocultar() {
        actual = null;
        if (globo) globo.classList.remove('is-visible');
    }

    document.addEventListener('mouseover', (e) => {
        const elemento = e.target.closest('[data-tooltip]');
        if (!elemento || !elemento.dataset.tooltip) return ocultar();
        if (elemento === actual) return;
        actual = elemento;
        asegurarGlobo().textContent = elemento.dataset.tooltip;
        globo.classList.add('is-visible');
        posicionar(e.clientX, e.clientY);
    });

    document.addEventListener('mousemove', (e) => {
        if (actual && globo) posicionar(e.clientX, e.clientY);
    });

    document.addEventListener('mouseout', (e) => {
        if (actual && !actual.contains(e.relatedTarget)) ocultar();
    });

    // Al hacer scroll o clic el elemento puede desaparecer: se oculta para no dejar el globo flotando
    document.addEventListener('scroll', ocultar, true);
    document.addEventListener('mousedown', ocultar);
})();
