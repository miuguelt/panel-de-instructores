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
    let origen, consultandoFicha = false;

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
            origen = boton;
            dialogo.showModal();
        });
    }
    doc.getElementById('pl-gantt-evento-cerrar').addEventListener('click', function () { dialogo.close(); });
    dialogo.addEventListener('click', function (evento) {
        // La ficha pedagógica usa el modal compartido, fuera de la capa del diálogo nativo.
        const abrirFicha = evento.target.closest('[data-pedagogico-target]');
        if (abrirFicha && fichaPedagogica) consultandoFicha = true;
        if (evento.target === dialogo || abrirFicha) dialogo.close();
    });
    dialogo.addEventListener('close', function () {
        if (consultandoFicha) alCambiarVentana();
        else if (origen) origen.focus();
    });
    function restaurarDesdeFicha() {
        if (!consultandoFicha) return;
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
