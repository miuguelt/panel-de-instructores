const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const { initLearnerPersonalization } = require('../app/static/js/aprendiz_personalizacion.js');

class Elemento {
    constructor(tagName = 'DIV', id = '') {
        Object.assign(this, { tagName, id, dataset: {}, children: [], attrs: {}, listeners: {}, style: { setProperty(name, value) { this[name] = value; } }, value: '', textContent: '', hidden: false, disabled: false, files: [] });
        this.className = '';
        this.classList = { contains: name => this.className.split(' ').includes(name), toggle: (name, enabled) => { this.className = this.className.split(' ').filter(item => item !== name).concat(enabled ? name : []).join(' '); }, add: name => this.classList.toggle(name, true), remove: name => this.classList.toggle(name, false) };
    }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    removeAttribute(name) { delete this.attrs[name]; }
    appendChild(child) { return this.insertBefore(child, null); }
    insertBefore(child, target) {
        if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1);
        const index = target ? this.children.indexOf(target) : this.children.length;
        this.children.splice(index, 0, child); child.parentElement = this; return child;
    }
    get nextSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) + 1] ?? null; }
    replaceChildren(...children) { this.children.forEach(child => { child.parentElement = null; }); this.children = []; children.forEach(child => this.appendChild(child)); }
    addEventListener(name, listener) { (this.listeners[name] ??= []).push(listener); }
    async dispatch(name, detail = {}) { for (const listener of this.listeners[name] ?? []) await listener({ target: this, preventDefault() {}, ...detail }); }
    matches(selector) {
        if (selector.startsWith('#')) return this.id === selector.slice(1);
        if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
        if (selector.startsWith('meta')) return this.tagName === 'META';
        const data = selector.match(/^\[data-([\w-]+)\]$/);
        if (data) return Object.hasOwn(this.dataset, data[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()));
        return false;
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    focus() { this.focused = true; }
}

