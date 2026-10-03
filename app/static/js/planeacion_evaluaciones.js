/* Consulta de aprendices y juicios por tramo, sin modificar evaluaciones. */
'use strict';

function normalizarBusqueda(valor) {
    return String(valor ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es-CO');
}

function tituloResultado(rap) {
    return rap.codigo && !rap.nombre.startsWith(rap.codigo) ? `${rap.codigo} · ${rap.nombre}` : rap.nombre;
}

function filtrarAprendices(filas, { estado = 'todos', busqueda = '', instructor = '' } = {}) {
    const texto = normalizarBusqueda(busqueda).trim();
    return filas.filter(function (fila) {
        const coincideEstado = estado === 'todos' || (estado === 'pendiente' ? fila.estado !== 'evaluado' : fila.estado === 'evaluado');
        const registros = fila.resultados || [fila];
        const coincideInstructor = !instructor || registros.some(function (r) { return r.instructor === instructor; });
        return coincideEstado && coincideInstructor && normalizarBusqueda(`${fila.nombre ?? ''} ${fila.documento ?? ''}`).includes(texto);
    });
}

function initPlaneacionEvaluaciones(doc = document) {
    const dialogo = doc.getElementById('pl-evaluaciones');
    const fuente = doc.getElementById('pl-evaluaciones-json');
    if (!dialogo || !fuente) return;
    const error = doc.getElementById('pl-evaluaciones-error');
    let catalogo;
    try { catalogo = JSON.parse(fuente.textContent); }
    catch (_) {
        error.hidden = false;
        error.textContent = 'No se pudo leer el detalle de evaluaciones. Vuelva a cargar la página para reintentar.';
        return;
    }
    const titulo = doc.getElementById('pl-evaluaciones-titulo');
    const contexto = doc.getElementById('pl-evaluaciones-contexto');
    const metricas = doc.getElementById('pl-evaluaciones-metricas');
    const rapsResumen = doc.getElementById('pl-evaluaciones-raps');
    const selectorRap = doc.getElementById('pl-evaluaciones-rap');
    const selectorInstructor = doc.getElementById('pl-evaluaciones-instructor');
    const buscar = doc.getElementById('pl-evaluaciones-buscar');
    const lista = doc.getElementById('pl-evaluaciones-lista');
    const contador = doc.getElementById('pl-evaluaciones-contador');
    const descripcion = doc.getElementById('pl-evaluaciones-descripcion');
    const filtros = doc.querySelectorAll('[data-evaluacion-estado]');
    let tramo, origen, estado = 'pendiente';

    function elemento(tag, clase, texto) {
        const nodo = doc.createElement(tag);
        nodo.className = clase;
        if (texto !== undefined) nodo.textContent = texto;
        return nodo;
    }

    function seleccionado() {
        return tramo.resultados.find(function (r) { return r.id === selectorRap.value; });
    }

    function actualizarInstructores() {
        const datos = seleccionado() || tramo;
        const nombres = new Set();
        for (const fila of datos.aprendices) {
            for (const registro of fila.resultados || [fila]) {
                if (registro.estado === 'evaluado') nombres.add(registro.instructor);
            }
        }
        selectorInstructor.replaceChildren(elemento('option', '', 'Todos los evaluadores'));
        selectorInstructor.children[0].value = '';
        for (const nombre of [...nombres].sort()) {
            const opcion = elemento('option', '', nombre);
            opcion.value = nombre;
            selectorInstructor.append(opcion);
        }
        selectorInstructor.value = '';
    }

    function actualizarRaps() {
        if (!rapsResumen) return;
        rapsResumen.replaceChildren();
        if (!tramo || !tramo.resultados || !tramo.resultados.length) {
            rapsResumen.hidden = true;
            return;
        }
        rapsResumen.hidden = false;
        const cabecera = elemento('div', 'pl-eval-raps-head');
        cabecera.append(
            elemento('span', '', `Resultados de aprendizaje (${tramo.resultados.length} RAP)`),
            elemento('small', 'pl-eval-nota', 'Haga clic en un resultado para filtrar los aprendices')
        );
        const listaRaps = elemento('div', 'pl-eval-raps-lista');
        const rapSeleccionadoId = selectorRap.value;
        for (const rap of tramo.resultados) {
            const item = elemento('button', 'pl-eval-rap-item' + (rapSeleccionadoId === rap.id ? ' is-selected' : ''));
            item.type = 'button';
            item.setAttribute('aria-pressed', String(rapSeleccionadoId === rap.id));
            const info = elemento('div', 'pl-eval-rap-info');
            info.append(
                elemento('strong', '', tituloResultado(rap)),
                elemento('small', '', rap.actividad || 'Actividad de aprendizaje')
            );
            const pendientes = rap.resumen ? rap.resumen.pendientes : 0;
            const chip = elemento(
                'span',
                'pl-chip pl-chip-sm pl-tone-' + (pendientes > 0 ? 'warning' : 'success') + ' is-tone',
                pendientes > 0 ? `${pendientes} pendientes` : 'Al día'
            );
            item.append(info, chip);
            item.addEventListener('click', function () {
                selectorRap.value = selectorRap.value === rap.id ? '' : rap.id;
                estado = 'pendiente';
                actualizarInstructores();
                actualizar();
            });
            listaRaps.append(item);
        }
        rapsResumen.append(cabecera, listaRaps);
    }

    function actualizar() {
        actualizarRaps();
        const resultado = seleccionado();
        const datos = resultado || tramo;
        metricas.replaceChildren();
        for (const [clave, etiqueta] of [['total', 'Aprendices'], ['evaluados', 'Evaluados'], ['pendientes', 'Pendientes']]) {
            const tarjeta = elemento('div', 'pl-eval-metrica');
            tarjeta.append(elemento('strong', '', String(datos.resumen[clave])), elemento('span', '', etiqueta));
            metricas.append(tarjeta);
        }
        descripcion.textContent = resultado
            ? [tituloResultado(resultado), resultado.actividad].filter(Boolean).join(' · ')
            : `Evaluados: tienen juicio en todos los RAP de este tramo. Pendientes: les falta al menos uno. ${tramo.resumen.parciales || 0} tienen evaluación parcial.`;
        const filas = filtrarAprendices(datos.aprendices, { estado, busqueda: buscar.value, instructor: selectorInstructor.value });
        contador.textContent = `${filas.length} de ${datos.resumen.total} aprendices · Orden alfabético`;
        for (const boton of filtros) boton.setAttribute('aria-pressed', String(boton.dataset.evaluacionEstado === estado));
        lista.replaceChildren();
        for (const fila of filas) {
            const tarjeta = elemento('article', 'pl-eval-aprendiz');
            const cabecera = elemento('div', 'pl-eval-aprendiz-head');
            const identidad = elemento('div', '');
            identidad.append(elemento('h3', '', fila.nombre), elemento('p', '', `Documento: ${fila.documento}`));
            const etiqueta = fila.estado === 'evaluado' ? 'Evaluado' : (fila.estado === 'parcial' ? 'Evaluación parcial' : 'Por evaluar');
            cabecera.append(identidad, elemento('span', 'pl-eval-estado is-' + fila.estado, etiqueta));
            tarjeta.append(cabecera);
            if (!resultado) tarjeta.append(elemento('p', 'pl-eval-progreso', `${fila.evaluados} de ${fila.total} RAP evaluados`));
            for (const registro of fila.resultados || [fila]) {
                const detalle = elemento('div', 'pl-eval-juicio');
                const rap = resultado || tramo.resultados.find(function (r) { return r.id === registro.rap_id; });
                detalle.append(elemento('strong', '', tituloResultado(rap)));
                detalle.append(elemento('span', registro.aprobado ? 'pl-eval-aprobado' : '', registro.juicio));
                if (registro.estado === 'evaluado') {
                    detalle.append(elemento('span', '', `Instructor registrado: ${registro.instructor}`));
                    detalle.append(elemento('span', 'pl-eval-fecha', registro.fecha || 'Fecha no registrada'));
                } else detalle.append(elemento('span', 'pl-eval-fecha', 'Sin juicio registrado'));
                tarjeta.append(detalle);
            }
            lista.append(tarjeta);
        }
        if (!filas.length) lista.append(elemento('p', 'pl-eval-vacio', datos.resumen.total
            ? 'No hay aprendices que coincidan con los filtros. Cambie el estado, el evaluador o la búsqueda.'
            : 'No hay aprendices incluidos en el análisis de este tramo. Revise el grupo y el reporte de juicios.'));
    }

    for (const boton of doc.querySelectorAll('[data-evaluacion-target]')) {
        boton.addEventListener('click', function () {
            const datos = catalogo[boton.dataset.evaluacionTarget];
            if (!datos) return;
            tramo = datos;
            origen = boton;
            estado = 'pendiente';
            titulo.textContent = tramo.nombre;
            contexto.textContent = [tramo.fase, tramo.periodo, tramo.fecha_limite ? ('Debió evaluarse: ' + tramo.fecha_limite) : ''].filter(Boolean).join(' · ');
            selectorRap.replaceChildren(elemento('option', '', 'Todos los RAP del tramo'));
            selectorRap.children[0].value = '';
            for (const rap of tramo.resultados) {
                const opcion = elemento('option', '', tituloResultado(rap));
                opcion.value = rap.id;
                selectorRap.append(opcion);
            }
            selectorRap.value = '';
            buscar.value = '';
            actualizarInstructores();
            actualizar();
            dialogo.showModal();
        });
        boton.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                boton.click();
            }
        });
    }
    for (const boton of filtros) boton.addEventListener('click', function () {
        estado = boton.dataset.evaluacionEstado;
        actualizar();
    });
    selectorRap.addEventListener('change', function () {
        estado = 'pendiente';
        actualizarInstructores();
        actualizar();
    });
    selectorInstructor.addEventListener('change', actualizar);
    buscar.addEventListener('input', actualizar);
    doc.getElementById('pl-evaluaciones-cerrar').addEventListener('click', function () { dialogo.close(); });
    dialogo.addEventListener('click', function (evento) { if (evento.target === dialogo) dialogo.close(); });
    dialogo.addEventListener('close', function () { if (origen) origen.focus(); });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { filtrarAprendices, initPlaneacionEvaluaciones, tituloResultado };
} else {
    initPlaneacionEvaluaciones();
}
