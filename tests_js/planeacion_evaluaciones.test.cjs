const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { filtrarAprendices, initPlaneacionEvaluaciones, tituloResultado } = require('../app/static/js/planeacion_evaluaciones.js');

const pendiente = { id: 1, nombre: 'Ángela Prueba', documento: '111', estado: 'pendiente', evaluados: 0, total: 2, resultados: [{ rap_id: '0', estado: 'pendiente', juicio: 'Por evaluar', instructor: null }] };
const parcial = { id: 2, nombre: 'Beatriz Prueba', documento: '222', estado: 'parcial', evaluados: 1, total: 2, resultados: [{ rap_id: '0', estado: 'evaluado', juicio: 'No aprobado (NA)', instructor: 'Instructor Uno', fecha: '01/09/2026' }, { rap_id: '1', estado: 'pendiente', juicio: 'Por evaluar', instructor: null }] };
const evaluado = { id: 3, nombre: '<img src=x onerror=alert(1)>', documento: '333', estado: 'evaluado', evaluados: 2, total: 2, resultados: [{ rap_id: '0', estado: 'evaluado', juicio: 'Aprobado (A)', instructor: 'Instructor Dos' }, { rap_id: '1', estado: 'evaluado', juicio: 'Aprobado (A)', instructor: 'Instructor Uno' }] };
const tramo = { nombre: 'Competencia', fase: 'ANÁLISIS', periodo: 'T1', resumen: { total: 3, evaluados: 1, pendientes: 2, parciales: 1 }, aprendices: [pendiente, parcial, evaluado], resultados: [
    { id: '0', codigo: '601390', nombre: 'Resultado uno', actividad: 'AP01', instructores_planeados: ['Planeado'], resumen: { total: 3, evaluados: 2, pendientes: 1 }, aprendices: [pendiente, { ...parcial, ...parcial.resultados[0] }, { ...evaluado, ...evaluado.resultados[0] }] },
    { id: '1', nombre: 'Resultado dos', resumen: { total: 3, evaluados: 1, pendientes: 2 }, aprendices: [] },
] };

test('El nombre del RAP muestra su código una sola vez', () => {
    assert.equal(tituloResultado({ codigo: '601390', nombre: '601390 - Resultado' }), '601390 - Resultado');
    assert.equal(tituloResultado({ codigo: '601390', nombre: 'Resultado' }), '601390 · Resultado');
    assert.equal(tituloResultado({ nombre: 'Resultado sin código' }), 'Resultado sin código');
});

class Elemento {
    constructor(tag = 'DIV') { Object.assign(this, { tagName: tag, children: [], listeners: {}, attrs: {}, dataset: {}, value: '', textContent: '', hidden: false, open: false }); }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    setAttribute(name, value) { this.attrs[name] = value; }
    addEventListener(name, fn) { (this.listeners[name] ??= []).push(fn); }
    dispatch(name, event = {}) { for (const fn of this.listeners[name] ?? []) fn({ target: this, ...event }); }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch('close'); }
    focus() { this.focused = true; }
    texto() { return this.textContent + this.children.map(child => child.texto()).join(' '); }
}

function entorno(datos = { 'tramo-0': tramo }) {
    const ids = {};
    for (const id of ['pl-evaluaciones', 'pl-evaluaciones-json', 'pl-evaluaciones-error', 'pl-evaluaciones-titulo', 'pl-evaluaciones-contexto', 'pl-evaluaciones-metricas', 'pl-evaluaciones-rap', 'pl-evaluaciones-instructor', 'pl-evaluaciones-buscar', 'pl-evaluaciones-lista', 'pl-evaluaciones-contador', 'pl-evaluaciones-descripcion', 'pl-evaluaciones-cerrar']) ids[id] = new Elemento();
    ids['pl-evaluaciones-json'].textContent = JSON.stringify(datos);
    const abrir = new Elemento('BUTTON'); abrir.dataset.evaluacionTarget = 'tramo-0';
    const filtros = ['pendiente', 'evaluado', 'todos'].map(estado => { const e = new Elemento('BUTTON'); e.dataset.evaluacionEstado = estado; return e; });
    const doc = { getElementById: id => ids[id] ?? null, createElement: tag => new Elemento(tag), querySelectorAll: selector => selector === '[data-evaluacion-target]' ? [abrir] : filtros };
    return { ids, abrir, filtros, doc };
}

