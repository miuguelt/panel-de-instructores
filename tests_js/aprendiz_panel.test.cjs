/**
 * Panel del aprendiz (app/static/js/aprendiz_panel.js).
 *
 * Usa un DOM simulado mínimo: cada prueba arma solo los elementos que el
 * comportamiento necesita y verifica el resultado observable (clases, textos,
 * atributos, eventos emitidos y llamadas a la red).
 *
 * Se ejecuta con `node --test tests_js/aprendiz_panel.test.cjs`.
 */
const assert = require('node:assert/strict');
const test = require('node:test');
const panel = require('../app/static/js/aprendiz_panel.js');

class Elemento {
    constructor(tag = 'div', atributos = {}) {
        this.tagName = tag.toUpperCase();
        this.attrs = {};
        this.dataset = {};
        this.children = [];
        this.listeners = {};
        this.style = {};
        this.textContent = '';
        this.value = '';
        this.className = '';
        this.parentElement = null;
        const clases = () => this.className.split(' ').filter(Boolean);
        this.classList = {
            contains: nombre => clases().includes(nombre),
            add: nombre => { if (!clases().includes(nombre)) this.className = [...clases(), nombre].join(' '); },
            remove: nombre => { this.className = clases().filter(c => c !== nombre).join(' '); },
            toggle: (nombre, activo) => (activo ? this.classList.add(nombre) : this.classList.remove(nombre)),
        };
        for (const [nombre, valor] of Object.entries(atributos)) this.setAttribute(nombre, valor);
    }
    setAttribute(nombre, valor) {
        if (nombre === 'class') { this.className = String(valor); return; }
        if (nombre === 'id') this.id = String(valor);
        this.attrs[nombre] = String(valor);
        if (nombre.startsWith('data-')) this.dataset[nombre.slice(5).replace(/-([a-z])/g, (_, l) => l.toUpperCase())] = String(valor);
    }
    getAttribute(nombre) { return nombre === 'id' ? this.id ?? null : this.attrs[nombre] ?? null; }
    appendChild(hijo) { this.children.push(hijo); hijo.parentElement = this; return hijo; }
    replaceChildren(...hijos) { this.children = []; hijos.forEach(h => this.appendChild(h)); }
    addEventListener(tipo, callback) { (this.listeners[tipo] ??= []).push(callback); }
    async disparar(tipo, extra = {}) {
        for (const callback of this.listeners[tipo] ?? []) await callback({ target: this, preventDefault() { this.prevenido = true; }, ...extra });
    }
    coincide(selector) {
        const id = selector.match(/^#([\w-]+)$/);
        if (id) return this.id === id[1];
        const clase = selector.match(/^([a-z]*)\.([\w-]+)$/);
        if (clase) return (!clase[1] || this.tagName === clase[1].toUpperCase()) && this.classList.contains(clase[2]);
        const attr = selector.match(/^([a-z]*)\[([\w-]+)(?:="([^"]*)")?\]$/);
        if (attr) return (!attr[1] || this.tagName === attr[1].toUpperCase())
            && Object.hasOwn(this.attrs, attr[2]) && (attr[3] === undefined || this.attrs[attr[2]] === attr[3]);
        throw new Error('Selector no soportado: ' + selector);
    }
    querySelectorAll(selector) { return this.children.flatMap(h => [...(h.coincide(selector) ? [h] : []), ...h.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    scrollIntoView(opciones) { this.desplazado = opciones; }
    focus(opciones) { this.enfocado = opciones ?? true; }
    get textos() { return [this.textContent, ...this.children.map(h => h.textos)].join(''); }
}

function documento() {
    const doc = new Elemento('document');
    doc.getElementById = id => doc.querySelector('#' + id);
    doc.createElement = tag => new Elemento(tag);
    doc.createTextNode = texto => Object.assign(new Elemento('#text'), { textContent: texto });
    return doc;
}

function agregar(padre, tag, atributos = {}, propiedades = {}) {
    return Object.assign(padre.appendChild(new Elemento(tag, atributos)), propiedades);
}

function ventana({ hash = '', guardada = null, almacenamientoFalla = false, respuesta } = {}) {
    const eventos = [];
    const win = new Elemento('window');
    Object.assign(win, {
        location: { hash, recargada: false, reload() { this.recargada = true; } },
        history: { anclas: [], replaceState(_a, _b, ancla) { this.anclas.push(ancla); } },
        localStorage: {
            datos: guardada ? { 'sena_learner_active_tab_9': guardada } : {},
            getItem(clave) { if (almacenamientoFalla) throw new Error('bloqueado'); return this.datos[clave] ?? null; },
            setItem(clave, valor) { if (almacenamientoFalla) throw new Error('bloqueado'); this.datos[clave] = valor; },
        },
        CustomEvent: class { constructor(tipo, init) { this.type = tipo; this.detail = init.detail; } },
        dispatchEvent(evento) { eventos.push(evento); },
        abrirModal(modal) { modal.abierto = true; },
        cerrarModal(modal) { modal.abierto = false; },
        peticiones: [],
        async fetch(url, opciones) { win.peticiones.push({ url, opciones }); return respuesta; },
    });
    win.eventos = eventos;
    return win;
}

// ---------------------------------------------------------------- Funciones puras

test('la pestaña inicial respeta el ancla, luego la guardada y por último el resumen', () => {
    assert.equal(panel.pestanaInicial('#seccion-tareas', 'grupo'), 'evidencias');
    assert.equal(panel.pestanaInicial('#tab-juicios', null), 'juicios');
    assert.equal(panel.pestanaInicial('', 'rendimiento'), 'rendimiento');
    assert.equal(panel.pestanaInicial('#otra', 'inventada'), 'resumen');
    assert.equal(panel.pestanaInicial('', null), 'resumen');
});

test('un ancla abre la pestaña que contiene su destino', () => {
    const seccion = { getAttribute: nombre => (nombre === 'data-learner-tab' ? 'evidencias' : null) };
    const destinos = {
        'experiencia-tarea-7': { closest: () => seccion },
        'suelto': { closest: () => null },
    };
    const doc = { getElementById: id => destinos[id] || null };
    assert.equal(panel.pestanaDeAncla('#seccion-juicios', doc), 'juicios');
    assert.equal(panel.pestanaDeAncla('#experiencia-tarea-7', doc), 'evidencias');
    assert.equal(panel.pestanaDeAncla('#suelto', doc), null);
    assert.equal(panel.pestanaDeAncla('#no-existe', doc), null);
    assert.equal(panel.pestanaDeAncla('#', doc), null);
    assert.equal(panel.pestanaDeAncla('#%E0', doc), null);
});

test('las fechas se convierten a ISO y al formato colombiano', () => {
    assert.equal(panel.aIso(2026, 0, 5), '2026-01-05');
    assert.equal(panel.formatoFecha('2026-11-21'), '21/11/2026');
});

test('el filtro de evidencias combina búsqueda y chip', () => {
    const pendiente = { titulo: 'diseño de base de datos', descripcion: 'modelo', estado: 'pending', urgente: true, extemporanea: false, plan: true };
    const entregada = { titulo: 'informe', descripcion: '', estado: 'delivered', urgente: false, extemporanea: true, plan: false };
    assert.equal(panel.coincideEvidencia(pendiente, 'all', ''), true);
    assert.equal(panel.coincideEvidencia(pendiente, 'all', 'modelo'), true);
    assert.equal(panel.coincideEvidencia(pendiente, 'all', 'informe'), false);
    assert.equal(panel.coincideEvidencia(pendiente, 'pending', ''), true);
    assert.equal(panel.coincideEvidencia(pendiente, 'urgent', ''), true);
    assert.equal(panel.coincideEvidencia(entregada, 'urgent', ''), false);
    assert.equal(panel.coincideEvidencia(entregada, 'extemporaneous', ''), false, 'una entregada no es extemporánea pendiente');
    assert.equal(panel.coincideEvidencia({ ...pendiente, extemporanea: true }, 'extemporaneous', ''), true);
    assert.equal(panel.coincideEvidencia(pendiente, 'plan', ''), true);
    assert.equal(panel.coincideEvidencia(entregada, 'plan', ''), false);
    assert.equal(panel.coincideEvidencia(entregada, 'delivered', ''), true);
    assert.equal(panel.coincideEvidencia(pendiente, 'delivered', ''), false);
});

test('los conteos de los chips separan pendientes, urgentes, extemporáneas, planes y entregadas', () => {
    const lista = [
        { estado: 'pending', urgente: true, extemporanea: false, plan: false },
        { estado: 'pending', urgente: false, extemporanea: true, plan: true },
        { estado: 'delivered', urgente: true, extemporanea: true, plan: true },
    ];
    assert.deepEqual(panel.contarChips(lista), { all: 3, pending: 2, urgent: 1, extemp: 1, plan: 2, delivered: 1 });
    assert.deepEqual(panel.contarChips([]), { all: 0, pending: 0, urgent: 0, extemp: 0, plan: 0, delivered: 0 });
});

test('los datos de una evidencia se leen de sus atributos y faltan con valores vacíos', () => {
    const item = new Elemento('article', { 'data-task-title': 'a', 'data-task-status': 'pending', 'data-task-urgent': 'true' });
    assert.deepEqual(panel.datosEvidencia(item), { titulo: 'a', descripcion: '', estado: 'pending', urgente: true, extemporanea: false, plan: false });
    assert.deepEqual(panel.datosEvidencia(new Elemento('article')), { titulo: '', descripcion: '', estado: '', urgente: false, extemporanea: false, plan: false });
});

// ---------------------------------------------------------------- Calendario

function calendario(datos) {
    const doc = documento();
    const seccion = agregar(doc, 'section', { class: 'learner-attendance-calendar' });
    const prev = agregar(seccion, 'button', { 'data-learner-calendar-prev': '' });
    const next = agregar(seccion, 'button', { 'data-learner-calendar-next': '' });
    const titulo = agregar(seccion, 'h2', { 'data-learner-calendar-month': '' });
    const grilla = agregar(seccion, 'div', { 'data-learner-calendar-grid': '' });
    const detalle = agregar(seccion, 'p', { 'data-learner-calendar-detail': '' });
    agregar(doc, 'script', { id: 'asistencia-calendario-data' }, { textContent: datos });
    return { doc, prev, next, titulo, grilla, detalle };
}

test('el calendario pinta el mes, marca hoy y muestra el detalle del día como texto', async () => {
    const carga = '<img src=x onerror=alert(1)>';
    const c = calendario(JSON.stringify({
        '2026-11-03': { estado: 'FALTA', etiqueta: 'Falta injustificada', clase: 'falta-nj', causal: carga },
        '2026-11-04': { estado: 'ASISTE', clase: '' },
    }));
    const api = panel.initCalendarioAsistencia(c.doc, new Date(2026, 10, 21));
    assert.equal(c.titulo.textContent, 'noviembre 2026');
    const dias = c.grilla.children.filter(e => e.tagName === 'BUTTON');
    assert.equal(dias.length, 30);
    assert.equal(c.grilla.children.filter(e => e.classList.contains('is-outside')).length, 6, 'noviembre de 2026 inicia domingo');
    assert.ok(dias[20].classList.contains('is-today'));
    assert.ok(dias[2].classList.contains('is-falta-nj'));
    assert.equal(dias[2].getAttribute('aria-label'), '03/11/2026: Falta injustificada');
    assert.equal(dias[3].getAttribute('aria-label'), '04/11/2026: ASISTE');
    assert.equal(dias[0].getAttribute('aria-label'), '01/11/2026: sin marcación');

    await dias[2].disparar('click');
    assert.equal(c.detalle.children[0].textContent, '03/11/2026');
    assert.equal(c.detalle.children[1].textContent, ` · Falta injustificada · ${carga}`);
    assert.equal(c.detalle.children[1].tagName, '#TEXT', 'la causal se inserta como texto, no como HTML');
    await dias[3].disparar('click');
    assert.equal(c.detalle.children[1].textContent, ' · ASISTE');
    await dias[0].disparar('click');
    assert.equal(c.detalle.textContent, 'No hay una marcación registrada para este día.');

    await c.prev.disparar('click');
    assert.equal(c.titulo.textContent, 'octubre 2026');
    await c.next.disparar('click');
    await c.next.disparar('click');
    assert.equal([api.mes(), api.anio()].join('/'), '11/2026');
    assert.equal(c.grilla.children.filter(e => e.classList.contains('is-today')).length, 0);
});

test('el calendario tolera datos ilegibles y no hace nada sin su sección', () => {
    const c = calendario('{no es json');
    panel.initCalendarioAsistencia(c.doc, new Date(2026, 1, 1));
    assert.equal(c.titulo.textContent, 'febrero 2026');
    assert.equal(c.grilla.children.filter(e => e.tagName === 'BUTTON').length, 28);
    assert.equal(panel.initCalendarioAsistencia(documento()), null);
    const soloJson = calendario('null');
    panel.initCalendarioAsistencia(soloJson.doc, new Date(2026, 1, 1));
    assert.equal(soloJson.grilla.children.filter(e => e.classList.contains('learner-calendar-day-state')).length, 0);
});

// ---------------------------------------------------------------- Panel

function panelCompleto(opciones = {}) {
    const doc = documento();
    const raiz = agregar(doc, 'div', { id: 'panel-aprendiz-root', 'data-learner-id': '9' });
    const tabs = ['resumen', 'evidencias', 'juicios'].map(t => agregar(raiz, 'button', { class: 'learner-tab-btn', 'data-tab-target': t }));
    const panes = {
        resumen: agregar(raiz, 'section', { 'data-learner-tab': 'resumen' }),
        evidencias: agregar(raiz, 'section', { 'data-learner-tab': 'evidencias' }),
        juicios: agregar(raiz, 'section', { 'data-learner-tab': 'juicios' }),
    };
    const salto = agregar(raiz, 'button', { 'data-jump-tab': 'juicios' });
    const saltoDirecto = agregar(raiz, 'button', { 'data-jump-tab': 'resumen', 'data-jump-target-id': 'seccion-alertas' });
    const alertas = agregar(panes.resumen, 'div', { id: 'seccion-alertas' });
    const icono = agregar(raiz, 'span', { id: 'view-mode-icon' });
    const textoVista = agregar(raiz, 'span', { id: 'view-mode-text' });
    const inferior = agregar(raiz, 'a', { class: 'learner-bottom-link', href: '#seccion-juicios' });
    const inferiorDesconocido = agregar(raiz, 'a', { class: 'learner-bottom-link', href: '#otra' });
    // Portafolio
    const modal = agregar(doc, 'dialog', { id: 'portafolio-modal' });
    const abrir = agregar(raiz, 'button', { id: 'btn-open-portafolio-modal' });
    const editarGithub = agregar(raiz, 'button', { class: 'btn-open-portafolio-modal', 'data-target-input': 'github' });
    const cerrar = agregar(modal, 'button', { 'data-close-portafolio-modal': '' });
    const form = agregar(modal, 'form', { id: 'form-portafolio-aprendiz' }, { action: '/aprendiz/1/portafolio' });
    agregar(form, 'input', { name: 'csrf_token' }, { value: 'token-prueba' });
    const github = agregar(form, 'input', { id: 'input-enlace-github' }, { value: ' https://github.com/a ' });
    agregar(form, 'input', { id: 'input-enlace-notion' }, { value: '' });
    const guardar = agregar(form, 'button', { id: 'btn-save-portafolio' });
    const textoGuardar = agregar(guardar, 'span', { id: 'btn-save-portafolio-text' });
    const aviso = agregar(modal, 'p', { id: 'portafolio-feedback-msg' });
    // Evidencias
    const busqueda = agregar(panes.evidencias, 'input', { id: 'task-search-input' });
    const limpiar = agregar(panes.evidencias, 'button', { id: 'task-search-clear' });
    const chips = ['all', 'pending', 'delivered'].map(f => agregar(panes.evidencias, 'button', { class: 'task-chip', 'data-task-filter': f }));
    chips[0].classList.add('is-active');
    const reiniciar = agregar(panes.evidencias, 'button', { id: 'btn-reset-task-filters' });
    const titulo = agregar(panes.evidencias, 'h3', { id: 'heading-tareas-pendientes' });
    const vacio = agregar(panes.evidencias, 'div', { id: 'tasks-empty-filter-state' });
    const pendiente = agregar(panes.evidencias, 'article', { 'data-task-item': '', 'data-task-title': 'modelo de datos', 'data-task-status': 'pending', 'data-task-urgent': 'true' });
    const entregadas = agregar(panes.evidencias, 'details', { class: 'entregadas-details' });
    const entregada = agregar(entregadas, 'article', { 'data-task-item': '', id: 'experiencia-tarea-7', 'data-task-title': 'informe final', 'data-task-status': 'delivered', 'data-task-plan': 'true' });
    for (const id of ['chip-count-all', 'chip-count-pending', 'chip-count-delivered', 'chip-count-plan']) agregar(raiz, 'span', { id });
    // Curva
    const punto = agregar(raiz, 'circle', { class: 'curve-point-item', 'data-fecha': '01/11', 'data-puntaje': '80', 'data-asistencia': '90', 'data-evidencias': '70', 'data-estado': 'Alto' });
    const puntoVacio = agregar(raiz, 'circle', { class: 'curve-point-item' });
    const inspector = Object.fromEntries(['fecha', 'puntaje', 'asistencia', 'evidencias', 'estado'].map(c => [c, agregar(raiz, 'span', { id: 'inspector-' + c })]));
    const win = ventana(opciones);
    const api = panel.initPanelAprendiz(doc, win);
    return { doc, raiz, tabs, panes, salto, saltoDirecto, alertas, icono, textoVista, inferior, inferiorDesconocido, modal, abrir, editarGithub, cerrar, form, github, guardar, textoGuardar, aviso, busqueda, limpiar, chips, reiniciar, titulo, vacio, pendiente, entregadas, entregada, punto, puntoVacio, inspector, win, api };
}

test('sin la raíz del panel no se inicializa nada', () => {
    assert.equal(panel.initPanelAprendiz(documento(), ventana()), null);
});

test('la pestaña inicial sale del ancla o de la preferencia guardada', () => {
    let p = panelCompleto({ hash: '#seccion-juicios' });
    assert.ok(p.panes.juicios.classList.contains('tab-pane-active'));
    assert.equal(p.tabs[2].getAttribute('aria-selected'), 'true');
    assert.deepEqual(p.win.history.anclas, [], 'la carga inicial no reescribe el ancla');
    p = panelCompleto({ guardada: 'evidencias' });
    assert.ok(p.panes.evidencias.classList.contains('tab-pane-active'));
    p = panelCompleto({ almacenamientoFalla: true });
    assert.ok(p.panes.resumen.classList.contains('tab-pane-active'), 'sin almacenamiento abre el resumen');
});

test('las pestañas, los saltos y la barra inferior activan la sección y avisan la ubicación', async () => {
    const p = panelCompleto();
    await p.tabs[1].disparar('click');
    assert.ok(p.panes.evidencias.classList.contains('tab-pane-active'));
    assert.ok(!p.panes.resumen.classList.contains('tab-pane-active'));
    assert.equal(p.win.history.anclas.at(-1), '#tab-evidencias');
    assert.equal(p.win.localStorage.datos['sena_learner_active_tab_9'], 'evidencias');

    await p.salto.disparar('click');
    assert.ok(p.panes.juicios.classList.contains('tab-pane-active'));
    assert.equal(p.panes.juicios.desplazado.behavior, 'smooth');
    assert.deepEqual(p.win.eventos.at(-1).detail, { tab: 'juicios', taskId: null });

    p.raiz.classList.add('experience-reduced-motion');
    await p.saltoDirecto.disparar('click');
    assert.equal(p.alertas.desplazado.behavior, 'auto');

    const anclas = p.win.history.anclas.length;
    await p.inferior.disparar('click');
    assert.ok(p.panes.juicios.classList.contains('tab-pane-active'));
    assert.equal(p.win.history.anclas.length, anclas, 'la barra inferior no reescribe el ancla');
    const eventos = p.win.eventos.length;
    await p.inferiorDesconocido.disparar('click');
    assert.equal(p.win.eventos.length, eventos);
});

test('la vista continua se aplica desde las preferencias y desplaza al activar una pestaña', async () => {
    const p = panelCompleto();
    await p.win.disparar('learner:preferences-applied', { detail: { preferences: { viewMode: 'cascade' } } });
    assert.ok(p.raiz.classList.contains('is-cascade-mode'));
    assert.equal(p.icono.textContent, '', 'el modo se comunica con texto, sin emojis');
    assert.equal(p.textoVista.textContent, 'Vista continua · Configurar');
    p.api.activarPestana('evidencias');
    assert.ok(p.panes.evidencias.desplazado);
    p.api.activarPestana('inexistente');
    await p.win.disparar('learner:preferences-applied', { detail: { preferences: { viewMode: 'tabs' } } });
    assert.ok(!p.raiz.classList.contains('is-cascade-mode'));
    assert.equal(p.textoVista.textContent, 'Por pestañas · Configurar');
});

test('la búsqueda, los chips y el reinicio filtran las evidencias y anuncian el vacío', async () => {
    const p = panelCompleto();
    assert.equal(p.doc.getElementById('chip-count-all').textContent, 2);
    assert.equal(p.doc.getElementById('chip-count-pending').textContent, 1);
    assert.equal(p.doc.getElementById('chip-count-plan').textContent, 1);

    p.busqueda.value = '  INFORME ';
    await p.busqueda.disparar('input');
    assert.equal(p.api.busqueda(), 'informe');
    assert.equal(p.pendiente.style.display, 'none');
    assert.equal(p.entregada.style.display, '');
    assert.equal(p.entregadas.open, true, 'la búsqueda abre las entregadas que coinciden');
    assert.equal(p.limpiar.style.display, 'block');

    await p.limpiar.disparar('click');
    assert.equal(p.busqueda.value, '');
    assert.equal(p.limpiar.style.display, 'none');
    assert.equal(p.pendiente.style.display, '');

    await p.chips[2].disparar('click');
    assert.equal(p.api.filtro(), 'delivered');
    assert.ok(p.chips[2].classList.contains('is-active'));
    assert.ok(!p.chips[0].classList.contains('is-active'));
    assert.equal(p.titulo.style.display, 'none');
    assert.equal(p.vacio.style.display, 'none');

    p.busqueda.value = 'nada coincide';
    await p.busqueda.disparar('input');
    assert.equal(p.vacio.style.display, 'block');

    await p.reiniciar.disparar('click');
    assert.equal(p.api.filtro(), 'all');
    assert.equal(p.busqueda.value, '');
    assert.ok(p.chips[0].classList.contains('is-active'));
    assert.equal(p.titulo.style.display, '');
    assert.equal(p.vacio.style.display, 'none');
});

test('sin evidencias el filtrado no hace nada', () => {
    const doc = documento();
    agregar(doc, 'div', { id: 'panel-aprendiz-root' });
    const api = panel.initPanelAprendiz(doc, ventana());
    assert.doesNotThrow(() => api.aplicarFiltros());
});

test('ir a una evidencia desde el inicio limpia filtros, abre su acordeón y la enfoca', async () => {
    const p = panelCompleto();
    await p.chips[1].disparar('click');
    assert.equal(p.entregada.style.display, 'none');
    await p.win.disparar('learner:navigate', { detail: { tab: 'evidencias', taskId: 7 } });
    assert.equal(p.api.filtro(), 'all');
    assert.equal(p.entregada.style.display, '');
    assert.equal(p.entregadas.open, true);
    assert.deepEqual(p.entregada.enfocado, { preventScroll: true });
    assert.ok(p.entregada.desplazado);

    await p.win.disparar('learner:navigate', { detail: { tab: 'juicios', taskId: null } });
    assert.ok(p.panes.juicios.desplazado);
    await p.win.disparar('learner:navigate', { detail: { tab: 'evidencias', taskId: 99 } });
    assert.ok(p.panes.evidencias.classList.contains('tab-pane-active'), 'sin la tarea se queda en la pestaña');
});

test('el portafolio se abre, enfoca el enlace pedido y se cierra', async () => {
    const p = panelCompleto();
    p.aviso.style.display = 'block';
    await p.abrir.disparar('click');
    assert.equal(p.modal.abierto, true);
    assert.equal(p.aviso.style.display, 'none');
    await p.cerrar.disparar('click');
    assert.equal(p.modal.abierto, false);
    await p.editarGithub.disparar('click');
    assert.equal(p.github.enfocado, true);
    await p.modal.disparar('click');
    assert.equal(p.modal.abierto, false, 'clic en el fondo cierra');
    p.modal.abierto = true;
    await p.modal.disparar('click', { target: p.form });
    assert.equal(p.modal.abierto, true, 'clic dentro del contenido no cierra');
});

test('guardar el portafolio envía los enlaces y recarga al confirmar', async () => {
    const p = panelCompleto({ respuesta: { ok: true, json: async () => ({ ok: true }) } });
    await p.form.disparar('submit');
    const { url, opciones } = p.win.peticiones[0];
    assert.equal(url, '/aprendiz/1/portafolio');
    assert.deepEqual(JSON.parse(opciones.body), { enlace_github: 'https://github.com/a', enlace_notion: '', csrf_token: 'token-prueba' });
    assert.equal(p.win.location.recargada, true);
    assert.equal(p.textoGuardar.textContent, 'Guardando...');
});

test('si el servidor rechaza el portafolio se informa el motivo y se reactiva el botón', async () => {
    const rechazo = panelCompleto({ respuesta: { ok: false, json: async () => ({ ok: false, error: 'Enlace no válido.' }) } });
    await rechazo.form.disparar('submit');
    assert.equal(rechazo.aviso.textContent, 'Enlace no válido.');
    assert.equal(rechazo.aviso.style.display, 'block');
    assert.equal(rechazo.guardar.disabled, false);
    assert.equal(rechazo.textoGuardar.textContent, 'Guardar enlaces');
    assert.equal(rechazo.win.location.recargada, false);

    const sinMotivo = panelCompleto({ respuesta: { ok: true, json: async () => ({ ok: false }) } });
    await sinMotivo.form.disparar('submit');
    assert.equal(sinMotivo.aviso.textContent, 'Error al guardar los enlaces.');

    const sinMensaje = panelCompleto({ respuesta: { ok: true, json: async () => { throw new Error(''); } } });
    await sinMensaje.form.disparar('submit');
    assert.equal(sinMensaje.aviso.textContent, 'Error inesperado.');
});

test('el inspector de la curva muestra los datos del punto señalado', async () => {
    const p = panelCompleto();
    await p.punto.disparar('mouseenter');
    assert.equal(p.inspector.fecha.textContent, '01/11');
    assert.equal(p.inspector.puntaje.textContent, '80 pts');
    assert.equal(p.inspector.asistencia.textContent, '90%');
    assert.equal(p.inspector.evidencias.textContent, '70%');
    assert.equal(p.inspector.estado.textContent, 'Alto');
    await p.puntoVacio.disparar('focus');
    assert.equal(p.inspector.fecha.textContent, '01/11', 'un punto sin datos conserva la lectura anterior');
    await p.puntoVacio.disparar('click');
});

test('sin modal ni formulario el portafolio no falla', () => {
    const doc = documento();
    agregar(doc, 'div', { id: 'panel-aprendiz-root' });
    const abrir = agregar(doc, 'button', { id: 'btn-open-portafolio-modal' });
    const cerrar = agregar(doc, 'button', { 'data-close-portafolio-modal': '' });
    panel.initPanelAprendiz(doc, ventana());
    assert.doesNotThrow(() => { abrir.disparar('click'); cerrar.disparar('click'); });
});
