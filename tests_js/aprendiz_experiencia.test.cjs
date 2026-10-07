const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const { initLearnerExperience } = require('../app/static/js/aprendiz_experiencia.js');

class Elemento {
    constructor(tag = 'DIV', id = '') {
        Object.assign(this, { tagName: tag, id, dataset: {}, children: [], attrs: {}, listeners: {}, textContent: '', value: '', checked: false, disabled: false, hidden: false, className: '', style: { setProperty(name, value) { this[name] = value; } } });
        this.classList = { contains: name => this.className.split(' ').includes(name), toggle: (name, value) => { this.className = this.className.split(' ').filter(item => item !== name).concat(value ? name : []).join(' '); } };
    }
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    addEventListener(name, callback) { (this.listeners[name] ??= []).push(callback); }
    async dispatch(name, detail = {}) { for (const callback of this.listeners[name] ?? []) await callback({ target: this, preventDefault() {}, ...detail }); }
    matches(selector) {
        if (selector[0] === '#') return this.id === selector.slice(1);
        if (selector[0] === '.') return this.classList.contains(selector.slice(1));
        if (selector.startsWith('meta')) return this.tagName === 'META';
        const data = selector.match(/^\[data-([\w-]+)\]$/);
        return data ? Object.hasOwn(this.dataset, data[1].replace(/-([a-z])/g, (_, value) => value.toUpperCase())) : false;
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) ?? null; }
    focus() { this.focused = true; }
}

const defaults = { weeklyGoal: 2, notificationMode: 'all', rankingVisible: true, reducedMotion: false, density: 'comfortable', resume: null };
function result(preferences = {}, revision = 2) { return { ok: true, preferences: { ...defaults, ...preferences }, revision }; }
function entorno({ seed = {}, responses = [], noSection = false } = {}) {
    const doc = new Elemento('DOCUMENT'); doc.getElementById = id => doc.querySelector('#' + id);
    const root = doc.appendChild(new Elemento('DIV', 'panel-aprendiz-root')); Object.assign(root.dataset, { experienciaUrl: '/aprendiz/7/experiencia', learnerId: '9' });
    const section = root.appendChild(new Elemento('SECTION', noSection ? '' : 'aprendiz-experiencia'));
    const elements = {};
    for (const id of ['experience-weekly-goal', 'experience-notification-mode', 'experience-ranking-visible', 'experience-reduced-motion', 'experience-density', 'experience-save', 'experience-retry', 'experience-reload', 'experience-status', 'experience-resume', 'experience-next-action', 'experience-weekly-count', 'experience-weekly-target', 'experience-weekly-progress', 'experience-weekly-summary']) elements[id] = section.appendChild(new Elemento('INPUT', id));
    const config = section.appendChild(new Elemento('SCRIPT', 'aprendiz-experiencia-data'));
    config.textContent = JSON.stringify({ ...result({}, 1), weekly: { count: 1, target: 2, percent: 50 }, next_action: { title: 'Entrega tu evidencia', tab: 'evidencias', taskId: 5, button: 'Ver evidencia' }, ...seed });
    const tab = root.appendChild(new Elemento('BUTTON')); tab.className = 'learner-tab-btn'; tab.dataset.tabTarget = 'grupo';
    const task = root.appendChild(new Elemento('ARTICLE')); task.dataset.experienceTaskId = '5'; task.dataset.experienceTaskTab = 'evidencias';
    const taskControl = task.appendChild(new Elemento('SUMMARY'));
    const optional = root.appendChild(new Elemento()); optional.dataset.experienceNotice = 'optional';
    const critical = root.appendChild(new Elemento()); critical.dataset.experienceNotice = 'important';
    const protectedNotice = root.appendChild(new Elemento()); protectedNotice.dataset.experienceNotice = 'optional'; protectedNotice.setAttribute('role', 'alert');
    const ranking = root.appendChild(new Elemento()); ranking.dataset.experienceRanking = '';
    const meta = doc.appendChild(new Elemento('META')); meta.setAttribute('content', 'csrf-prueba');
    const timers = new Map(), calls = [], notices = [], events = []; let counter = 0;
    const win = new Elemento('WINDOW');
    Object.assign(win, { AbortController, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } }, setTimeout(callback, delay) { timers.set(++counter, { callback, delay }); return counter; }, clearTimeout(id) { timers.delete(id); }, trigger(delay) { const timer = [...timers].find(([, value]) => value.delay === delay); if (!timer) throw new Error('Temporizador ausente'); timers.delete(timer[0]); return timer[1].callback(); }, mostrarAviso(message, options) { notices.push({ message, options }); }, fetch: async (url, options) => {
        calls.push({ url, options }); const response = responses.shift(); if (response instanceof Error) throw response;
        if (typeof response === 'function') return response(options);
        return { ok: !response?.status, status: response?.status || 200, json: async () => { if (response?.html) throw new Error('HTML'); return response; } };
    } });
    win.dispatchEvent = event => { events.push(event); return win.dispatch(event.type, { detail: event.detail }); };
    return { doc, win, root, section, elements, tab, task, taskControl, optional, critical, protectedNotice, ranking, timers, calls, notices, events, config };
}

