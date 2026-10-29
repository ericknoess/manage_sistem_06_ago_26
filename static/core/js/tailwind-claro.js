// static/core/js/tailwind-claro.js — Tema claro para las pantallas que usan Tailwind por CDN (roster, diseñador, tablet).
// Se incluye DESPUÉS de <script src="https://cdn.tailwindcss.com">: redefine las paletas para que las clases escritas
// para el tema oscuro (bg-slate-900, text-slate-200, text-red-300…) se vean bien sobre fondo claro (se proyectan).
//   slate: escala invertida (fondos oscuros → claros, textos claros → oscuros).
//   colores: los tonos claros (300/400) pasan a los oscuros (700/600) y los fondos oscuros (800/900/950) a tintes claros;
//   500–700 se quedan (botones de color con texto blanco).
// Letra más grande en una pantalla: <script src="…/tailwind-claro.js" data-letra="1.15"></script> escala text-xs…text-3xl.
(function () {
    if (!window.tailwind) return;
    const factor = parseFloat((document.currentScript && document.currentScript.dataset.letra) || '1') || 1;
    const slate = {
        50: '#0f172a', 100: '#0f172a', 200: '#1e293b', 300: '#334155', 400: '#475569', 500: '#64748b',
        600: '#94a3b8', 700: '#c3cedb', 800: '#ffffff', 900: '#eef2f7', 950: '#f8fafc',
    };
    // Paletas de Tailwind v3 (solo los tonos que se intercambian)
    const base = {
        red: { 50: '#fef2f2', 100: '#fee2e2', 200: '#fecaca', 300: '#fca5a5', 400: '#f87171', 500: '#ef4444', 600: '#dc2626', 700: '#b91c1c', 800: '#991b1b', 900: '#7f1d1d', 950: '#450a0a' },
        amber: { 50: '#fffbeb', 100: '#fef3c7', 200: '#fde68a', 300: '#fcd34d', 400: '#fbbf24', 500: '#f59e0b', 600: '#d97706', 700: '#b45309', 800: '#92400e', 900: '#78350f', 950: '#451a03' },
        emerald: { 50: '#ecfdf5', 100: '#d1fae5', 200: '#a7f3d0', 300: '#6ee7b7', 400: '#34d399', 500: '#10b981', 600: '#059669', 700: '#047857', 800: '#065f46', 900: '#064e3b', 950: '#022c22' },
        cyan: { 50: '#ecfeff', 100: '#cffafe', 200: '#a5f3fc', 300: '#67e8f9', 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2', 700: '#0e7490', 800: '#155e75', 900: '#164e63', 950: '#083344' },
        sky: { 50: '#f0f9ff', 100: '#e0f2fe', 200: '#bae6fd', 300: '#7dd3fc', 400: '#38bdf8', 500: '#0ea5e9', 600: '#0284c7', 700: '#0369a1', 800: '#075985', 900: '#0c4a6e', 950: '#082f49' },
        purple: { 50: '#faf5ff', 100: '#f3e8ff', 200: '#e9d5ff', 300: '#d8b4fe', 400: '#c084fc', 500: '#a855f7', 600: '#9333ea', 700: '#7e22ce', 800: '#6b21a8', 900: '#581c87', 950: '#3b0764' },
        indigo: { 50: '#eef2ff', 100: '#e0e7ff', 200: '#c7d2fe', 300: '#a5b4fc', 400: '#818cf8', 500: '#6366f1', 600: '#4f46e5', 700: '#4338ca', 800: '#3730a3', 900: '#312e81', 950: '#1e1b4b' },
        green: { 50: '#f0fdf4', 100: '#dcfce7', 200: '#bbf7d0', 300: '#86efac', 400: '#4ade80', 500: '#22c55e', 600: '#16a34a', 700: '#15803d', 800: '#166534', 900: '#14532d', 950: '#052e16' },
        yellow: { 50: '#fefce8', 100: '#fef9c3', 200: '#fef08a', 300: '#fde047', 400: '#facc15', 500: '#eab308', 600: '#ca8a04', 700: '#a16207', 800: '#854d0e', 900: '#713f12', 950: '#422006' },
        orange: { 50: '#fff7ed', 100: '#ffedd5', 200: '#fed7aa', 300: '#fdba74', 400: '#fb923c', 500: '#f97316', 600: '#ea580c', 700: '#c2410c', 800: '#9a3412', 900: '#7c2d12', 950: '#431407' },
        rose: { 50: '#fff1f2', 100: '#ffe4e6', 200: '#fecdd3', 300: '#fda4af', 400: '#fb7185', 500: '#f43f5e', 600: '#e11d48', 700: '#be123c', 800: '#9f1239', 900: '#881337', 950: '#4c0519' },
    };
    const claro = (p) => ({ ...p, 50: p[900], 100: p[800], 200: p[800], 300: p[700], 400: p[600], 800: p[200], 900: p[100], 950: p[50] });
    const colors = { slate, gray: slate };
    Object.entries(base).forEach(([nombre, paleta]) => { colors[nombre] = claro(paleta); });
    const extend = { colors };
    if (factor !== 1) {
        const tamanos = { xs: [0.75, 1], sm: [0.875, 1.25], base: [1, 1.5], lg: [1.125, 1.75], xl: [1.25, 1.75], '2xl': [1.5, 2], '3xl': [1.875, 2.25] };
        extend.fontSize = Object.fromEntries(Object.entries(tamanos).map(([k, [t, l]]) =>
            [k, [`${(t * factor).toFixed(3)}rem`, `${(l * factor).toFixed(3)}rem`]]));
    }
    window.tailwind.config = { theme: { extend } };
})();
