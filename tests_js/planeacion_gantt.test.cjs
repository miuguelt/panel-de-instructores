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
    dispatch(nombre, target = this, extra = {}) { for (const callback of this.listeners[nombre] ?? []) callback({ target, preventDefault() {}, stopPropagation() {}, ...extra }); }
    click() { this.dispatch('click'); }
    setAttribute(nombre, valor) { this.attrs[nombre] = valor; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch('close'); }
    focus() { this.focused = true; }
    closest(selector) {
        if (selector === '[data-pedagogia-filtro]') return this.dataset.pedagogiaFiltro ? this : null;
        return this.dataset.pedagogicoTarget ? this : null;
    }
    contains(elemento) { return elemento === this; }
}

function entorno() {
    const ids = {};
    for (const id of ['seccion-gantt', 'pl-gantt-columnas', 'pl-gantt-evento', 'pl-gantt-evento-titulo', 'pl-gantt-evento-contexto', 'pl-gantt-evento-cerrar', 'pl-gantt-contador', 'pl-gantt-vacio', 'modal-pedagogico', 'pl-modal-close-btn']) ids[id] = new Elemento();
    const paneles = [new Elemento({ nombre: '<img src=x> Inducción', contexto: 'ANÁLISIS · T1' }), new Elemento({ nombre: 'Competencia transversal', contexto: 'PLANEACIÓN · T2' })];
    paneles.forEach((panel, i) => {
        panel.id = 'evento-' + i; panel.hidden = true;
        panel.tabs = ['resumen', 'resultados', 'aprendices', 'pedagogia'].map(ganttTab => new Elemento({ ganttTab }));
        panel.panes = panel.tabs.map(tab => new Elemento({ ganttPane: tab.dataset.ganttTab }));
        panel.querySelectorAll = selector => selector === '[data-gantt-tab]' ? panel.tabs : panel.panes;
    });
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
    doc.media = new Elemento();
    doc.media.matches = false;
    doc.defaultView = { requestAnimationFrame: callback => doc.frames.push(callback), matchMedia: () => doc.media };
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

test('La columna se oculta en celular y el control conserva la decisión al cambiar el ancho', () => {
    const e = entorno();
    e.doc.media.matches = true;
    initPlaneacionGantt(e.doc);
    const control = e.ids['pl-gantt-columnas'];
    assert.equal(e.ids['seccion-gantt']['is-labels-hidden'], true);
    assert.equal(control.attrs['aria-expanded'], 'false');
    assert.equal(control.textContent, 'Mostrar columna');
    control.dispatch('click');
    assert.equal(e.ids['seccion-gantt']['is-labels-hidden'], false);
    assert.equal(control.attrs['aria-expanded'], 'true');
    assert.equal(control.textContent, 'Ocultar columna');
    e.doc.media.dispatch('change', e.doc.media, { matches: true });
    assert.equal(e.ids['seccion-gantt']['is-labels-hidden'], false);
    control.dispatch('click');
    assert.equal(control.attrs['aria-pressed'], 'true');
    assert.equal(e.ids['seccion-gantt']['is-labels-hidden'], true);
    const automatico = entorno();
    initPlaneacionGantt(automatico.doc);
    automatico.doc.media.dispatch('change', automatico.doc.media, { matches: true });
    assert.equal(automatico.ids['seccion-gantt']['is-labels-hidden'], true);
});

test('Las pestañas muestran solo su contenido y admiten flechas, Inicio y Fin', () => {
    const e = entorno();
    initPlaneacionGantt(e.doc);
    e.abrir[0].dispatch('click');
    const { tabs, panes } = e.paneles[0];
    assert.deepEqual(panes.map(p => p.hidden), [false, true, true, true]);
    tabs[2].dispatch('click');
    assert.deepEqual(panes.map(p => p.hidden), [true, true, false, true]);
    assert.equal(tabs[2].attrs['aria-selected'], 'true');
    assert.equal(tabs[0].tabIndex, -1);
    for (const [desde, key, destino] of [[2, 'ArrowRight', 3], [3, 'ArrowRight', 0], [0, 'ArrowLeft', 3], [3, 'Home', 0], [0, 'End', 3]]) {
        tabs[desde].dispatch('keydown', tabs[desde], { key });
        assert.equal(tabs[destino].attrs['aria-selected'], 'true');
        assert.equal(tabs[destino].tabIndex, 0);
        assert.equal(tabs[destino].focused, true);
        assert.equal(panes[destino].hidden, false);
    }
    tabs[3].dispatch('keydown', tabs[3], { key: 'Tab' });
    assert.equal(tabs[3].attrs['aria-selected'], 'true');
    e.ids['pl-gantt-evento-cerrar'].dispatch('click');
    e.abrir[1].dispatch('click');
    assert.deepEqual(e.paneles[1].panes.map(p => p.hidden), [false, true, true, true]);
    e.ids['pl-gantt-evento-cerrar'].dispatch('click');
    e.abrir[0].dispatch('click');
    assert.deepEqual(panes.map(p => p.hidden), [false, true, true, true]);
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
    const ficha = new Elemento({ pedagogicoTarget: 'Inducción' });
    ficha.addEventListener('click', () => e.ids['modal-pedagogico'].classList.toggle('is-open', true));
    e.ids['pl-gantt-evento'].dispatch('click', ficha);
    assert.equal(e.ids['modal-pedagogico'].classList.contains('is-open'), false);
    e.doc.dispatch('click');
    e.doc.avanzarFrames();
    assert.equal(e.ids['modal-pedagogico'].classList.contains('is-open'), true);
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

test('El buscador y filtros pedagógicos actualizan visibilidad y anuncian coincidencias', () => {
    const e = entorno();
    initPlaneacionGantt(e.doc);
    e.abrir[0].dispatch('click');

    const item1 = new Elemento();
    item1.classList.toggle('pl-pedagogia-item', true);
    item1.textContent = 'Bases de datos SQL y PostgreSQL';

    const item2 = new Elemento();
    item2.classList.toggle('pl-pedagogia-item', true);
    item2.textContent = 'Algoritmos y estructuras de datos';

    const contador = new Elemento();
    const input = new Elemento();
    input.classList.toggle('pl-pedagogia-search', true);
    input.value = 'sql';

    const panel = e.paneles[0];
    panel.querySelectorAll = selector => selector === '.pl-pedagogia-item' ? [item1, item2] : [];
    panel.querySelector = selector => selector === '.pl-pedagogia-match-count' ? contador : null;

    e.ids['pl-gantt-evento'].dispatch('input', input);
    assert.equal(item1.hidden, false);
    assert.equal(item2.hidden, true);
    assert.equal(contador.textContent, '1 coincidencias');

    input.value = '';
    e.ids['pl-gantt-evento'].dispatch('input', input);
    assert.equal(item1.hidden, false);
    assert.equal(item2.hidden, false);
    assert.equal(contador.textContent, '');

    const btnTodos = new Elemento({ pedagogiaFiltro: 'todos' });
    const btnCriterios = new Elemento({ pedagogiaFiltro: 'criterios' });
    const secCriterios = new Elemento({ pedagogiaSeccion: 'criterios' });
    const secProcesos = new Elemento({ pedagogiaSeccion: 'procesos' });

    panel.querySelectorAll = selector => {
        if (selector === '[data-pedagogia-filtro]') return [btnTodos, btnCriterios];
        if (selector === '[data-pedagogia-seccion]') return [secCriterios, secProcesos];
        return [];
    };

    e.ids['pl-gantt-evento'].dispatch('click', btnCriterios);
    assert.equal(secCriterios.hidden, false);
    assert.equal(secProcesos.hidden, true);
    assert.equal(btnCriterios.attrs['aria-pressed'], 'true');

    e.ids['pl-gantt-evento'].dispatch('click', btnTodos);
    assert.equal(secCriterios.hidden, false);
    assert.equal(secProcesos.hidden, false);
});