test('restaura la experiencia desde la lectura del servidor y protege los avisos importantes', () => {
    const e = entorno({ seed: result({ weeklyGoal: 4, notificationMode: 'quiet', rankingVisible: false, reducedMotion: true, density: 'compact', resume: { tab: 'evidencias', taskId: 5 } }, 7) });
    const app = initLearnerExperience(e.doc, e.win); assert.ok(app);
    assert.equal(e.calls.length, 0);
    assert.equal(e.elements['experience-weekly-goal'].value, '4');
    assert.equal(e.optional.hidden, true); assert.equal(e.critical.hidden, false); assert.equal(e.protectedNotice.hidden, false);
    assert.equal(e.ranking.hidden, true); assert.equal(e.root.classList.contains('experience-reduced-motion'), true);
    assert.equal(e.root.dataset.experienceDensity, 'compact');
    assert.equal(e.elements['experience-weekly-progress'].getAttribute('aria-valuenow'), '25');
    assert.equal(e.elements['experience-resume'].hidden, false);
});

test('la semilla de la página no necesita el indicador ok de las respuestas de la API', () => {
    const seed = result({ weeklyGoal: 5 }, 3); delete seed.ok;
    const e = entorno({ seed });
    const data = JSON.parse(e.config.textContent); delete data.ok; e.config.textContent = JSON.stringify(data);
    initLearnerExperience(e.doc, e.win);
    assert.equal(e.calls.length, 0);
    assert.equal(e.elements['experience-weekly-goal'].value, '5');
});

test('los valores iniciales sin registro se anuncian cargados y solo una revisión persistida se anuncia guardada', async () => {
    const e = entorno({ seed: result({}, 0), responses: [result({}, 0), result({}, 1)] });
    const app = initLearnerExperience(e.doc, e.win);
    assert.equal(e.elements['experience-status'].textContent, 'Tus ajustes iniciales están cargados. Los cambios se guardan automáticamente.');
    assert.doesNotMatch(e.elements['experience-status'].textContent, /están guardados/);
    await app.load();
    assert.equal(e.elements['experience-status'].textContent, 'Tus ajustes iniciales están cargados. Los cambios se guardan automáticamente.');
    await app.load();
    assert.equal(e.elements['experience-status'].textContent, 'Tus ajustes guardados están cargados.');
    const guardado = entorno({ seed: result({}, 1) });
    initLearnerExperience(guardado.doc, guardado.win);
    assert.equal(guardado.elements['experience-status'].textContent, 'Tus ajustes están guardados en tu cuenta.');
});

