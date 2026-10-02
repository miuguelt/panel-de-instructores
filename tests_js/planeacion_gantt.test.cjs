const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { initPlaneacionGantt } = require('../app/static/js/planeacion_gantt.js');

class Elemento {
    constructor(dataset = {}) {
        Object.assign(this, { dataset, hidden: false, listeners: {}, attrs: {}, textContent: '', open: false });
        this.classList = { toggle: (nombre, activo) => { this[nombre] = activo; }, contains: nombre => Boolean(this[nombre]) };
    }
    addEventListener(nombre, callback) { (this.listeners[nombre] ??= []).push(callback); }
    dispatch(nombre, target = this) { for (const callback of this.listeners[nombre] ?? []) callback({ target }); }
    setAttribute(nombre, valor) { this.attrs[nombre] = valor; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch('close'); }
    focus() { this.focused = true; }
    closest() { return this.dataset.pedagogicoTarget ? this : null; }
    contains(elemento) { return elemento === this; }
}

function entorno() {
    const ids = {};
    for (const id of ['seccion-gantt', 'pl-gantt-evento', 'pl-gantt-evento-titulo', 'pl-gantt-evento-contexto', 'pl-gantt-evento-cerrar', 'pl-gantt-contador', 'pl-gantt-vacio', 'modal-pedagogico', 'pl-modal-close-btn']) ids[id] = new Elemento();
    const paneles = [new Elemento({ nombre: '<img src=x> Inducción', contexto: 'ANÁLISIS · T1' }), new Elemento({ nombre: 'Competencia transversal', contexto: 'PLANEACIÓN · T2' })];
    paneles.forEach((panel, i) => { panel.id = 'evento-' + i; panel.hidden = true; });
    const abrir = paneles.map(panel => new Elemento({ ganttTarget: panel.id }));
    const filas = [new Elemento({ type: 'tecnicas', status: 'atrasadas' }), new Elemento({ type: 'flexibles', status: 'al_dia' })];
    const grupos = filas.map(fila => { const grupo = new Elemento(); grupo.querySelectorAll = () => [fila]; return grupo; });
    const filtros = ['all', 'tecnicas', 'atrasadas', 'flexibles'].map(filter => new Elemento({ filter }));
    const reset = new Elemento();
    ids['seccion-gantt'].querySelectorAll = selector => ({ '[data-gantt-target]': abrir, '.pl-filter-btn': filtros, '.pl-gantt-item': filas, '.pl-gantt-grupo': grupos })[selector] || [];
    ids['seccion-gantt'].querySelector = () => reset;
    ids['pl-gantt-evento'].querySelectorAll = () => paneles;
    const doc = new Elemento();
    doc.getElementById = id => ids[id] ?? null;
    doc.frames = [];
    doc.defaultView = { requestAnimationFrame: callback => doc.frames.push(callback) };
    doc.avanzarFrame = () => { for (const callback of doc.frames.splice(0)) callback(); };
    doc.avanzarFrames = () => { doc.avanzarFrame(); doc.avanzarFrame(); };
    return { ids, paneles, abrir, filas, grupos, filtros, reset, doc };
}

test('La línea de tiempo abre el evento correcto, cierra y devuelve el foco', () => {
    const e = entorno();
    initPlaneacionGantt(e.doc);
    e.abrir[0].dispatch('click');
    assert.equal(e.ids['pl-gantt-evento'].open, true);
    assert.equal(e.ids['pl-gantt-evento-titulo'].textContent, '<img src=x> Inducción');
    assert.equal(e.ids['pl-gantt-evento-contexto'].textContent, 'ANÁLISIS · T1');
    assert.deepEqual(e.paneles.map(p => p.hidden), [false, true]);
    e.ids['pl-gantt-evento'].dispatch('click', e.paneles[0]);
    assert.equal(e.ids['pl-gantt-evento'].open, true);
    e.ids['pl-gantt-evento-cerrar'].dispatch('click');
    assert.equal(e.ids['pl-gantt-evento'].open, false);
    assert.equal(e.abrir[0].focused, true);
    e.abrir[1].dispatch('click');
    assert.equal(e.ids['pl-gantt-evento-titulo'].textContent, 'Competencia transversal');
    assert.deepEqual(e.paneles.map(p => p.hidden), [true, false]);
    e.ids['pl-gantt-evento'].dispatch('click');
    assert.equal(e.ids['pl-gantt-evento'].open, false);
    assert.equal(e.abrir[1].focused, true);
    e.abrir[0].dispatch('click');
    e.ids['pl-gantt-evento'].dispatch('click', new Elemento({ pedagogicoTarget: 'Inducción' }));
    assert.equal(e.ids['pl-gantt-evento'].open, false);
});

