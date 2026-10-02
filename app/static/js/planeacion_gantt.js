/* Lectura compacta del cronograma y detalle de cada evento. */
'use strict';

function initPlaneacionGantt(doc = document) {
    const seccion = doc.getElementById('seccion-gantt');
    const dialogo = doc.getElementById('pl-gantt-evento');
    if (!seccion || !dialogo) return;
    const paneles = [...dialogo.querySelectorAll('[data-gantt-detalle]')];
    const filas = seccion.querySelectorAll('.pl-gantt-item');
    const grupos = seccion.querySelectorAll('.pl-gantt-grupo');
    const filtros = seccion.querySelectorAll('.pl-filter-btn');
    const fichaPedagogica = doc.getElementById('modal-pedagogico');
    let origen, botonFicha, consultandoFicha = false;
    const columnas = doc.getElementById('pl-gantt-columnas');
    const movil = doc.defaultView.matchMedia('(max-width: 799px)');
    let columnaElegida = false;

    function mostrarColumna(oculta) {
        seccion.classList.toggle('is-labels-hidden', oculta);
        columnas.setAttribute('aria-expanded', String(!oculta));
        columnas.setAttribute('aria-pressed', String(oculta));
        columnas.textContent = oculta ? 'Mostrar columna' : 'Ocultar columna';
    }
    mostrarColumna(movil.matches);
    columnas.addEventListener('click', function () {
        columnaElegida = true;
        mostrarColumna(!seccion.classList.contains('is-labels-hidden'));
    });
    movil.addEventListener('change', function (evento) {
        if (!columnaElegida) mostrarColumna(evento.matches);
    });

    function activarPestana(panel, nombre, enfocar = false) {
        for (const tab of panel.querySelectorAll('[data-gantt-tab]')) {
            const activa = tab.dataset.ganttTab === nombre;
            tab.setAttribute('aria-selected', String(activa));
            tab.tabIndex = activa ? 0 : -1;
            if (activa && enfocar) tab.focus();
        }
        for (const contenido of panel.querySelectorAll('[data-gantt-pane]')) {
            contenido.hidden = contenido.dataset.ganttPane !== nombre;
        }
    }
    for (const panel of paneles) {
        const tabs = [...panel.querySelectorAll('[data-gantt-tab]')];
        for (const [indice, tab] of tabs.entries()) {
            tab.addEventListener('click', function () { activarPestana(panel, tab.dataset.ganttTab); });
            tab.addEventListener('keydown', function (evento) {
                const destinos = { ArrowRight: (indice + 1) % tabs.length, ArrowLeft: (indice + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 };
                if (!(evento.key in destinos)) return;
                evento.preventDefault();
                activarPestana(panel, tabs[destinos[evento.key]].dataset.ganttTab, true);
            });
        }
    }

    function filtrar(filtro) {
        let visibles = 0;
        for (const fila of filas) {
            fila.hidden = filtro !== 'all' && fila.dataset.type !== filtro && fila.dataset.status !== filtro;
            if (!fila.hidden) visibles++;
        }
        for (const grupo of grupos) {
            grupo.hidden = ![...grupo.querySelectorAll('.pl-gantt-item')].some(fila => !fila.hidden);
        }
        for (const boton of filtros) {
            const activo = boton.dataset.filter === filtro;
            boton.classList.toggle('is-active', activo);
            boton.setAttribute('aria-pressed', String(activo));
        }
        doc.getElementById('pl-gantt-contador').textContent = `${visibles} de ${filas.length} competencias`;
        doc.getElementById('pl-gantt-vacio').hidden = visibles > 0;
    }

    for (const boton of filtros) boton.addEventListener('click', function () { filtrar(boton.dataset.filter); });
    seccion.querySelector('[data-gantt-reset]').addEventListener('click', function () { filtrar('all'); });
    filtrar('all');

    for (const boton of seccion.querySelectorAll('[data-gantt-target]')) {
        boton.addEventListener('click', function () {
            const panel = paneles.find(detalle => detalle.id === boton.dataset.ganttTarget);
            if (!panel) return;
            for (const detalle of paneles) detalle.hidden = detalle !== panel;
            doc.getElementById('pl-gantt-evento-titulo').textContent = panel.dataset.nombre;
            doc.getElementById('pl-gantt-evento-contexto').textContent = panel.dataset.contexto;
            activarPestana(panel, 'resumen');
            origen = boton;
            dialogo.showModal();
        });
    }
    doc.getElementById('pl-gantt-evento-cerrar').addEventListener('click', function () { dialogo.close(); });
    dialogo.addEventListener('click', function (evento) {
        // La ficha pedagógica usa el modal compartido, fuera de la capa del diálogo nativo.
        const abrirFicha = evento.target.closest ? evento.target.closest('[data-pedagogico-target]') : null;
        if (abrirFicha && fichaPedagogica && dialogo.open) {
            evento.stopPropagation();
            consultandoFicha = true;
            botonFicha = abrirFicha;
            dialogo.close();
            return;
        } else if (evento.target === dialogo) {
            dialogo.close();
            return;
        }

        const botonFiltro = evento.target.closest ? evento.target.closest('[data-pedagogia-filtro]') : null;
        if (botonFiltro && botonFiltro.dataset && botonFiltro.dataset.pedagogiaFiltro) {
            const panel = paneles.find(p => !p.hidden);
            if (!panel) return;
            const filtro = botonFiltro.dataset.pedagogiaFiltro;
            const botones = panel.querySelectorAll?.('[data-pedagogia-filtro]') || [];
            for (const b of botones) {
                if (b.classList && b.dataset?.pedagogiaFiltro) {
                    const activo = b === botonFiltro;
                    b.classList.toggle('is-active', activo);
                    b.setAttribute?.('aria-pressed', String(activo));
                }
            }
            const secciones = panel.querySelectorAll?.('[data-pedagogia-seccion]') || [];
            for (const sec of secciones) {
                if (sec.dataset?.pedagogiaSeccion) {
                    sec.hidden = filtro !== 'todos' && sec.dataset.pedagogiaSeccion !== filtro;
                }
            }
        }
    });
    dialogo.addEventListener('input', function (evento) {
        const input = (evento.target?.classList?.contains && evento.target.classList.contains('pl-pedagogia-search')) ? evento.target : null;
        if (!input) return;
        const panel = paneles.find(p => !p.hidden);
        if (!panel) return;
        const termino = (input.value || '').trim().toLowerCase();
        const items = panel.querySelectorAll?.('.pl-pedagogia-item') || [];
        let coincidencias = 0;
        for (const item of items) {
            if (!item.classList?.contains?.('pl-pedagogia-item')) continue;
            const texto = (item.textContent || '').toLowerCase();
            const coincide = !termino || texto.includes(termino);
            item.hidden = !coincide;
            if (coincide && termino) coincidencias++;
        }
        const contador = panel.querySelector?.('.pl-pedagogia-match-count');
        if (contador) {
            contador.textContent = termino ? `${coincidencias} coincidencias` : '';
        }
    });
    dialogo.addEventListener('close', function () {
        if (botonFicha) {
            // Delega la apertura existente cuando la capa nativa ya dejó de bloquear el foco.
            const solicitud = botonFicha;
            doc.defaultView.requestAnimationFrame(function () {
                doc.defaultView.requestAnimationFrame(function () {
                    botonFicha = null;
                    solicitud.click();
                    alCambiarVentana();
                });
            });
        } else if (consultandoFicha) alCambiarVentana();
        else if (origen) origen.focus();
    });
    function restaurarDesdeFicha() {
        if (!consultandoFicha || botonFicha) return;
        if (fichaPedagogica.classList.contains('is-open')) {
            if (!fichaPedagogica.contains(doc.activeElement)) doc.getElementById('pl-modal-close-btn').focus();
        } else {
            consultandoFicha = false;
            origen.focus();
        }
    }
    // El control debe estar visible después del cierre nativo y la apertura compartida.
    function alCambiarVentana() {
        doc.defaultView.requestAnimationFrame(function () {
            doc.defaultView.requestAnimationFrame(restaurarDesdeFicha);
        });
    }
    doc.addEventListener('click', alCambiarVentana);
    doc.addEventListener('keydown', alCambiarVentana);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { initPlaneacionGantt };
} else {
    initPlaneacionGantt();
}