test('guarda preferencias JSON con revisión y headers, y aplica solo la confirmación', async () => {
    const e = entorno({ responses: [result({ weeklyGoal: 3, density: 'compact', rankingVisible: false }, 2)] });
    const app = initLearnerExperience(e.doc, e.win);
    e.elements['experience-weekly-goal'].value = '3'; e.elements['experience-density'].value = 'compact'; e.elements['experience-ranking-visible'].checked = false;
    await e.elements['experience-weekly-goal'].dispatch('change');
    assert.equal(e.elements['experience-weekly-target'].textContent, '2'); assert.equal(e.ranking.hidden, false);
    await e.elements['experience-save'].dispatch('click');
    assert.equal(e.calls[0].url, '/aprendiz/7/experiencia');
    assert.equal(e.calls[0].options.headers['X-CSRFToken'], 'csrf-prueba');
    assert.equal(e.calls[0].options.headers['X-Learner-Id'], '9');
    assert.equal(e.calls[0].options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(e.calls[0].options.body), { revision: 1, preferences: { ...defaults, weeklyGoal: 3, density: 'compact', rankingVisible: false } });
    assert.equal(e.elements['experience-weekly-target'].textContent, '3'); assert.equal(e.ranking.hidden, true);
    assert.match(e.elements['experience-status'].textContent, /guardad/);
    assert.equal(e.notices.length, 1); assert.equal(e.timers.size, 0);
    await app.ready;
});

test('mantiene el borrador ante errores, reintenta y exige recargar un conflicto', async () => {
    const e = entorno({ responses: [new Error('Sin conexión'), { status: 409, detail: 'Otra pestaña guardó cambios.' }, result({ weeklyGoal: 8 }, 4)] });
    const app = initLearnerExperience(e.doc, e.win);
    e.elements['experience-weekly-goal'].value = '6'; await app.save();
    assert.equal(e.elements['experience-weekly-goal'].value, '6'); assert.equal(e.elements['experience-weekly-target'].textContent, '2');
    assert.equal(e.elements['experience-retry'].hidden, false);
    await e.elements['experience-retry'].dispatch('click');
    assert.equal(e.elements['experience-reload'].hidden, false); assert.equal(e.elements['experience-save'].disabled, true);
    e.elements['experience-weekly-goal'].value = '7'; await e.elements['experience-weekly-goal'].dispatch('change');
    assert.equal(e.elements['experience-reload'].hidden, false);
    assert.match(e.elements['experience-status'].textContent, /Otra pestaña/);
    await app.save(); assert.equal(e.calls.length, 2);
    await e.elements['experience-reload'].dispatch('click');
    assert.equal(e.calls[2].options.method, 'GET');
    assert.equal(e.elements['experience-weekly-goal'].value, '8');
    assert.equal(e.elements['experience-save'].disabled, false);
});

test('los campos se validan antes de guardar y una meta en cero pausa el contador', async () => {
    const e = entorno({ responses: [result({ weeklyGoal: 0, notificationMode: 'quiet' })] });
    const app = initLearnerExperience(e.doc, e.win);
    for (const value of ['-1', '21', '1.5', '', 'sin número']) { e.elements['experience-weekly-goal'].value = value; await app.save(); assert.equal(e.calls.length, 0); }
    assert.match(e.elements['experience-status'].textContent, /0 y 20/);
    e.elements['experience-weekly-goal'].value = '0'; e.elements['experience-notification-mode'].value = 'quiet'; await app.save();
    assert.match(e.elements['experience-weekly-summary'].textContent, /pausa/);
    assert.equal(e.elements['experience-weekly-progress'].getAttribute('aria-valuenow'), '0');
    assert.equal(e.notices.length, 0);
});

test('las acciones navegan a la tarea, capturan continuidad y agrupan los cambios por debounce', async () => {
    const e = entorno({ seed: result({ resume: { tab: 'evidencias', taskId: 5 } }, 1), responses: [result({ resume: { tab: 'evidencias', taskId: 5 } })] });
    const app = initLearnerExperience(e.doc, e.win);
    await e.elements['experience-next-action'].dispatch('click');
    assert.deepEqual(e.events.at(-1).detail, { tab: 'evidencias', taskId: 5, clearTaskFilters: true });
    await e.elements['experience-resume'].dispatch('click');
    await e.tab.dispatch('click');
    await e.root.dispatch('click', { target: e.taskControl });
    assert.equal([...e.timers.values()].filter(timer => timer.delay === 600).length, 1);
    await e.win.trigger(600);
    assert.equal(e.calls.length, 1);
    assert.deepEqual(JSON.parse(e.calls[0].options.body).preferences.resume, { tab: 'evidencias', taskId: 5 });
    app.navigate({ tab: 'desconocida', taskId: 5 }); assert.equal(e.events.length, 2);
});

