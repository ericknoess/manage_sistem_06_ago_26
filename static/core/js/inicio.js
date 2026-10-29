// static/core/js/inicio.js — Animaciones del Centro de Control de Operaciones (página de inicio).
//
// - Intro cinematográfica (barras de cine, emblema que se dibuja, título que se enfoca): una vez por sesión del navegador;
//   «Saltar», Esc o un clic la terminan, y «Ver la intro otra vez» (pie de página) la repite.
// - Entrada escalonada de encabezado, indicadores (con contador desde 0), etapas del flujo y tarjetas (GSAP).
// - Reloj en vivo, células flotando en el fondo (canvas) con paralaje al mover el mouse, tarjetas con inclinación 3D
//   y reflejo que sigue al cursor.
// Con «reducir movimiento» en el sistema, o si GSAP no carga, la página se queda quieta (todo visible, sin intro).

(function () {
    const reducir = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const conGsap = typeof window.gsap !== 'undefined' && !reducir;
    const $ = (sel, raiz = document) => raiz.querySelector(sel);
    const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

    // ---------------------------------------------------------------- reloj
    const hora = $('#relojHora'), seg = $('#relojSegundos');
    const tic = () => {
        const d = new Date();
        hora.textContent = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
        seg.textContent = `:${String(d.getSeconds()).padStart(2, '0')}`;
    };
    tic();
    setInterval(tic, 1000);

    if (!conGsap) {
        document.documentElement.classList.remove('cc-intro-pendiente');
        return;
    }

    // ---------------------------------------------------------------- células del fondo
    (function celulas() {
        const lienzo = $('#lienzoCelulas');
        const ctx = lienzo.getContext('2d');
        const colores = ['96, 165, 250', '167, 139, 250', '244, 114, 182', '52, 211, 153', '251, 191, 36'];
        let ancho, alto, dpr, puntos = [], mouse = { x: 0, y: 0 }, visible = true;
        const crear = () => {
            dpr = Math.min(window.devicePixelRatio || 1, 2);
            ancho = window.innerWidth; alto = window.innerHeight;
            lienzo.width = ancho * dpr; lienzo.height = alto * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            const n = Math.round(Math.min(70, ancho * alto / 26000));
            puntos = Array.from({ length: n }, () => ({
                x: Math.random() * ancho, y: Math.random() * alto, r: 4 + Math.random() * 16,
                vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25 - 0.08,
                c: colores[Math.floor(Math.random() * colores.length)], z: 0.3 + Math.random() * 0.9, fase: Math.random() * Math.PI * 2,
            }));
        };
        const dibujar = (t) => {
            if (visible) {
                ctx.clearRect(0, 0, ancho, alto);
                const px = (mouse.x - ancho / 2) * 0.02, py = (mouse.y - alto / 2) * 0.02;
                for (const p of puntos) {
                    p.x += p.vx; p.y += p.vy;
                    if (p.x < -40) p.x = ancho + 40; if (p.x > ancho + 40) p.x = -40;
                    if (p.y < -40) p.y = alto + 40; if (p.y > alto + 40) p.y = -40;
                    p.dx = p.x - px * p.z; p.dy = p.y - py * p.z;
                }
                // Enlaces entre células cercanas
                for (let i = 0; i < puntos.length; i++) {
                    for (let j = i + 1; j < puntos.length; j++) {
                        const a = puntos[i], b = puntos[j];
                        const d = Math.hypot(a.dx - b.dx, a.dy - b.dy);
                        if (d < 150) {
                            ctx.strokeStyle = `rgba(99, 102, 241, ${0.12 * (1 - d / 150)})`;
                            ctx.lineWidth = 1;
                            ctx.beginPath(); ctx.moveTo(a.dx, a.dy); ctx.lineTo(b.dx, b.dy); ctx.stroke();
                        }
                    }
                }
                for (const p of puntos) {
                    const latido = 1 + Math.sin(t / 900 + p.fase) * 0.06;
                    const r = p.r * latido;
                    const g = ctx.createRadialGradient(p.dx - r * 0.3, p.dy - r * 0.3, r * 0.1, p.dx, p.dy, r);
                    g.addColorStop(0, `rgba(${p.c}, 0.35)`);
                    g.addColorStop(1, `rgba(${p.c}, 0.08)`);
                    ctx.fillStyle = g;
                    ctx.beginPath(); ctx.arc(p.dx, p.dy, r, 0, Math.PI * 2); ctx.fill();
                    ctx.strokeStyle = `rgba(${p.c}, 0.35)`; ctx.stroke();
                    ctx.fillStyle = `rgba(${p.c}, 0.45)`;                       // núcleo
                    ctx.beginPath(); ctx.arc(p.dx + r * 0.15, p.dy + r * 0.1, r * 0.28, 0, Math.PI * 2); ctx.fill();
                }
            }
            requestAnimationFrame(dibujar);
        };
        crear();
        window.addEventListener('resize', crear);
        window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
        document.addEventListener('visibilitychange', () => { visible = !document.hidden; });
        requestAnimationFrame(dibujar);
    })();

    // ---------------------------------------------------------------- tarjetas con inclinación 3D y reflejo
    $$('.app-card, .cc-kpi').forEach((tarjeta) => {
        const fuerza = tarjeta.classList.contains('cc-kpi') ? 10 : 7;
        tarjeta.addEventListener('mousemove', (e) => {
            const r = tarjeta.getBoundingClientRect();
            const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
            tarjeta.style.setProperty('--mx', `${x * 100}%`);
            tarjeta.style.setProperty('--my', `${y * 100}%`);
            gsap.to(tarjeta, { rotateY: (x - 0.5) * fuerza, rotateX: (0.5 - y) * fuerza, y: -4, transformPerspective: 700,
                               duration: 0.4, ease: 'power2.out' });
        });
        tarjeta.addEventListener('mouseleave', () => gsap.to(tarjeta, { rotateX: 0, rotateY: 0, y: 0, duration: 0.7, ease: 'elastic.out(1, 0.5)' }));
    });

    // ---------------------------------------------------------------- entrada de la página
    function entrada(rapida = false) {
        const v = rapida ? 0.6 : 1;   // velocidad
        const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });
        tl.from('.cc-hero', { y: -40, opacity: 0, duration: 0.9 * v })
          .from('.cc-eyebrow', { x: -30, opacity: 0, duration: 0.6 * v }, '-=0.5')
          .from('#tituloPrincipal', { opacity: 0, filter: 'blur(14px)', letterSpacing: '0.25em', duration: 1.2 * v }, '-=0.45')
          .from('.cc-subtitulo', { y: 14, opacity: 0, duration: 0.6 * v }, '-=0.7')
          .from('.cc-reactor', { scale: 0.4, rotate: -18, opacity: 0, duration: 1 * v, ease: 'back.out(1.8)' }, '-=1')
          .from('.cc-hero__lateral > *', { x: 30, opacity: 0, stagger: 0.1, duration: 0.6 * v }, '-=0.8')
          .from('.cc-kpi', { y: 50, rotateX: -50, opacity: 0, transformPerspective: 800, transformOrigin: '50% 100%',
                             stagger: 0.08, duration: 0.8 * v, ease: 'back.out(1.4)' }, '-=0.4')
          .add(contadores, '<0.1')
          .from('.cc-grupo__titulo', { x: -40, opacity: 0, stagger: 0.1, duration: 0.6 * v }, '-=0.4')
          .from('.cc-etapa', { y: 70, opacity: 0, scale: 0.96, stagger: 0.18, duration: 0.9 * v }, '-=0.4')
          .from('.cc-conector', { scaleX: 0, opacity: 0, transformOrigin: '0% 50%', stagger: 0.18, duration: 0.6 * v }, '-=0.8')
          .from('.cc-etapa .app-card', { y: 26, opacity: 0, stagger: 0.04, duration: 0.55 * v }, '-=0.9')
          .from('.cc-secundarios .cc-grupo', { y: 50, opacity: 0, stagger: 0.12, duration: 0.8 * v }, '-=0.5')
          .from('.cc-pie', { opacity: 0, duration: 0.6 * v }, '-=0.3');
        // Que nada quede con estilos de la animación (filtros o transformaciones) al terminar
        tl.eventCallback('onComplete', () => gsap.set('.cc-hero, #tituloPrincipal, .cc-etapa, .cc-secundarios .cc-grupo', { clearProps: 'filter,transform' }));
        return tl;
    }

    function contadores() {
        $$('.cc-kpi__valor').forEach((el, i) => {
            const fin = Number(el.dataset.valor) || 0;
            const obj = { n: 0 };
            gsap.to(obj, { n: fin, duration: 1.4 + i * 0.1, ease: 'power2.out', onUpdate: () => { el.textContent = Math.round(obj.n); } });
        });
    }

    // ---------------------------------------------------------------- intro cinematográfica
    const intro = $('#intro');
    let tlIntro = null;

    function terminarIntro() {
        if (!tlIntro) return;
        tlIntro.revert();      // deshace todo lo que la intro (y la entrada anidada) alcanzó a aplicar
        tlIntro = null;
        document.documentElement.classList.remove('cc-intro-pendiente');
        intro.classList.add('cc-intro--activa');
        gsap.fromTo(intro, { opacity: 1 }, { opacity: 0, duration: 0.35, onComplete: () => { intro.classList.remove('cc-intro--activa'); gsap.set(intro, { clearProps: 'all' }); } });
        entrada(true);
        document.removeEventListener('keydown', teclaIntro);
    }
    const teclaIntro = (e) => { if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') terminarIntro(); };

    function reproducirIntro() {
        intro.classList.add('cc-intro--activa');
        gsap.set(intro, { opacity: 1 });
        const trazos = $$('.cc-trazo', intro);
        trazos.forEach((t) => { const l = t.getTotalLength(); gsap.set(t, { strokeDasharray: l, strokeDashoffset: l }); });
        document.addEventListener('keydown', teclaIntro);

        tlIntro = gsap.timeline({ defaults: { ease: 'power3.inOut' } });
        tlIntro
            .fromTo('.cc-intro__barra--arriba', { yPercent: -100 }, { yPercent: 0, duration: 0.6 })
            .fromTo('.cc-intro__barra--abajo', { yPercent: 100 }, { yPercent: 0, duration: 0.6 }, '<')
            .to(trazos, { strokeDashoffset: 0, duration: 1.2, stagger: 0.12 }, '-=0.1')
            .fromTo('.cc-intro__emblema', { scale: 0.7, rotate: -25 }, { scale: 1, rotate: 0, duration: 1.4, ease: 'expo.out' }, '<')
            .fromTo('.cc-intro__marca span', { opacity: 0, y: 20, letterSpacing: '1.2em' },
                    { opacity: 1, y: 0, letterSpacing: '0.35em', stagger: 0.07, duration: 0.8, ease: 'power3.out' }, '-=0.6')
            .fromTo('.cc-intro__titulo', { opacity: 0, filter: 'blur(18px)', scale: 1.15 },
                    { opacity: 1, filter: 'blur(0px)', scale: 1, duration: 1.1, ease: 'expo.out' }, '-=0.4')
            .to({}, { duration: 0.6 })
            .to('.cc-intro__centro', { scale: 1.35, opacity: 0, filter: 'blur(10px)', duration: 0.8, ease: 'power2.in' })
            .to('.cc-intro__barra--arriba', { yPercent: -100, duration: 0.7 }, '<0.2')
            .to('.cc-intro__barra--abajo', { yPercent: 100, duration: 0.7 }, '<')
            .to(intro, { opacity: 0, duration: 0.5 }, '-=0.4')
            .add(() => {
                intro.classList.remove('cc-intro--activa');
                document.documentElement.classList.remove('cc-intro-pendiente');
                gsap.set([intro, '.cc-intro__centro', '.cc-intro__titulo', '.cc-intro__marca span', '.cc-intro__emblema'], { clearProps: 'all' });
                tlIntro = null;
                document.removeEventListener('keydown', teclaIntro);
            })
            .add(entrada(), '-=0.55');
    }

    $('#saltarIntro').addEventListener('click', terminarIntro);
    intro.addEventListener('click', (e) => { if (e.target !== $('#saltarIntro')) terminarIntro(); });
    $('#repetirIntro').addEventListener('click', () => { window.scrollTo({ top: 0, behavior: 'instant' }); reproducirIntro(); });

    let vista = false;
    try { vista = sessionStorage.getItem('cc-intro-vista') === '1'; sessionStorage.setItem('cc-intro-vista', '1'); } catch (e) { vista = false; }
    if (vista) entrada(true);
    else reproducirIntro();
})();