const defaults = { avatar: '💻', accent: '#39a900', themeName: 'sena', motto: '', alias: '', background: 'plain', sectionOrder: [], viewMode: 'tabs' };
function respuesta(preferences = {}, extra = {}) { return { ok: true, preferences: { ...defaults, ...preferences }, revision: 1, photoUrl: null, configured: true, ...extra }; }
function entorno({ responses = [respuesta()], storage = {}, noConfig = false, storageFails = false } = {}) {
    const doc = new Elemento('DOCUMENT');
    doc.getElementById = id => doc.querySelector('#' + id);
    doc.createElement = tag => new Elemento(tag.toUpperCase());
    doc.createComment = () => new Elemento('COMMENT');
    const page = doc.appendChild(new Elemento('DIV', 'panel-aprendiz-root'));
    const modal = page.appendChild(new Elemento('DIALOG', 'personalizacion-modal'));
    const elements = {};
    for (const id of ['btn-open-customizer', 'learner-avatar-disc', 'learner-motto-wrapper', 'btn-toggle-view-mode', 'learner-avatar-display', 'learner-display-name', 'learner-motto-text', 'learner-photo-display', 'personalizacion-global-status']) elements[id] = page.appendChild(new Elemento('BUTTON', id));
    for (const id of ['customizer-motto-input', 'customizer-alias-input', 'customizer-background-input', 'customizer-view-mode-input', 'customizer-photo-input', 'customizer-photo-preview', 'customizer-photo-symbol', 'customizer-remove-photo', 'btn-save-personalizacion', 'btn-reset-personalizacion', 'personalizacion-status', 'personalizacion-retry', 'personalizacion-reload', 'personalizacion-legacy', 'personalizacion-order-list', 'personalizacion-form-fields']) elements[id] = modal.appendChild(new Elemento('INPUT', id));
    const close = modal.appendChild(new Elemento('BUTTON')); close.dataset.closePersonalizacionModal = '';
    const avatar = modal.appendChild(new Elemento('BUTTON')); avatar.dataset.avatar = '🚀';
    const color = modal.appendChild(new Elemento('BUTTON')); Object.assign(color.dataset, { accent: '#d97706', themeName: 'amber' });
    const motto = modal.appendChild(new Elemento('BUTTON')); motto.dataset.motto = 'Cada día un paso más cerca de la meta';
    const progress = page.appendChild(new Elemento('SECTION', 'seccion-progreso'));
    const tasks = page.appendChild(new Elemento('SECTION', 'tasks-wrapper'));
    const taskHeading = tasks.appendChild(new Elemento('H2', 'seccion-tareas'));
    const ranking = page.appendChild(new Elemento('SECTION', 'seccion-ranking'));
    const meta = doc.appendChild(new Elemento('META')); meta.setAttribute('content', 'csrf-prueba');
    if (!noConfig) { const config = doc.appendChild(new Elemento('SCRIPT', 'learner-personalization-config')); config.textContent = JSON.stringify({ learnerId: 9, endpoint: '/aprendiz/7/personalizacion', displayName: 'María Pérez' }); }
    const calls = [], removed = [], revoked = [], values = new Map(Object.entries(storage)), timers = new Map();
    let nextTimer = 0;
    const win = new Elemento('WINDOW');
    Object.assign(win, { FormData, AbortController, setTimeout(callback) { timers.set(++nextTimer, callback); return nextTimer; }, clearTimeout(id) { timers.delete(id); }, triggerTimeout() { timers.get(nextTimer)(); }, CustomEvent: class { constructor(type, data) { this.type = type; this.detail = data.detail; } }, URL: { createObjectURL: () => 'blob:preview', revokeObjectURL: url => revoked.push(url) }, abrirModal: value => { value.open = true; }, cerrarModal: value => { value.open = false; }, localStorage: { getItem(key) { if (storageFails) throw new Error('Storage'); return values.get(key) ?? null; }, removeItem(key) { if (storageFails) throw new Error('Storage'); removed.push(key); values.delete(key); } }, fetch: async (url, options) => {
        calls.push({ url, options }); const item = responses.shift(); if (item instanceof Error) throw item;
        if (typeof item === 'function') return item(options);
        return { ok: item?.status ? false : true, status: item?.status ?? 200, json: async () => { if (item?.html) throw new Error('HTML'); return item; } };
    } });
    win.dispatchEvent = event => { win.lastEvent = event; return win.dispatch(event.type, { detail: event.detail }); };
    return { doc, win, page, modal, elements, close, avatar, color, motto, progress, tasks, taskHeading, ranking, calls, removed, revoked, values, timers };
}

test('lee la base de datos antes de habilitar guardar y el servidor prevalece sobre el navegador', async () => {
    let resolver; const e = entorno({ responses: [() => new Promise(resolve => { resolver = resolve; })], storage: { sena_learner_prefs_9: JSON.stringify({ alias: 'Antiguo' }) } });
    const app = initLearnerPersonalization(e.doc, e.win);
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
    resolver({ ok: true, status: 200, json: async () => respuesta({ alias: 'Guardado', motto: 'Mi meta', viewMode: 'cascade', background: 'grid' }, { photoUrl: '/foto?v=1' }) });
    await app.ready;
    assert.equal(e.elements['learner-display-name'].textContent, 'Guardado');
    assert.equal(e.elements['learner-photo-display'].getAttribute('src'), '/foto?v=1');
    assert.equal(e.elements['learner-avatar-display'].hidden, true);
    assert.equal(e.page.dataset.learnerBackground, 'grid');
    assert.equal(e.win.lastEvent.detail.preferences.viewMode, 'cascade');
    assert.equal(e.elements['personalizacion-legacy'].hidden, true);
    assert.equal(e.elements['btn-save-personalizacion'].disabled, false);
});

