// static/core/js/inicio-previo.js — Se carga en el <head> del inicio: si toca intro (primera visita de la sesión y sin
// «reducir movimiento»), la muestra desde el primer cuadro para que la página no se vea un instante antes.
(function () {
    try {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        if (sessionStorage.getItem('cc-intro-vista') === '1') return;
        document.documentElement.classList.add('cc-intro-pendiente');
    } catch (e) { /* sin almacenamiento: sin intro */ }
})();
