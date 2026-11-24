/**
 * Calendario de programación: abre el formulario de asignación ya rellenado
 * (nueva desde una celda o edición desde una asignación), alterna «Un día /
 * Varias semanas» y carga las competencias de la ficha elegida.
 * La validación definitiva la hace el servidor; aquí no hay temporizadores.
 */
(function (raiz) {
    'use strict';

    function diasDesdeMascara(mascara) {
        const valor = Number(mascara) || 0;
        const dias = [];
        for (let bit = 0; bit <= 5; bit += 1) {
            if (valor & (1 << bit)) dias.push(String(bit));
        }
        return dias;
    }

    function campo(form, nombre) {
        return form.elements[nombre];
    }

    function opciones(form, nombre) {
        const elemento = campo(form, nombre);
        if (!elemento) return [];
        return elemento.length !== undefined && !elemento.tagName ? Array.from(elemento) : [elemento];
    }

    function marcar(form, nombre, valores) {
        const elegidos = new Set(valores.map(String));
        opciones(form, nombre).forEach(function (opcion) {
            opcion.checked = elegidos.has(String(opcion.value));
        });
    }

    function modoActual(form) {
        const elegido = opciones(form, 'modo').find(function (opcion) { return opcion.checked; });
        return elegido ? elegido.value : 'semanas';
    }

    function aplicarModo(form) {
        const porSemanas = modoActual(form) === 'semanas';
        form.querySelectorAll('[data-prg-solo-semanas]').forEach(function (bloque) {
            bloque.hidden = !porSemanas;
        });
        const fin = campo(form, 'fecha_fin');
        if (fin) fin.required = porSemanas;
        const etiqueta = form.querySelector('[data-prg-etiqueta-inicio]');
        if (etiqueta) etiqueta.textContent = porSemanas ? 'Desde' : 'Fecha';
        return porSemanas;
    }

    function mostrarQuitar(form, urlEliminar) {
        const boton = form.querySelector('[data-prg-solo-editar]');
        const eliminar = form.ownerDocument.getElementById('form-eliminar-asignacion');
        if (boton) boton.hidden = !urlEliminar;
        if (eliminar && urlEliminar) eliminar.action = urlEliminar;
    }

    function prepararNuevo(form, datos) {
        const info = datos || {};
        form.reset();
        const contenedor = form.querySelector('[data-url-crear]');
        form.action = contenedor ? contenedor.dataset.urlCrear : form.action;
        if (info.instructor) campo(form, 'instructor_id').value = info.instructor;
        if (info.inicio) {
            campo(form, 'fecha_inicio').value = info.inicio;
            campo(form, 'fecha_fin').value = info.inicio;
        }
        marcar(form, 'modo', [info.inicio ? 'dia' : 'semanas']);
        mostrarQuitar(form, null);
        aplicarModo(form);
        return form;
    }

    function prepararEdicion(form, datos) {
        form.reset();
        form.action = datos.url;
        campo(form, 'instructor_id').value = datos.instructor;
        campo(form, 'ficha_id').value = datos.ficha;
        campo(form, 'competencia').value = datos.competencia;
        campo(form, 'fecha_inicio').value = datos.inicio;
        campo(form, 'fecha_fin').value = datos.fin;
        campo(form, 'observacion').value = datos.observacion || '';
        marcar(form, 'modo', [datos.inicio === datos.fin ? 'dia' : 'semanas']);
        marcar(form, 'dias_semana', diasDesdeMascara(datos.dias));
        marcar(form, 'jornada', [datos.jornada]);
        mostrarQuitar(form, datos.urlEliminar);
        aplicarModo(form);
        return form;
    }

    function llenarCompetencias(datalist, competencias) {
        datalist.innerHTML = '';
        (competencias || []).forEach(function (competencia) {
            // El servidor envía {nombre, tipo, transversal}; se aceptan también nombres sueltos.
            const datos = typeof competencia === 'string' ? { nombre: competencia } : competencia;
            const opcion = datalist.ownerDocument.createElement('option');
            opcion.value = datos.nombre;
            if (datos.transversal) opcion.label = 'Transversal: se puede programar a otros equipos';
            datalist.appendChild(opcion);
        });
        return datalist;
    }

    function cargarCompetencias(form, buscar) {
        const datalist = form.ownerDocument.getElementById('prg-competencias');
        const contenedor = form.querySelector('[data-url-competencias]');
        const ficha = campo(form, 'ficha_id').value;
        if (!datalist || !contenedor || !ficha) {
            if (datalist) llenarCompetencias(datalist, []);
            return Promise.resolve([]);
        }
        const url = contenedor.dataset.urlCompetencias.replace(/\/0\/competencias$/, '/' + encodeURIComponent(ficha) + '/competencias');
        return buscar(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
            .then(function (respuesta) { return respuesta.ok ? respuesta.json() : []; })
            .catch(function () { return []; })
            .then(function (lista) {
                llenarCompetencias(datalist, lista);
                return lista;
            });
    }

    function initProgramacion(doc, win) {
        const form = doc.getElementById('form-asignacion');
        if (!form) return null;
        // modal-system.js se carga después de este archivo: se busca al momento de abrir.
        const abrir = function (id) { if (win.abrirModal) win.abrirModal(id); };
        const buscar = win.fetch ? win.fetch.bind(win) : function () { return Promise.reject(new Error('sin fetch')); };

        doc.addEventListener('click', function (evento) {
            const objetivo = evento.target.closest ? evento.target : null;
            if (!objetivo) return;
            const editar = objetivo.closest('[data-prg-editar]');
            const programar = objetivo.closest('[data-prg-programar]');
            if (editar) {
                prepararEdicion(form, editar.dataset);
                cargarCompetencias(form, buscar);
                abrir('modal-asignacion');
            } else if (programar) {
                prepararNuevo(form, programar.dataset);
                cargarCompetencias(form, buscar);
                abrir('modal-asignacion');
            }
        });
        opciones(form, 'modo').forEach(function (opcion) {
            opcion.addEventListener('change', function () { aplicarModo(form); });
        });
        campo(form, 'ficha_id').addEventListener('change', function () { cargarCompetencias(form, buscar); });
        form.addEventListener('reset', function () {
            // Los campos vuelven a su valor inicial después del evento: se reaplica en el siguiente cuadro.
            win.requestAnimationFrame(function () { aplicarModo(form); });
        });
        aplicarModo(form);
        return form;
    }

    function arrancar(ventana) {
        const doc = ventana.document;
        if (doc.readyState === 'loading') {
            doc.addEventListener('DOMContentLoaded', initProgramacion.bind(null, doc, ventana));
            return false;
        }
        initProgramacion(doc, ventana);
        return true;
    }

    const api = {
        diasDesdeMascara, aplicarModo, prepararNuevo, prepararEdicion,
        llenarCompetencias, cargarCompetencias, initProgramacion, arrancar,
    };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    } else {
        raiz.Programacion = api;
        arrancar(raiz);
    }
}(typeof window !== 'undefined' ? window : globalThis));