test('los cambios que llegan mientras se guarda permanecen en el borrador y usan la revisión nueva', async () => {
    let resolver;
    const e = entorno({ responses: [() => new Promise(resolve => { resolver = resolve; }), result({ density: 'compact', weeklyGoal: 7 }, 3)] });
    const app = initLearnerExperience(e.doc, e.win);
    e.elements['experience-density'].value = 'compact'; const saving = app.save();
    e.elements['experience-weekly-goal'].value = '7'; await e.elements['experience-weekly-goal'].dispatch('change');
    resolver({ ok: true, status: 200, json: async () => result({ density: 'compact' }, 2) }); await saving;
    assert.equal(e.elements['experience-weekly-goal'].value, '7');
    await e.win.trigger(600);
    assert.equal(JSON.parse(e.calls[1].options.body).revision, 2);
    assert.equal(JSON.parse(e.calls[1].options.body).preferences.weeklyGoal, 7);
});

test('timeout, cambio de sesión y HTML nunca muestran confirmación falsa', async () => {
    const blocked = options => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('Abortado'))));
    const e = entorno({ responses: [blocked, { status: 401, detail: 'La sesión cambió.' }, { status: 400, html: true }] });
    const app = initLearnerExperience(e.doc, e.win);
    const saving = app.save(); e.win.trigger(15000); await saving;
    assert.match(e.elements['experience-status'].textContent, /tiempo/); assert.equal(e.elements['experience-save'].disabled, false);
    await e.elements['experience-retry'].dispatch('click'); assert.equal(e.elements['experience-save'].disabled, true);
    await e.elements['experience-retry'].dispatch('click'); assert.equal(e.calls[2].options.method, 'GET');
    assert.match(e.elements['experience-status'].textContent, /sesión/); assert.equal(e.notices.length, 0);
});

test('tolera vistas sin componente y recupera una semilla inválida leyendo el servidor', async () => {
    const vacio = entorno({ noSection: true }); assert.equal(initLearnerExperience(vacio.doc, vacio.win), null);
    const e = entorno({ responses: [result({ notificationMode: 'important' }, 2)] }); e.config.textContent = '{incompleto';
    const app = initLearnerExperience(e.doc, e.win); await app.ready;
    assert.equal(e.calls[0].options.method, 'GET'); assert.equal(e.optional.hidden, true);
    assert.equal(e.elements['experience-save'].disabled, false);
});

test('el script se inicializa automáticamente y descarta destinos inexistentes sin inventar tareas', async () => {
    const e = entorno({ seed: result({ resume: { tab: 'evidencias', taskId: 999 } }, 1) });
    vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/js/aprendiz_experiencia.js'), 'utf8'), { document: e.doc, window: e.win });
    await e.win.learnerExperience.ready;
    await e.elements['experience-resume'].dispatch('click');
    assert.equal(e.events[0].detail.taskId, null);
    assert.equal(e.events[0].detail.tab, 'evidencias');
});

test('valida las opciones y registra navegación externa sin ocultar alertas', async () => {
    const e = entorno({ responses: [result({ resume: { tab: 'grupo', taskId: null } })] });
    const app = initLearnerExperience(e.doc, e.win);
    e.elements['experience-density'].value = 'desconocida'; await app.save();
    assert.match(e.elements['experience-status'].textContent, /densidad/); assert.equal(e.calls.length, 0);
    e.elements['experience-density'].value = 'comfortable';
    await e.win.dispatch('learner:location', { detail: { tab: 'grupo', taskId: null } });
    await e.win.trigger(600);
    assert.deepEqual(JSON.parse(e.calls[0].options.body).preferences.resume, { tab: 'grupo', taskId: null });
    assert.equal(e.protectedNotice.hidden, false);
    await e.root.dispatch('toggle', { target: e.taskControl });
    assert.ok([...e.timers.values()].some(timer => timer.delay === 600));
});
