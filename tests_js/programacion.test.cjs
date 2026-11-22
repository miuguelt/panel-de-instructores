const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../app/static/js/programacion.js');

class Nodo {
    constructor(datos = {}) {
        Object.assign(this, { hidden: false, value: '', checked: false, required: false, textContent: '', dataset: {}, listeners: {} }, datos);
    }
    addEventListener(nombre, callback) { (this.listeners[nombre] ??= []).push(callback); }
    emitir(nombre, evento = {}) { for (const callback of this.listeners[nombre] ?? []) callback(evento); }
}

function grupo(nombre, valores, marcados = []) {
    const lista = valores.map(value => new Nodo({ name: nombre, value, checked: marcados.includes(value) }));
    return lista; // NodeList-like: tiene length y no tiene tagName
}

function entorno({ conContenedor = true, conEliminar = true } = {}) {
    const documento = {
        ids: {},
        listeners: {},
        getElementById(id) { return this.ids[id] ?? null; },
        createElement() { return new Nodo(); },
        addEventListener(nombre, callback) { (this.listeners[nombre] ??= []).push(callback); },
    };
    const datalist = new Nodo({ innerHTML: 'x', hijos: [], ownerDocument: documento });
    datalist.appendChild = hijo => datalist.hijos.push(hijo);
    const eliminar = new Nodo({ action: '' });
    documento.ids['prg-competencias'] = datalist;
    if (conEliminar) documento.ids['form-eliminar-asignacion'] = eliminar;

    const soloSemanas = [new Nodo(), new Nodo()];
    const etiqueta = new Nodo({ textContent: 'Desde' });
    const quitar = new Nodo({ hidden: true });
    const contenedor = new Nodo({ dataset: { urlCrear: '/programacion/asignaciones', urlCompetencias: '/programacion/fichas/0/competencias' } });
    const elements = {
        instructor_id: new Nodo({ tagName: 'SELECT' }),
        ficha_id: new Nodo({ tagName: 'SELECT' }),
        competencia: new Nodo({ tagName: 'INPUT' }),
        fecha_inicio: new Nodo({ tagName: 'INPUT' }),
        fecha_fin: new Nodo({ tagName: 'INPUT' }),
        observacion: new Nodo({ tagName: 'INPUT' }),
        modo: grupo('modo', ['dia', 'semanas'], ['semanas']),
        dias_semana: grupo('dias_semana', ['0', '1', '2', '3', '4', '5'], ['0', '1', '2', '3', '4']),
        jornada: grupo('jornada', ['manana', 'tarde', 'noche'], ['manana']),
    };
    const form = new Nodo({
        action: '/inicial', elements, ownerDocument: documento,
        reset() {
            this.resets = (this.resets || 0) + 1;
            for (const nombre of ['instructor_id', 'ficha_id', 'competencia', 'fecha_inicio', 'fecha_fin', 'observacion']) elements[nombre].value = '';
        },
        querySelectorAll(selector) { return selector === '[data-prg-solo-semanas]' ? soloSemanas : []; },
        querySelector(selector) {
            return {
                '[data-prg-etiqueta-inicio]': etiqueta,
                '[data-prg-solo-editar]': quitar,
                '[data-url-crear]': conContenedor ? contenedor : null,
                '[data-url-competencias]': conContenedor ? contenedor : null,
            }[selector] ?? null;
        },
    });
    documento.ids['form-asignacion'] = form;
    return { documento, form, elements, soloSemanas, etiqueta, quitar, eliminar, datalist };
}

const marcados = lista => lista.filter(o => o.checked).map(o => o.value);

test('diasDesdeMascara convierte la máscara en días y tolera valores vacíos', () => {
    assert.deepEqual(P.diasDesdeMascara(0b100101), ['0', '2', '5']);
    assert.deepEqual(P.diasDesdeMascara('3'), ['0', '1']);
    assert.deepEqual(P.diasDesdeMascara(undefined), []);
});

