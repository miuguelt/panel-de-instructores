/**
 * Filtros de casos de seguimiento (app/static/js/seguimiento.js).
 *
 * Al abrir la página el filtro se aplica sin mover la vista: antes llamaba a
 * FiltroVista.aplicar, que desplazaba la página hasta la barra de filtros y
 * dejaba fuera de pantalla el título y el resumen.
 *
 * Se ejecuta con `node --test tests_js/seguimiento.test.cjs`.
 */
const assert = require('node:assert/strict');
const test = require('node:test');
const { initFollowupFilters, registrar } = require('../app/static/js/seguimiento.js');

class Nodo {
    constructor(atributos = {}) {
        this.dataset = { ...atributos.dataset };
        this.value = atributos.value ?? '';
        this.textContent = '';
        this.hidden = false;
        this.listeners = {};
        this.hijos = atributos.hijos ?? [];
    }
    addEventListener(tipo, callback) { (this.listeners[tipo] ??= []).push(callback); }
    disparar(tipo) { (this.listeners[tipo] ?? []).forEach(callback => callback({ target: this })); }
    querySelectorAll() { return this.hijos; }
}

function entorno({ conFiltroVista = true, sinControles = false } = {}) {
    const casos = [
        new Nodo({ dataset: { caseSearch: 'Ana Ruiz falta', casePriority: 'alta', caseStatus: 'activa' } }),
        new Nodo({ dataset: { caseSearch: 'Luis Peña tareas', casePriority: 'media', caseStatus: 'cerrada' } }),
    ];
    const elementos = {
        '[data-followup-list]': new Nodo({ hijos: casos }),
        '[data-followup-search]': new Nodo(),
        '[data-followup-priority]': new Nodo(),
        '[data-followup-status]': new Nodo(),
        '[data-followup-count]': new Nodo(),
        '[data-followup-empty]': new Nodo(),
        '.followup-filters': new Nodo(),
    };
    if (sinControles) delete elementos['[data-followup-search]'];
    const doc = { querySelector: selector => elementos[selector] ?? null };
    const desplazamientos = [];
    const win = conFiltroVista ? {
        FiltroVista: {
            normalizar: texto => String(texto ?? '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''),
            aplicar(ancla, accion) { desplazamientos.push(ancla); return accion(); },
            debounce: fn => fn,
        },
    } : {};
    return { doc, win, casos, elementos, desplazamientos };
}

test('al cargar filtra y cuenta sin mover la vista', () => {
    const e = entorno();
    initFollowupFilters(e.doc, e.win);
    assert.equal(e.elementos['[data-followup-count]'].textContent, '2 casos');
    assert.deepEqual(e.desplazamientos, [], 'la carga inicial no debe desplazar la página');
    assert.equal(e.elementos['[data-followup-list]'].dataset.followupReady, 'true');
});

test('los cambios del usuario sí conservan la posición de lectura', () => {
    const e = entorno();
    initFollowupFilters(e.doc, e.win);
    e.elementos['[data-followup-search]'].value = 'PEÑA';
    e.elementos['[data-followup-search]'].disparar('input');
    assert.equal(e.elementos['[data-followup-count]'].textContent, '1 caso');
    assert.equal(e.casos[0].hidden, true);
    assert.equal(e.desplazamientos.length, 1);
    e.elementos['[data-followup-search]'].value = '';
    e.elementos['[data-followup-priority]'].value = 'baja';
    e.elementos['[data-followup-priority]'].disparar('change');
    assert.equal(e.elementos['[data-followup-empty]'].hidden, false);
    e.elementos['[data-followup-priority]'].value = '';
    e.elementos['[data-followup-status]'].value = 'cerrada';
    e.elementos['[data-followup-status]'].disparar('change');
    assert.equal(e.elementos['[data-followup-count]'].textContent, '1 caso');
});

test('sin FiltroVista filtra directamente y normaliza tildes', () => {
    const e = entorno({ conFiltroVista: false });
    initFollowupFilters(e.doc, e.win);
    e.elementos['[data-followup-search]'].value = 'pena';
    e.elementos['[data-followup-search]'].disparar('input');
    assert.equal(e.elementos['[data-followup-count]'].textContent, '1 caso');
});

test('no se inicializa dos veces ni sin sus controles', () => {
    const e = entorno();
    initFollowupFilters(e.doc, e.win);
    e.elementos['[data-followup-count]'].textContent = 'sin cambios';
    initFollowupFilters(e.doc, e.win);
    assert.equal(e.elementos['[data-followup-count]'].textContent, 'sin cambios');
    const incompleto = entorno({ sinControles: true });
    initFollowupFilters(incompleto.doc, incompleto.win);
    assert.equal(incompleto.elementos['[data-followup-count]'].textContent, '');
    assert.doesNotThrow(() => initFollowupFilters({ querySelector: () => null }, {}));
});

test('se registra al cargar la página y tras cada intercambio de htmx', () => {
    const e = entorno();
    const cuerpo = new Nodo();
    const doc = { ...e.doc, body: cuerpo, listeners: {}, addEventListener(tipo, callback) { (this.listeners[tipo] ??= []).push(callback); } };
    registrar(doc, e.win);
    doc.listeners.DOMContentLoaded[0]();
    assert.equal(e.elementos['[data-followup-count]'].textContent, '2 casos');
    assert.equal(cuerpo.listeners['htmx:afterSwap'].length, 1);
    cuerpo.disparar('htmx:afterSwap');
});