test('Los filtros ocultan fases vacías, anuncian el conteo y permiten restablecer', () => {
    const e = entorno();
    initPlaneacionGantt(e.doc);
    assert.equal(e.ids['pl-gantt-contador'].textContent, '2 de 2 competencias');
    for (const indice of [1, 2, 3]) {
        e.filtros[indice].dispatch('click');
        const visible = indice === 3 ? 1 : 0;
        assert.equal(e.filas[visible].hidden, false);
        assert.equal(e.filas[1 - visible].hidden, true);
        assert.equal(e.grupos[1 - visible].hidden, true);
        assert.equal(e.filtros[indice].attrs['aria-pressed'], 'true');
        assert.equal(e.filtros[0].attrs['aria-pressed'], 'false');
        assert.equal(e.ids['pl-gantt-contador'].textContent, '1 de 2 competencias');
    }
    e.filas[0].dataset.status = 'al_dia';
    e.filtros[2].dispatch('click');
    assert.equal(e.ids['pl-gantt-vacio'].hidden, false);
    assert.equal(e.ids['pl-gantt-contador'].textContent, '0 de 2 competencias');
    e.reset.dispatch('click');
    assert.equal(e.ids['pl-gantt-vacio'].hidden, true);
    assert.ok(e.filas.every(fila => !fila.hidden));
    assert.ok(e.grupos.every(grupo => !grupo.hidden));
    assert.equal(e.filtros[0]['is-active'], true);
});

test('La vista vacía y un evento ausente no abren datos de otro tramo', () => {
    assert.equal(initPlaneacionGantt({ getElementById: () => null }), undefined);
    const e = entorno();
    e.abrir[0].dataset.ganttTarget = 'inexistente';
    initPlaneacionGantt(e.doc);
    e.abrir[0].dispatch('click');
    assert.equal(e.ids['pl-gantt-evento'].open, false);
    assert.ok(e.paneles.every(panel => panel.hidden));
    e.ids['pl-gantt-evento'].dispatch('close');
    assert.equal(e.abrir[0].focused, undefined);
});

test('El cambio a la ficha pedagógica conserva el foco y permite regresar al evento', () => {
    const e = entorno();
    initPlaneacionGantt(e.doc);
    e.abrir[0].dispatch('click');
    // El cierre nativo se anuncia después de que el controlador compartido abra la ficha.
    e.ids['pl-gantt-evento'].dispatch('click', new Elemento({ pedagogicoTarget: 'Inducción' }));
    e.doc.dispatch('click');
    e.ids['modal-pedagogico'].classList.toggle('is-open', true);
    e.doc.avanzarFrames();
    e.ids['pl-gantt-evento'].dispatch('close');
    e.doc.avanzarFrames();
    assert.equal(e.ids['pl-modal-close-btn'].focused, true);
    e.abrir[0].focused = false;
    e.doc.dispatch('click');
    e.doc.avanzarFrames();
    assert.equal(e.abrir[0].focused, false);
    e.doc.activeElement = e.ids['modal-pedagogico'];
    e.ids['pl-modal-close-btn'].focused = false;
    e.doc.dispatch('keydown');
    e.doc.avanzarFrames();
    assert.equal(e.ids['pl-modal-close-btn'].focused, false);
    e.ids['modal-pedagogico'].classList.toggle('is-open', false);
    e.doc.dispatch('keydown');
    e.doc.avanzarFrames();
    assert.equal(e.abrir[0].focused, true);
    e.abrir[0].focused = false;
    e.doc.dispatch('click');
    e.doc.avanzarFrames();
    assert.equal(e.abrir[0].focused, false);
});

test('El cronograma se inicializa al cargarlo en el navegador', () => {
    const e = entorno();
    vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/js/planeacion_gantt.js'), 'utf8'), { document: e.doc });
    e.abrir[0].dispatch('click');
    assert.equal(e.ids['pl-gantt-evento'].open, true);
});