test('aplicarModo oculta días y fecha final en «Un día» y los muestra en «Varias semanas»', () => {
    const { form, elements, soloSemanas, etiqueta } = entorno();
    assert.equal(P.aplicarModo(form), true);
    assert.equal(elements.fecha_fin.required, true);
    assert.equal(etiqueta.textContent, 'Desde');
    elements.modo[0].checked = true; elements.modo[1].checked = false;
    assert.equal(P.aplicarModo(form), false);
    assert.ok(soloSemanas.every(b => b.hidden));
    assert.equal(elements.fecha_fin.required, false);
    assert.equal(etiqueta.textContent, 'Fecha');
});

test('aplicarModo sin opciones de modo usa «Varias semanas»', () => {
    const { form, elements } = entorno();
    delete elements.modo;
    delete elements.fecha_fin;
    form.querySelector = () => null;
    assert.equal(P.aplicarModo(form), true);
});

test('prepararNuevo desde una celda: instructor y día preseleccionados, modo «Un día»', () => {
    const { form, elements, quitar } = entorno();
    elements.competencia.value = 'resto anterior';
    P.prepararNuevo(form, { instructor: '7', inicio: '2026-11-18' });
    assert.equal(form.action, '/programacion/asignaciones');
    assert.equal(elements.instructor_id.value, '7');
    assert.equal(elements.fecha_inicio.value, '2026-11-18');
    assert.equal(elements.fecha_fin.value, '2026-11-18');
    assert.equal(elements.competencia.value, '');
    assert.deepEqual(marcados(elements.modo), ['dia']);
    assert.equal(quitar.hidden, true);
});

test('prepararNuevo sin datos (botón principal) deja el formulario vacío en «Varias semanas»', () => {
    const { form, elements } = entorno({ conContenedor: false });
    P.prepararNuevo(form);
    assert.equal(form.action, '/inicial');
    assert.equal(elements.instructor_id.value, '');
    assert.deepEqual(marcados(elements.modo), ['semanas']);
});

test('prepararEdicion rellena todos los campos y habilita «Quitar asignación»', () => {
    const { form, elements, quitar, eliminar } = entorno();
    P.prepararEdicion(form, {
        url: '/programacion/asignaciones/4', urlEliminar: '/programacion/asignaciones/4/eliminar',
        instructor: '2', ficha: '9', competencia: 'Ética', inicio: '2026-11-16', fin: '2026-11-28',
        dias: '34', jornada: 'noche', observacion: 'Ambiente 2',
    });
    assert.equal(form.action, '/programacion/asignaciones/4');
    assert.equal(elements.ficha_id.value, '9');
    assert.equal(elements.observacion.value, 'Ambiente 2');
    assert.deepEqual(marcados(elements.modo), ['semanas']);
    assert.deepEqual(marcados(elements.dias_semana), ['1', '5']);
    assert.deepEqual(marcados(elements.jornada), ['noche']);
    assert.equal(quitar.hidden, false);
    assert.equal(eliminar.action, '/programacion/asignaciones/4/eliminar');
});

test('prepararEdicion de un solo día sin nota ni formulario de eliminación', () => {
    const { form, elements } = entorno({ conEliminar: false });
    P.prepararEdicion(form, { url: '/a/1', instructor: '1', ficha: '1', competencia: 'X', inicio: '2026-11-18', fin: '2026-11-18', dias: '4', jornada: 'tarde' });
    assert.deepEqual(marcados(elements.modo), ['dia']);
    assert.equal(elements.observacion.value, '');
});

test('llenarCompetencias reemplaza las opciones del datalist', () => {
    const { datalist } = entorno();
    P.llenarCompetencias(datalist, ['Ética', 'Inglés']);
    assert.equal(datalist.innerHTML, '');
    assert.deepEqual(datalist.hijos.map(h => h.value), ['Ética', 'Inglés']);
    P.llenarCompetencias(datalist, null);
    assert.equal(datalist.hijos.length, 2);
});

