// gestion/static/gestion/js/tablero.js — Tablero Kanban de un proyecto de oficina.
//
//   TableroOficina.pintar(caja, proyecto, tareas)   (tareas sin las resumen)
//
// Arrastrar una tarjeta a otra columna o posición la mueve (POST /mover/); la columna final la marca terminada.
// Cada columna tiene alta rápida al final. Usa moverTarjeta, crearTareaRapida y abrirTarea de proyecto.js.

const TableroOficina = (() => {
    let arrastrada = null;

    function tarjeta(t, proyecto) {
        const etiquetas = proyecto.etiquetas.filter(e => t.etiquetas.includes(e.id));
        const padre = t.padre ? proyecto.tareas.find(x => x.id === t.padre) : null;
        const [hechos, total] = t.checklist;
        const terminada = t.avance >= 100;
        return `
            <article class="gk-tarjeta gk-tarjeta--${t.prioridad.toLowerCase()} ${terminada ? 'gk-tarjeta--hecha' : ''}" draggable="true"
                     data-id="${t.id}" tabindex="0" aria-label="${escaparHtml(t.nombre)}">
                ${padre ? `<span class="gk-padre">${escaparHtml(padre.nombre)} ›</span>` : ''}
                ${etiquetas.length ? `<span class="gk-etiquetas">${etiquetas.map(e => `<span class="gk-etiqueta" style="--color:${escaparHtml(e.color)}">${escaparHtml(e.nombre)}</span>`).join('')}</span>` : ''}
                <strong class="gk-titulo">${t.es_hito ? '◆ ' : ''}${escaparHtml(t.nombre)}</strong>
                ${t.avance > 0 && t.avance < 100 ? `<span class="gk-avance" title="Avance ${t.avance} %"><span style="width:${t.avance}%"></span></span>` : ''}
                <span class="gk-pie">
                    ${t.fin ? `<span class="gk-fecha ${t.vencida ? 'g-vencida' : ''}" title="${t.vencida ? 'Vencida' : 'Fecha de fin'}">📅 ${G.fechaCorta(t.fin)}</span>` : ''}
                    ${total ? `<span class="${hechos === total ? 'gk-completo' : ''}" title="Checklist">☑ ${hechos}/${total}</span>` : ''}
                    ${t.comentarios ? `<span title="Comentarios">💬 ${t.comentarios}</span>` : ''}
                    ${t.prioridad === 'URGENTE' || t.prioridad === 'ALTA' ? `<span class="gk-prioridad">${G.PRIORIDADES[t.prioridad]}</span>` : ''}
                    <span class="gk-espacio"></span>
                    ${t.responsable ? `<i class="gk-persona" style="background:${G.colorPersona(t.responsable)}" title="${escaparHtml(t.responsable_nombre)}">${G.iniciales(t.responsable_nombre)}</i>` : ''}
                </span>
            </article>`;
    }

    function pintar(caja, proyecto, tareas) {
        const scroll = caja.querySelector('.gk') ? caja.querySelector('.gk').scrollLeft : 0;
        const porColumna = Object.fromEntries(proyecto.columnas.map(c => [c.id, []]));
        const sinColumna = [];
        tareas.forEach(t => (porColumna[t.columna] || sinColumna).push(t));
        Object.values(porColumna).forEach(l => l.sort((a, b) => a.orden_columna - b.orden_columna || a.id - b.id));
        caja.innerHTML = `
            <div class="gk">
                ${proyecto.columnas.map(c => {
                    const lista = porColumna[c.id];
                    const lleno = c.limite && lista.length >= c.limite;
                    return `
                    <section class="gk-columna ${c.es_final ? 'gk-columna--final' : ''} ${lleno ? 'gk-columna--llena' : ''}" data-columna="${c.id}" aria-label="${escaparHtml(c.nombre)}">
                        <header class="gk-columna__cabecera">
                            <h3>${c.es_final ? '✔ ' : ''}${escaparHtml(c.nombre)}</h3>
                            <span class="gk-conteo" title="${c.limite ? `Límite de ${c.limite} tarjetas` : ''}">${lista.length}${c.limite ? `/${c.limite}` : ''}</span>
                        </header>
                        <div class="gk-lista" data-lista="${c.id}">${lista.map(t => tarjeta(t, proyecto)).join('')}</div>
                        <div class="gk-nueva"><input type="text" maxlength="200" placeholder="+ Agregar tarjeta" data-nueva="${c.id}" aria-label="Nueva tarjeta en ${escaparHtml(c.nombre)}"></div>
                    </section>`;
                }).join('')}
                ${sinColumna.length ? `<section class="gk-columna gk-columna--sin"><header class="gk-columna__cabecera"><h3>Sin columna</h3>
                    <span class="gk-conteo">${sinColumna.length}</span></header><div class="gk-lista">${sinColumna.map(t => tarjeta(t, proyecto)).join('')}</div></section>` : ''}
            </div>`;
        const tablero = caja.querySelector('.gk');
        tablero.scrollLeft = scroll;

        caja.querySelectorAll('.gk-tarjeta').forEach(el => {
            el.addEventListener('click', () => abrirTarea(Number(el.dataset.id)));
            el.addEventListener('keydown', (e) => { if (e.key === 'Enter') abrirTarea(Number(el.dataset.id)); });
            el.addEventListener('dragstart', (e) => {
                arrastrada = el;
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', el.dataset.id);
                requestAnimationFrame(() => el.classList.add('gk-tarjeta--arrastrando'));
            });
            el.addEventListener('dragend', () => {
                el.classList.remove('gk-tarjeta--arrastrando');
                caja.querySelectorAll('.gk-hueco').forEach(h => h.remove());
                arrastrada = null;
            });
        });

        caja.querySelectorAll('.gk-lista[data-lista]').forEach(lista => {
            lista.addEventListener('dragover', (e) => {
                if (!arrastrada) return;
                e.preventDefault();
                let hueco = caja.querySelector('.gk-hueco');
                if (!hueco) { hueco = document.createElement('div'); hueco.className = 'gk-hueco'; }
                const despues = [...lista.querySelectorAll('.gk-tarjeta:not(.gk-tarjeta--arrastrando)')]
                    .find(t => e.clientY < t.getBoundingClientRect().top + t.offsetHeight / 2);
                despues ? lista.insertBefore(hueco, despues) : lista.appendChild(hueco);
            });
            lista.addEventListener('drop', (e) => {
                e.preventDefault();
                if (!arrastrada) return;
                const hueco = lista.querySelector('.gk-hueco');
                const anteriores = hueco ? [...lista.children].slice(0, [...lista.children].indexOf(hueco))
                    .filter(n => n.classList.contains('gk-tarjeta') && n !== arrastrada).length : 0;
                const id = Number(arrastrada.dataset.id);
                if (hueco) lista.insertBefore(arrastrada, hueco);   // se ve en su lugar mientras responde el servidor
                caja.querySelectorAll('.gk-hueco').forEach(h => h.remove());
                moverTarjeta(id, Number(lista.dataset.lista), anteriores);
            });
        });

        caja.querySelectorAll('[data-nueva]').forEach(input => input.addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || !input.value.trim()) return;
            input.disabled = true;
            const ok = await crearTareaRapida({ nombre: input.value, columna: Number(input.dataset.nueva) });
            if (!ok) input.disabled = false;
            // tras recargar, el campo de esa columna vuelve a tener el foco para seguir capturando
            const otra = document.querySelector(`[data-nueva="${input.dataset.nueva}"]`);
            if (ok && otra) otra.focus();
        }));
    }

    return { pintar };
})();
