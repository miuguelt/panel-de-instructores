const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const raiz = path.resolve(__dirname, '..');

test('cada módulo JavaScript de producción tiene sintaxis válida', () => {
    const carpeta = path.join(raiz, 'app/static/js');
    const archivos = fs.readdirSync(carpeta).filter(nombre => nombre.endsWith('.js'));
    assert.ok(archivos.length > 0);
    for (const archivo of archivos) {
        assert.doesNotThrow(() => new vm.Script(fs.readFileSync(path.join(carpeta, archivo), 'utf8'), { filename: archivo }));
    }
});

test('todos los formularios POST incluyen el campo CSRF que necesita el servidor', () => {
    function revisar(carpeta) {
        const pendientes = [];
        for (const entrada of fs.readdirSync(carpeta, { withFileTypes: true })) {
            const archivo = path.join(carpeta, entrada.name);
            if (entrada.isDirectory()) pendientes.push(...revisar(archivo));
            else if (entrada.name.endsWith('.html')) {
                const fuente = fs.readFileSync(archivo, 'utf8');
                for (const form of fuente.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/gi)) {
                    if (/method\s*=\s*["']POST["']/i.test(form[1]) && !form[2].includes('csrf_token')) pendientes.push(path.relative(raiz, archivo));
                }
            }
        }
        return pendientes;
    }
    assert.deepEqual(revisar(path.join(raiz, 'app/templates')), []);
});

test('reinicializar filas después de HTMX conserva un único listener y una sola navegación', () => {
    const filas = [{ dataset: {}, listeners: [], url: '/destino' }, { dataset: {}, listeners: [], url: '' }];
    for (const fila of filas) {
        fila.addEventListener = (nombre, callback) => fila.listeners.push(callback);
        fila.getAttribute = nombre => nombre === 'data-url' ? fila.url : null;
    }
    let navegaciones = 0;
    const location = { set href(valor) { assert.equal(valor, '/destino'); navegaciones++; } };
    const contexto = {
        window: { location },
        document: { addEventListener() {}, body: { addEventListener() {} }, querySelectorAll() { return filas; } },
    };
    vm.createContext(contexto);
    vm.runInContext(fs.readFileSync(path.join(raiz, 'app/static/js/table-filters.js'), 'utf8'), contexto);
    contexto.initClickableRows(); contexto.initClickableRows();
    assert.equal(filas[0].listeners.length, 1);
    assert.equal(filas[1].listeners.length, 1);
    filas[0].listeners[0].call(filas[0], { target: { closest() { return true; } } });
    assert.equal(navegaciones, 0);
    filas[0].listeners[0].call(filas[0], { target: { closest() { return null; } } });
    filas[1].listeners[0].call(filas[1], { target: { closest() { return null; } } });
    assert.equal(navegaciones, 1);
});

test('copiar texto confirma el resultado real e informa permisos denegados sin propagar errores', async () => {
    const { copiarTexto } = require('../app/static/js/portapapeles.js');
    const avisos = [];
    const copias = [];
    const entorno = { navigator: { clipboard: { async writeText(texto) { copias.push(texto); } } }, mostrarAviso(mensaje, opciones) { avisos.push([mensaje, opciones]); } };
    assert.equal(await copiarTexto('https://example.org/prueba', entorno), true);
    assert.deepEqual(copias, ['https://example.org/prueba']);
    assert.equal(avisos.at(-1)[1].intent, 'success');
    entorno.navigator.clipboard.writeText = async () => { throw Error('permiso denegado'); };
    assert.equal(await copiarTexto('https://example.org/prueba', entorno), false);
    assert.equal(avisos.at(-1)[1].intent, 'danger');
    assert.match(avisos.at(-1)[0], /manualmente/);
    const alertas = [];
    assert.equal(await copiarTexto('https://example.org/prueba', { navigator: {}, alert(mensaje) { alertas.push(mensaje); } }), false);
    assert.equal(alertas.length, 1);
    assert.match(alertas[0], /copiar/);
});

function importador(respuestas, presente = true) {
    const { initImportStatus } = require('../app/static/js/importaciones.js');
    class Elemento {
        constructor() { this.dataset = {}; this.children = []; this.attrs = new Map(); this.clases = new Set(); this.handlers = new Map(); this.classList = { add: (...valores) => valores.forEach(v => this.clases.add(v)), remove: (...valores) => valores.forEach(v => this.clases.delete(v)) }; }
        setAttribute(nombre, valor) { this.attrs.set(nombre, String(valor)); }
        append(...elementos) { this.children.push(...elementos); }
        addEventListener(nombre, callback) { this.handlers.set(nombre, callback); }
    }
    const box = new Elemento(); box.dataset.statusUrl = '/import-job';
    const mensaje = new Elemento();
    const timers = new Map(); let next = 0; const urls = []; const llamadas = [];
    const win = {
        AbortController,
        location: { href: 'https://panel.example/aprendices?importacion_id=4&estado=activo', replace(url) { urls.push(url); } },
        setTimeout(callback, demora) { timers.set(++next, { callback, demora }); return next; },
        clearTimeout(id) { timers.delete(id); },
        async fetch(url, opciones) {
            llamadas.push([url, opciones]);
            const respuesta = respuestas.shift();
            if (respuesta instanceof Error) throw respuesta;
            if (typeof respuesta === 'function') return respuesta(opciones);
            return { ok: true, status: 200, async json() { return respuesta; } };
        },
    };
    const doc = { getElementById(id) { return !presente ? null : id === 'import-status' ? box : mensaje; }, createElement() { return new Elemento(); } };
    const api = initImportStatus(doc, win);
    return { api, box, mensaje, timers, urls, llamadas, win, retry: () => box.children.find(el => el.id === 'import-status-retry'), refresh: () => box.children.find(el => el.id === 'import-status-refresh') };
}

test('una importación confirmada conserva advertencias y pide actualizar explícitamente', async () => {
    const estado = importador([{ estado: 'completado', resultado: { nuevos: 2, actualizados: 3, juicios_nuevos: 4, juicios_actualizados: 5, juicios_repetidos: 6, advertencias: ['Los indicadores están pendientes.', '<img src=x>'] } }]);
    await estado.api.ready;
    assert.match(estado.mensaje.textContent, /2 aprendices nuevos/);
    assert.match(estado.mensaje.textContent, /indicadores están pendientes/);
    assert.match(estado.mensaje.textContent, /<img src=x>/);
    assert.equal(estado.mensaje.attrs.get('role'), 'alert');
    assert.equal(estado.box.clases.has('alert-warning'), true);
    assert.equal(estado.box.attrs.get('aria-busy'), 'false');
    assert.equal(estado.refresh().hidden, false);
    assert.equal(estado.timers.size, 0);
    await estado.api.consultar(); assert.equal(estado.llamadas.length, 1);
    estado.refresh().handlers.get('click')();
    assert.deepEqual(estado.urls, ['https://panel.example/aprendices?estado=activo']);
});

test('las importaciones sin advertencias actualizan la vista y los estados intermedios no anuncian éxito', async () => {
    for (const resultado of [{ juicios_repetidos: 2 }, {}]) {
        const estado = importador([{ estado: 'completado', resultado }]); await estado.api.ready;
        assert.equal(estado.box.clases.has('alert-success'), true);
        const timer = [...estado.timers.values()].find(t => t.demora === 1200);
        assert.ok(timer); timer.callback(); assert.equal(estado.urls.length, 1);
    }
    const cola = importador([{ estado: 'encolado' }, { estado: 'procesando' }, { estado: 'error', error: 'El Excel no contiene aprendices.' }]);
    await cola.api.ready; assert.match(cola.mensaje.textContent, /cola/);
    await [...cola.timers.values()][0].callback(); assert.match(cola.mensaje.textContent, /leyendo/);
    await [...cola.timers.values()][0].callback(); assert.match(cola.mensaje.textContent, /no contiene aprendices/);
    assert.equal(cola.box.clases.has('alert-error'), true); assert.equal(cola.timers.size, 0);
    assert.equal(importador([], false).api, null);
});

test('los errores de consulta y el agotamiento de intentos conservan un reintento accionable', async () => {
    const estado = importador([new Error('sin conexión'), {}, { estado: 'encolado' }]);
    await estado.api.ready;
    assert.equal(estado.retry().hidden, false);
    assert.match(estado.mensaje.textContent, /No se pudo consultar/);
    await estado.retry().handlers.get('click')();
    assert.match(estado.mensaje.textContent, /respuesta.*válida/i);
    await estado.retry().handlers.get('click')();
    assert.match(estado.mensaje.textContent, /cola/);
    const pendientes = importador(Array.from({ length: 150 }, () => ({ estado: 'procesando' })));
    await pendientes.api.ready;
    for (let i = 1; i < 150; i++) await [...pendientes.timers.values()][0].callback();
    assert.equal(pendientes.timers.size, 0);
    assert.equal(pendientes.retry().hidden, false);
    assert.equal(pendientes.box.attrs.get('aria-busy'), 'false');
    assert.match(pendientes.mensaje.textContent, /No se pudo confirmar/);
});

test('una sesión vencida, JSON ilegible y una consulta que tarda demasiado informan la recuperación', async () => {
    const sesion = importador([async () => ({ ok: false, status: 401, async json() { return { error: 'Sesión expirada' }; } })]);
    await sesion.api.ready;
    assert.equal(sesion.timers.size, 0);
    assert.equal(sesion.refresh().hidden, false);
    assert.match(sesion.mensaje.textContent, /sesión/i);
    const sesionHtml = importador([async () => ({ ok: false, status: 401, async json() { throw Error('El servidor respondió HTML.'); } })]);
    await sesionHtml.api.ready;
    assert.equal(sesionHtml.timers.size, 0);
    assert.equal(sesionHtml.refresh().hidden, false);
    assert.match(sesionHtml.mensaje.textContent, /sesión/i);
    const sesionRedirigida = importador([async () => ({ ok: true, status: 200, redirected: true, async json() { throw Error('La redirección respondió con el formulario de ingreso.'); } })]);
    await sesionRedirigida.api.ready;
    assert.equal(sesionRedirigida.timers.size, 0);
    assert.equal(sesionRedirigida.refresh().hidden, false);
    assert.equal(sesionRedirigida.retry().hidden, true);
    assert.match(sesionRedirigida.mensaje.textContent, /sesión/i);
    const ilegible = importador([async () => ({ ok: true, status: 200, async json() { throw Error('HTML'); } })]);
    await ilegible.api.ready; assert.equal(ilegible.retry().hidden, false);
    assert.match(ilegible.mensaje.textContent, /respuesta.*válida/i);
    const lento = importador([opciones => new Promise((resolve, reject) => opciones.signal.addEventListener('abort', () => reject(Error('Tiempo agotado'))))]);
    await lento.api.consultar();
    [...lento.timers.values()].find(t => t.demora === 15000).callback();
    await lento.api.ready;
    assert.match(lento.mensaje.textContent, /tiempo de espera/i);
    assert.equal(lento.retry().disabled, false);
});