test('cargarCompetencias consulta la ficha elegida y maneja errores sin inventar datos', async () => {
    const { form, elements, datalist } = entorno();
    const pedidas = [];
    elements.ficha_id.value = '12';
    const lista = await P.cargarCompetencias(form, url => { pedidas.push(url); return Promise.resolve({ ok: true, json: () => ['Ética'] }); });
    assert.deepEqual(pedidas, ['/programacion/fichas/12/competencias']);
    assert.deepEqual(lista, ['Ética']);
    assert.deepEqual(await P.cargarCompetencias(form, () => Promise.resolve({ ok: false })), []);
    assert.deepEqual(await P.cargarCompetencias(form, () => Promise.reject(new Error('red'))), []);
    elements.ficha_id.value = '';
    datalist.hijos = [];
    assert.deepEqual(await P.cargarCompetencias(form, () => assert.fail('no debe consultar')), []);
    const sinDatalist = entorno();
    sinDatalist.documento.ids['prg-competencias'] = null;
    assert.deepEqual(await P.cargarCompetencias(sinDatalist.form, () => assert.fail('no debe consultar')), []);
});

test('initProgramacion abre el formulario desde celdas y asignaciones, y reacciona a cambios y reinicio', async () => {
    const { documento, form, elements } = entorno();
    const abiertos = [];
    const cuadros = [];
    const ventana = {
        abrirModal: id => abiertos.push(id),
        fetch: () => Promise.resolve({ ok: true, json: () => [] }),
        requestAnimationFrame: callback => cuadros.push(callback),
    };
    assert.equal(P.initProgramacion(documento, ventana), form);

    const celda = { dataset: { instructor: '3', inicio: '2026-11-19' } };
    const clic = objetivo => documento.listeners.click[0]({ target: { closest: s => objetivo[s] ?? null } });
    clic({ '[data-prg-programar]': celda });
    assert.equal(elements.instructor_id.value, '3');
    clic({ '[data-prg-editar]': { dataset: { url: '/a/5', instructor: '4', ficha: '1', competencia: 'C', inicio: '2026-11-16', fin: '2026-11-20', dias: '31', jornada: 'manana' } } });
    assert.equal(form.action, '/a/5');
    clic({});
    documento.listeners.click[0]({ target: {} });
    assert.deepEqual(abiertos, ['modal-asignacion', 'modal-asignacion']);

    elements.modo[0].checked = true; elements.modo[1].checked = false;
    elements.modo[0].emitir('change');
    assert.equal(elements.fecha_fin.required, false);
    elements.ficha_id.emitir('change');

    elements.modo[0].checked = false; elements.modo[1].checked = true;
    form.emitir('reset');
    assert.equal(cuadros.length, 1);
    cuadros[0]();
    assert.equal(elements.fecha_fin.required, true);
});

test('initProgramacion sin formulario ni fetch no falla', async () => {
    assert.equal(P.initProgramacion({ getElementById: () => null }, {}), null);
    const { documento, elements } = entorno();
    P.initProgramacion(documento, { requestAnimationFrame() {} });
    documento.listeners.click[0]({ target: { closest: s => (s === '[data-prg-programar]' ? { dataset: {} } : null) } });
    elements.ficha_id.value = '1';
    elements.ficha_id.emitir('change');
    await new Promise(resolve => setImmediate(resolve));
});

test('en el navegador se expone window.Programacion y se inicia según el estado del documento', () => {
    const fs = require('node:fs');
    const vm = require('node:vm');
    const codigo = fs.readFileSync(require.resolve('../app/static/js/programacion.js'), 'utf8');
    for (const readyState of ['loading', 'complete']) {
        const eventos = {};
        const documento = { readyState, getElementById: () => null, addEventListener: (n, c) => { eventos[n] = c; } };
        const ventana = { document: documento };
        ventana.window = ventana;
        vm.runInNewContext(codigo, ventana);
        assert.equal(typeof ventana.Programacion.initProgramacion, 'function');
        if (readyState === 'loading') eventos.DOMContentLoaded();
        assert.equal(Boolean(eventos.DOMContentLoaded), readyState === 'loading');
    }
});

test('arrancar espera a DOMContentLoaded si el documento aún carga', () => {
    for (const readyState of ['loading', 'complete']) {
        const eventos = {};
        const documento = { readyState, getElementById: () => null, addEventListener: (n, c) => { eventos[n] = c; } };
        assert.equal(P.arrancar({ document: documento }), readyState !== 'loading');
        if (eventos.DOMContentLoaded) assert.equal(eventos.DOMContentLoaded(), null);
    }
});