test('Los filtros distinguen pendientes, parciales y evaluados y encuentran tildes o documento', () => {
    const filas = tramo.aprendices;
    assert.deepEqual(filtrarAprendices(filas, { estado: 'pendiente' }).map(a => a.id), [1, 2]);
    assert.deepEqual(filtrarAprendices(filas, { estado: 'evaluado' }).map(a => a.id), [3]);
    assert.deepEqual(filtrarAprendices(filas, { busqueda: 'angela' }).map(a => a.id), [1]);
    assert.deepEqual(filtrarAprendices(filas, { busqueda: '222' }).map(a => a.id), [2]);
    assert.deepEqual(filtrarAprendices(filas, { instructor: 'Instructor Uno' }).map(a => a.id), [2, 3]);
    assert.equal(filtrarAprendices(filas, { instructor: 'Planeado' }).length, 0);
    assert.equal(filtrarAprendices([], {}).length, 0);
    assert.equal(filtrarAprendices(filas).length, 3);
    assert.equal(filtrarAprendices([{ nombre: null, documento: null, estado: 'evaluado', instructor: 'No registrado' }], { instructor: 'No registrado' }).length, 1);
});

test('El diálogo abre el tramo, filtra, cambia de RAP y restaura el foco', () => {
    const { ids, abrir, filtros, doc } = entorno();
    initPlaneacionEvaluaciones(doc);
    abrir.dispatch('click');
    assert.equal(ids['pl-evaluaciones'].open, true);
    assert.equal(ids['pl-evaluaciones-titulo'].textContent, 'Competencia');
    assert.match(ids['pl-evaluaciones-lista'].texto(), /Ángela/);
    assert.match(ids['pl-evaluaciones-lista'].texto(), /Evaluación parcial/);
    assert.match(ids['pl-evaluaciones-metricas'].texto(), /Pendientes/);
    filtros[1].dispatch('click');
    assert.equal(filtros[1].attrs['aria-pressed'], 'true');
    assert.match(ids['pl-evaluaciones-lista'].texto(), /<img src=x/);
    assert.match(ids['pl-evaluaciones-lista'].texto(), /Instructor Dos/);
    filtros[2].dispatch('click');
    ids['pl-evaluaciones-instructor'].value = 'Instructor Uno'; ids['pl-evaluaciones-instructor'].dispatch('change');
    assert.match(ids['pl-evaluaciones-contador'].textContent, /2 de 3/);
    ids['pl-evaluaciones-buscar'].value = 'Sin coincidencias'; ids['pl-evaluaciones-buscar'].dispatch('input');
    assert.match(ids['pl-evaluaciones-lista'].texto(), /No hay aprendices/);
    ids['pl-evaluaciones-rap'].value = '0'; ids['pl-evaluaciones-rap'].dispatch('change');
    ids['pl-evaluaciones-buscar'].value = ''; ids['pl-evaluaciones-buscar'].dispatch('input');
    filtros[1].dispatch('click');
    assert.match(ids['pl-evaluaciones-lista'].texto(), /No aprobado/);
    assert.match(ids['pl-evaluaciones-descripcion'].textContent, /AP01/);
    ids['pl-evaluaciones-rap'].value = '1'; ids['pl-evaluaciones-rap'].dispatch('change');
    assert.match(ids['pl-evaluaciones-lista'].texto(), /No hay aprendices/);
    ids['pl-evaluaciones-rap'].value = ''; ids['pl-evaluaciones-rap'].dispatch('change');
    ids['pl-evaluaciones'].dispatch('click', { target: new Elemento() });
    assert.equal(ids['pl-evaluaciones'].open, true);
    ids['pl-evaluaciones-cerrar'].dispatch('click');
    assert.equal(abrir.focused, true);
    assert.equal(ids['pl-evaluaciones'].open, false);
    abrir.dispatch('click'); ids['pl-evaluaciones'].dispatch('click');
    assert.equal(ids['pl-evaluaciones'].open, false);
});

test('La inicialización tolera vista vacía, datos corruptos y tramos ausentes', () => {
    assert.equal(initPlaneacionEvaluaciones({ getElementById: () => null }), undefined);
    const roto = entorno(); roto.ids['pl-evaluaciones-json'].textContent = 'no es JSON';
    initPlaneacionEvaluaciones(roto.doc);
    assert.equal(roto.ids['pl-evaluaciones-error'].hidden, false);
    assert.match(roto.ids['pl-evaluaciones-error'].textContent, /Vuelva a cargar/);
    const vacio = entorno({}); initPlaneacionEvaluaciones(vacio.doc); vacio.abrir.dispatch('click');
    assert.equal(vacio.ids['pl-evaluaciones'].open, false);
    const sinGrupo = entorno({ 'tramo-0': { ...tramo, aprendices: [], resultados: [], resumen: { total: 0, evaluados: 0, pendientes: 0 } } });
    initPlaneacionEvaluaciones(sinGrupo.doc); sinGrupo.abrir.dispatch('click');
    assert.match(sinGrupo.ids['pl-evaluaciones-lista'].texto(), /No hay aprendices/);
});

test('El archivo se inicializa en el navegador', () => {
    const { doc } = entorno();
    vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/js/planeacion_evaluaciones.js'), 'utf8'), { document: doc });
});