test('guarda multipart con revisión y CSRF; aplica solo respuesta confirmada, permite cancelar y restablecer', async () => {
    const e = entorno({ responses: [respuesta(), respuesta({ alias: 'Confirmado', motto: 'Servidor', avatar: '🚀', accent: '#d97706', themeName: 'amber', background: 'dots', viewMode: 'cascade' }, { revision: 2 })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready;
    await e.elements['btn-open-customizer'].dispatch('click'); assert.equal(e.modal.open, true);
    await e.avatar.dispatch('click'); await e.color.dispatch('click'); await e.motto.dispatch('click');
    e.elements['customizer-alias-input'].value = ' Borrador ';
    e.elements['customizer-background-input'].value = 'dots';
    e.elements['customizer-view-mode-input'].value = 'cascade';
    assert.equal(e.elements['learner-display-name'].textContent, 'María Pérez');
    await e.elements['btn-save-personalizacion'].dispatch('click');
    const payload = e.calls[1].options.body;
    assert.equal(payload.get('revision'), '1'); assert.equal(payload.get('csrf_token'), 'csrf-prueba');
    assert.equal(JSON.parse(payload.get('preferences')).alias, 'Borrador');
    assert.equal(JSON.parse(payload.get('preferences')).avatar, '🚀');
    assert.equal(e.calls[1].options.method, 'POST');
    assert.equal(e.calls[0].options.headers['X-Learner-Id'], '9');
    assert.equal(e.calls[1].options.headers['X-Learner-Id'], '9');
    assert.equal(e.elements['learner-display-name'].textContent, 'Confirmado');
    assert.equal(e.page.style['--learner-accent-foreground'], '#111827');
    assert.equal(e.modal.open, false);
    await e.elements['learner-avatar-disc'].dispatch('click');
    await e.elements['btn-reset-personalizacion'].dispatch('click');
    assert.equal(e.elements['customizer-alias-input'].value, '');
    assert.equal(e.elements['learner-display-name'].textContent, 'Confirmado');
    await e.close.dispatch('click');
    await e.elements['learner-motto-wrapper'].dispatch('keydown', { key: 'Enter' });
    assert.equal(e.elements['customizer-alias-input'].value, 'Confirmado');
    await e.modal.dispatch('cancel');
    await e.elements['learner-avatar-disc'].dispatch('keydown', { key: ' ' });
    await e.modal.dispatch('click');
    await e.elements['learner-motto-wrapper'].dispatch('keydown', { key: 'Tab' });
    await e.elements['btn-toggle-view-mode'].dispatch('click');
    assert.equal(e.elements['customizer-view-mode-input'].focused, true);
});

test('fallo de red conserva el borrador y un conflicto exige recargar antes de guardar', async () => {
    const e = entorno({ responses: [respuesta(), new Error('Sin red'), { status: 409, detail: 'Otra pestaña guardó cambios.' }, respuesta({ alias: 'Otra pestaña' }, { revision: 3 })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    e.elements['customizer-alias-input'].value = 'Pendiente'; await app.save();
    assert.equal(e.elements['customizer-alias-input'].value, 'Pendiente');
    assert.equal(e.elements['learner-display-name'].textContent, 'María Pérez');
    assert.match(e.elements['personalizacion-status'].textContent, /conexión/);
    assert.equal(e.elements['personalizacion-retry'].hidden, false);
    await e.elements['personalizacion-retry'].dispatch('click');
    assert.equal(e.elements['personalizacion-reload'].hidden, false);
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
    const calls = e.calls.length; await app.save(); assert.equal(e.calls.length, calls);
    await e.elements['personalizacion-reload'].dispatch('click');
    assert.equal(e.elements['customizer-alias-input'].value, 'Otra pestaña');
    assert.equal(e.elements['learner-display-name'].textContent, 'Otra pestaña');
});

test('lectura fallida y respuesta HTML mantienen guardar bloqueado y ofrecen reintentar', async () => {
    const e = entorno({ responses: [{ status: 503, detail: 'Servicio no disponible.' }, respuesta(), { status: 400, html: true }] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready;
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
    await e.elements['personalizacion-retry'].dispatch('click');
    assert.equal(e.elements['btn-save-personalizacion'].disabled, false);
    await app.save(); assert.match(e.elements['personalizacion-status'].textContent, /sesión/);
});

test('validación de foto, vista previa, reemplazo, quitar foto y carga confirmada', async () => {
    const e = entorno({ responses: [respuesta({}, { photoUrl: '/foto?v=1' }), respuesta({}, { photoUrl: '/foto?v=2', revision: 2 }), respuesta({}, { revision: 3 })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    e.elements['customizer-photo-input'].files = [{ type: 'text/plain', size: 10 }];
    await e.elements['customizer-photo-input'].dispatch('change'); assert.match(e.elements['personalizacion-status'].textContent, /JPEG/);
    e.elements['customizer-photo-input'].files = [{ type: 'image/png', size: 2 * 1024 * 1024 + 1 }];
    await e.elements['customizer-photo-input'].dispatch('change'); assert.match(e.elements['personalizacion-status'].textContent, /2 MiB/);
    const foto = new Blob(['imagen'], { type: 'image/png' });
    e.elements['customizer-photo-input'].files = [foto]; await e.elements['customizer-photo-input'].dispatch('change');
    assert.equal(e.elements['customizer-photo-preview'].getAttribute('src'), 'blob:preview');
    await e.elements['customizer-photo-input'].dispatch('change'); assert.deepEqual(e.revoked, ['blob:preview']);
    await app.save(); assert.equal(e.calls[1].options.body.get('photo').type, 'image/png');
    assert.equal(e.elements['learner-photo-display'].getAttribute('src'), '/foto?v=2');
    app.open(); await e.elements['customizer-remove-photo'].dispatch('click'); await app.save();
    assert.equal(e.calls[2].options.body.get('remove_photo'), 'true');
    assert.equal(e.elements['learner-avatar-display'].hidden, false);
    e.elements['customizer-photo-input'].files = []; await e.elements['customizer-photo-input'].dispatch('change');
});

test('ordena secciones con controles accesibles y mueve todo el contenedor de tareas al confirmar', async () => {
    const order = ['seccion-tareas', 'seccion-ranking', 'seccion-progreso'];
    const e = entorno({ responses: [respuesta({}, { photoUrl: null }), respuesta({ sectionOrder: order })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    const list = e.elements['personalizacion-order-list'];
    assert.equal(list.children[0].children[1].disabled, true);
    await list.children[0].children[2].dispatch('click');
    assert.match(list.children[0].children[0].textContent, /Evidencias/);
    await list.children[1].children[1].dispatch('click');
    assert.match(list.children[0].children[0].textContent, /Progreso/);
    await list.children[0].children[2].dispatch('click');
    await list.children[1].children[2].dispatch('click');
    await app.save();
    const sections = e.page.children.filter(item => [e.progress, e.tasks, e.ranking].includes(item));
    assert.deepEqual(sections, [e.tasks, e.ranking, e.progress]);
    assert.equal(e.taskHeading.parentElement, e.tasks);
    assert.deepEqual(JSON.parse(e.calls[1].options.body.get('preferences')).sectionOrder, order);
});

test('guardar el alias conserva las posiciones de tarjetas conocidas que no están visibles', async () => {
    const order = ['seccion-grupo-trabajo', 'seccion-progreso', 'seccion-liga-grupos', 'seccion-tareas', 'seccion-ranking'];
    const e = entorno({ responses: [respuesta({ sectionOrder: order }), respuesta({ sectionOrder: order, alias: 'Mi alias' })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    e.elements['customizer-alias-input'].value = 'Mi alias';
    assert.equal(e.elements['personalizacion-order-list'].children.length, 3);
    await app.save();
    assert.deepEqual(JSON.parse(e.calls[1].options.body.get('preferences')).sectionOrder, order);
    assert.equal(e.elements['learner-display-name'].textContent, 'Mi alias');
});

test('subir y bajar tarjetas visibles mantiene los espacios de las ausentes; restablecer sí limpia el orden', async () => {
    const original = ['seccion-grupo-trabajo', 'seccion-progreso', 'seccion-liga-grupos', 'seccion-tareas', 'seccion-ranking'];
    const moved = ['seccion-grupo-trabajo', 'seccion-tareas', 'seccion-liga-grupos', 'seccion-ranking', 'seccion-progreso'];
    const e = entorno({ responses: [respuesta({ sectionOrder: original }), respuesta({ sectionOrder: moved }), respuesta()] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    const list = e.elements['personalizacion-order-list'];
    assert.equal(list.children[0].children[0].textContent, '1. Progreso');
    assert.equal(list.children[0].children[1].disabled, true);
    assert.equal(list.children[2].children[2].disabled, true);
    await list.children[0].children[2].dispatch('click');
    assert.equal(list.children[0].children[0].textContent, '1. Evidencias');
    await list.children[1].children[2].dispatch('click');
    assert.equal(list.children[1].children[0].textContent, '2. Mi posición');
    await app.save();
    assert.deepEqual(JSON.parse(e.calls[1].options.body.get('preferences')).sectionOrder, moved);
    assert.deepEqual(e.page.children.filter(item => [e.progress, e.tasks, e.ranking].includes(item)), [e.tasks, e.ranking, e.progress]);
    app.open(); await e.elements['btn-reset-personalizacion'].dispatch('click'); await app.save();
    assert.deepEqual(JSON.parse(e.calls[2].options.body.get('preferences')).sectionOrder, ['seccion-progreso', 'seccion-tareas', 'seccion-ranking']);
});

test('recupera preferencias antiguas solo con acción explícita y borra la copia tras confirmación', async () => {
    const legacy = { ...defaults, alias: 'Mi alias', accent: '#not-valid', sectionOrder: ['seccion-tareas', 'seccion-tareas', 'inexistente'] };
    const e = entorno({ responses: [respuesta({}, { configured: false, revision: 0 }), new Error('Sin red'), respuesta({ alias: 'Mi alias' })], storage: { sena_learner_prefs_9: JSON.stringify(legacy) } });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready;
    assert.equal(e.elements['learner-display-name'].textContent, 'María Pérez');
    assert.equal(e.elements['personalizacion-legacy'].hidden, false);
    await e.elements['personalizacion-legacy'].dispatch('click');
    assert.equal(e.elements['customizer-alias-input'].value, 'Mi alias');
    await app.save(); assert.equal(e.removed.length, 0);
    await app.save(); assert.deepEqual(e.removed, ['sena_learner_prefs_9']);
    assert.equal(JSON.parse(e.calls[1].options.body.get('preferences')).accent, '#39a900');
});

test('restablecer después de recuperar no borra la copia anterior sin guardar esa recuperación', async () => {
    const e = entorno({ responses: [respuesta({}, { configured: false, revision: 0 }), respuesta()], storage: { sena_learner_prefs_9: JSON.stringify({ alias: 'Anterior' }) } });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    await e.elements['personalizacion-legacy'].dispatch('click');
    await e.elements['btn-reset-personalizacion'].dispatch('click'); await app.save();
    assert.equal(e.removed.length, 0);
    assert.equal(e.values.has('sena_learner_prefs_9'), true);
});

test('tolera falta de configuración, almacenamiento roto y metadatos inválidos sin guardar falsamente', async () => {
    assert.equal(initLearnerPersonalization(entorno({ noConfig: true }).doc, {}), null);
    const vacio = new Elemento('DOCUMENT'); vacio.getElementById = () => null;
    assert.equal(initLearnerPersonalization(vacio, {}), null);
    for (const storage of [{ sena_learner_prefs_9: '{incorrecto' }, { sena_learner_prefs_9: 'null' }]) {
        const e = entorno({ storage, responses: [respuesta({}, { configured: false })] });
        const app = initLearnerPersonalization(e.doc, e.win); await app.ready; assert.equal(e.elements['personalizacion-legacy'].hidden, true);
    }
    const e = entorno({ storageFails: true, responses: [{ ok: false }] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready;
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
});

test('el script se inicializa automáticamente con configuración de la plantilla', async () => {
    const e = entorno();
    vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/js/aprendiz_personalizacion.js'), 'utf8'), { document: e.doc, window: e.win });
    await e.win.learnerPersonalization.ready;
    assert.equal(e.elements['learner-display-name'].textContent, 'María Pérez');
});

test('cambiar avatar o color conserva el alias y los otros campos que ya escribiste', async () => {
    const e = entorno(); const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    e.elements['customizer-alias-input'].value = 'Nuevo alias';
    e.elements['customizer-motto-input'].value = 'Mi texto';
    e.elements['customizer-background-input'].value = 'grid';
    e.elements['customizer-view-mode-input'].value = 'cascade';
    await e.avatar.dispatch('click'); await e.color.dispatch('click');
    assert.equal(e.elements['customizer-alias-input'].value, 'Nuevo alias');
    assert.equal(e.elements['customizer-motto-input'].value, 'Mi texto');
    assert.equal(e.elements['customizer-background-input'].value, 'grid');
    assert.equal(e.elements['customizer-view-mode-input'].value, 'cascade');
    await e.modal.dispatch('close');
    assert.equal(e.elements['customizer-alias-input'].value, '');
});

test('durante el guardado bloquea duplicados y cierre; confirma el mensaje accesible al terminar', async () => {
    let resolver;
    const e = entorno({ responses: [respuesta(), () => new Promise(resolve => { resolver = resolve; })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    const saving = app.save();
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
    assert.equal(e.modal.getAttribute('aria-busy'), 'true');
    await app.save(); await app.load(); await e.close.dispatch('click'); await e.modal.dispatch('cancel'); app.open();
    assert.equal(e.calls.length, 2); assert.equal(e.modal.open, true);
    resolver({ ok: true, status: 200, json: async () => respuesta({ alias: 'Persistido' }) });
    await saving;
    assert.match(e.elements['personalizacion-global-status'].textContent, /quedaron guardados/);
    assert.equal(e.elements['personalizacion-global-status'].dataset.kind, 'success');
    assert.equal(e.modal.open, false);
});

test('usa el aviso accesible compartido para confirmar el guardado', async () => {
    const e = entorno({ responses: [respuesta(), respuesta({ alias: 'Conservado' })] });
    const notices = [];
    e.win.mostrarAviso = (message, options) => notices.push({ message, options });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; await app.save();
    assert.equal(notices.length, 1);
    assert.match(notices[0].message, /quedaron guardados/);
    assert.equal(notices[0].options.intent, 'success');
});

test('una respuesta incompleta no autoriza un guardado ni activa recuperación local', async () => {
    const broken = respuesta(); delete broken.configured;
    const e = entorno({ responses: [broken], storage: { sena_learner_prefs_9: JSON.stringify({ alias: 'Antiguo' }) } });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready;
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
    assert.equal(e.elements['personalizacion-legacy'].hidden, true);
});

test('al cambiar la sesión rechaza el guardado, conserva el borrador y exige leer la cuenta de nuevo', async () => {
    const e = entorno({ responses: [respuesta({ alias: 'Cuenta original' }), { status: 401, detail: 'La sesión cambió. Recarga la página para continuar.' }, { status: 401, detail: 'La sesión cambió.' }] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    e.elements['customizer-alias-input'].value = 'Borrador pendiente'; await app.save();
    assert.equal(e.elements['learner-display-name'].textContent, 'Cuenta original');
    assert.equal(e.elements['customizer-alias-input'].value, 'Borrador pendiente');
    assert.equal(e.elements['btn-save-personalizacion'].disabled, true);
    assert.match(e.elements['personalizacion-status'].textContent, /sesión cambió/);
    await e.elements['personalizacion-retry'].dispatch('click');
    assert.equal(e.calls.at(-1).options.method, 'GET');
});

test('un tiempo de espera agotado libera la interfaz y permite reintentar conservando el borrador', async () => {
    const blocked = options => new Promise((_, reject) => { options.signal.addEventListener('abort', () => reject(new Error('Abortado'))); });
    const e = entorno({ responses: [respuesta(), blocked, respuesta({ alias: 'Guardado después' })] });
    const app = initLearnerPersonalization(e.doc, e.win); await app.ready; app.open();
    e.elements['customizer-alias-input'].value = 'Pendiente';
    const saving = app.save(); e.win.triggerTimeout(); await saving;
    assert.match(e.elements['personalizacion-status'].textContent, /tiempo/);
    assert.equal(e.elements['customizer-alias-input'].value, 'Pendiente');
    assert.equal(e.elements['btn-save-personalizacion'].disabled, false);
    assert.equal(e.modal.getAttribute('aria-busy'), 'false');
    assert.equal(e.timers.size, 0);
    await e.elements['personalizacion-retry'].dispatch('click');
    assert.equal(e.elements['learner-display-name'].textContent, 'Guardado después');
    assert.equal(e.timers.size, 0);
});
