const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { initPlaneacionNavigation } = require('../app/static/js/planeacion_navegacion.js');

class Elemento {
    constructor(tagName = 'DIV', { id = '', classes = '', text = '' } = {}) {
        Object.assign(this, { tagName, id, className: classes, textContent: text, dataset: {}, children: [], attrs: {}, listeners: {}, parentElement: null });
        this.classList = {
            contains: (name) => this.className.split(' ').includes(name),
            add: (...names) => { this.className = [...new Set([...this.className.split(' '), ...names])].join(' '); },
            remove: (...names) => { this.className = this.className.split(' ').filter(name => !names.includes(name)).join(' '); },
            toggle: (name, force) => { const next = force ?? !this.classList.contains(name); this.classList[next ? 'add' : 'remove'](name); return next; },
        };
    }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    removeAttribute(name) { delete this.attrs[name]; }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    addEventListener(name, callback) { (this.listeners[name] ??= []).push(callback); }
    dispatch(name, detail = {}) {
        const event = { target: this, currentTarget: this, preventDefault() {}, ...detail };
        for (const callback of this.listeners[name] ?? []) callback.call(this, event);
        if (this.parentElement) this.parentElement.dispatch(name, event);
    }
    matches(selector) {
        if (selector.startsWith('#')) return this.id === selector.slice(1);
        if (selector === '[id]') return Boolean(this.id);
        if (selector.includes('section.pl-card')) return this.tagName === 'SECTION' && this.classList.contains('pl-card') && (!selector.includes(':not') || !this.classList.contains('pl-carga-card'));
        if (selector.includes('h2') || selector.includes('h3')) return ['H2', 'H3'].includes(this.tagName);
        if (selector.includes('a[href') || selector === '[href^="#"]') return this.tagName === 'A' && (this.getAttribute('href') || '').startsWith('#');
        const cssClass = selector.match(/\.([\w-]+)(?:\[.*\])?$/)?.[1];
        if (cssClass) return this.classList.contains(cssClass);
        return selector.toUpperCase() === this.tagName;
    }
    querySelectorAll(selector) {
        const last = selector.trim().split(/\s+/).at(-1);
        return this.children.flatMap(child => [...(child.matches(last) ? [child] : []), ...child.querySelectorAll(last)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) ?? null; }
    focus() { this.focused = true; }
}

function entorno({ almacenado = {}, hash = '', fallaStorage = false, observer = true, conPagina = true } = {}) {
    const root = new Elemento('DOCUMENT');
    root.createElement = (tag) => new Elemento(tag.toUpperCase());
    root.getElementById = (id) => root.querySelector('#' + id);
    const page = root.appendChild(new Elemento('DIV', { classes: conPagina ? 'pl-page' : '' }));
    page.dataset.fichaId = '42';
    const sections = ['seccion-resumen', 'seccion-gantt', 'seccion-curva-s'].map((id, index) => {
        const section = page.appendChild(new Elemento('SECTION', { id, classes: 'pl-card' }));
        section.dataset.collapseDefault = index ? 'cerrado' : 'abierto';
        const head = section.appendChild(new Elemento('DIV', { classes: 'pl-card-head' }));
        head.appendChild(new Elemento('H2', { text: ['Resumen', 'Cronograma', 'Curva S'][index] }));
        return section;
    });
    const carga = page.appendChild(new Elemento('SECTION', { id: 'centro-carga', classes: 'pl-card pl-carga-card' }));
    const actualizar = carga.appendChild(new Elemento('DETAILS', { classes: 'pl-carga-actualizar' }));
    const more = page.appendChild(new Elemento('DETAILS', { classes: 'pl-nav-more' }));
    const links = sections.map((section, index) => {
        const link = (index === 2 ? more : page).appendChild(new Elemento('A', { classes: 'pl-subnav-link' }));
        link.setAttribute('href', '#' + section.id);
        return link;
    });
    const cargar = page.appendChild(new Elemento('A'));
    cargar.setAttribute('href', '#centro-carga');
    const expandir = page.appendChild(new Elemento('BUTTON', { id: 'pl-expandir-todo' }));
    const colapsar = page.appendChild(new Elemento('BUTTON', { id: 'pl-colapsar-todo' }));
    const values = new Map(Object.entries(almacenado));
    const win = new Elemento('WINDOW');
    win.location = { hash };
    win.getComputedStyle = () => ({ display: 'flex' });
    win.localStorage = {
        getItem(key) { if (fallaStorage) throw new Error('Almacenamiento no disponible'); return values.get(key) ?? null; },
        setItem(key, value) { if (fallaStorage) throw new Error('Almacenamiento no disponible'); values.set(key, value); },
    };
    const observado = [];
    let notificar;
    if (observer) win.IntersectionObserver = class {
        constructor(callback) { notificar = callback; }
        observe(element) { observado.push(element); }
    };
    return { root, win, page, sections, links, cargar, actualizar, more, expandir, colapsar, values, observado, notify: entries => notificar(entries) };
}

test('crea controles accesibles, restaura el estado por ficha y conserva cambios', () => {
    const e = entorno({ almacenado: { 'pl-collapse:f42:seccion-resumen': '1', 'pl-collapse:f42:seccion-gantt': '0' } });
    initPlaneacionNavigation(e.root, e.win);
    const toggle = e.sections[0].querySelector('.pl-card-toggle');
    assert.ok(toggle);
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
    assert.match(toggle.getAttribute('aria-label'), /Resumen/);
    assert.equal(e.sections[1].classList.contains('is-collapsed'), false);
    toggle.dispatch('click');
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(e.values.get('pl-collapse:f42:seccion-resumen'), '0');
    e.colapsar.dispatch('click');
    assert.ok(e.sections.every(section => section.classList.contains('is-collapsed')));
    e.expandir.dispatch('click');
    assert.ok(e.sections.every(section => !section.classList.contains('is-collapsed')));
});

test('seguir enlaces abre el destino y los análisis secundarios', () => {
    const e = entorno();
    initPlaneacionNavigation(e.root, e.win);
    e.links[2].dispatch('click');
    assert.equal(e.sections[2].classList.contains('is-collapsed'), false);
    assert.equal(e.more.open, true);
    assert.equal(e.links[2].getAttribute('aria-current'), 'location');
    e.cargar.dispatch('click');
    assert.equal(e.actualizar.open, true);
});

test('hash inicial y hashchange abren secciones aunque estén guardadas cerradas', () => {
    const e = entorno({ hash: '#seccion-curva-s', almacenado: { 'pl-collapse:f42:seccion-curva-s': '1' } });
    initPlaneacionNavigation(e.root, e.win);
    assert.equal(e.sections[2].classList.contains('is-collapsed'), false);
    assert.equal(e.more.open, true);
    e.win.location.hash = '#centro-carga';
    e.win.dispatch('hashchange');
    assert.equal(e.actualizar.open, true);
    e.win.location.hash = '#destino-inexistente';
    assert.doesNotThrow(() => e.win.dispatch('hashchange'));
});

test('el observador actualiza el enlace activo sin desplegar Más análisis', () => {
    const e = entorno();
    initPlaneacionNavigation(e.root, e.win);
    assert.ok(e.observado.includes(e.sections[2]));
    e.notify([{ target: e.sections[0], isIntersecting: false }, { target: e.sections[2], isIntersecting: true }]);
    assert.equal(e.links[2].getAttribute('aria-current'), 'location');
    assert.equal(e.links[2].classList.contains('is-active'), true);
    assert.equal(e.links[0].getAttribute('aria-current'), null);
    assert.notEqual(e.more.open, true);
});

test('funciona sin almacenamiento, sin observador y fuera de la página', () => {
    const e = entorno({ fallaStorage: true, observer: false });
    assert.doesNotThrow(() => initPlaneacionNavigation(e.root, e.win));
    e.sections[0].querySelector('.pl-card-toggle').dispatch('click');
    assert.equal(e.sections[0].classList.contains('is-collapsed'), true);
    e.links[0].dispatch('click');
    assert.equal(e.sections[0].classList.contains('is-collapsed'), false);
    const vacio = entorno({ conPagina: false });
    assert.doesNotThrow(() => initPlaneacionNavigation(vacio.root, vacio.win));
});

test('tolera encabezados incompletos y abre destinos interiores sin bloquear hashes inválidos', () => {
    const e = entorno();
    e.sections[0].children = [];
    const head = e.sections[1].children[0];
    head.children = [];
    const destino = e.sections[1].appendChild(new Elemento('DIV', { id: 'contenido-interior' }));
    e.win.getComputedStyle = () => ({ display: 'block' });
    e.links[0].classList.add('is-active');
    initPlaneacionNavigation(e.root, e.win);
    assert.equal(e.sections[0].querySelector('.pl-card-toggle'), null);
    assert.equal(e.links[0].getAttribute('aria-current'), 'location');
    assert.equal(head.classList.contains('has-toggle'), true);
    assert.equal(head.querySelector('.pl-card-toggle').getAttribute('aria-label'), 'Expandir sección');
    e.win.location.hash = '#' + destino.id;
    e.win.dispatch('hashchange');
    assert.equal(e.sections[1].classList.contains('is-collapsed'), false);
    assert.equal(e.links[1].getAttribute('aria-current'), 'location');
    for (const hash of ['#', '#%', '#seccion-resumen']) {
        e.win.location.hash = hash;
        assert.doesNotThrow(() => e.win.dispatch('hashchange'));
    }
});

test('el script se inicializa automáticamente en un navegador', () => {
    const e = entorno({ hash: '#centro-carga' });
    const ruta = path.resolve(__dirname, '../app/static/js/planeacion_navegacion.js');
    vm.runInNewContext(fs.readFileSync(ruta, 'utf8'), { document: e.root, window: e.win }, { filename: ruta });
    assert.equal(e.actualizar.open, true);
    assert.equal(e.sections[1].querySelector('.pl-card-toggle').getAttribute('aria-expanded'), 'false');
});
