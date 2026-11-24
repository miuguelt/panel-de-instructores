// Planeación: el script de la página vive en static/js/planeacion.js, no en línea.
// La URL del estado de importación llega por data-estado-url y el script la usa tal cual.
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const RAIZ = path.join(__dirname, '..');
const SCRIPT = fs.readFileSync(path.join(RAIZ, 'app/static/js/planeacion.js'), 'utf8');
const PLANTILLA = fs.readFileSync(path.join(RAIZ, 'app/templates/instructor/planeacion.html'), 'utf8');

// Elemento mínimo: la página real siempre trae los contenedores que el script busca por id.
function elemento() {
    return {
        dataset: {}, style: {}, hidden: false, textContent: '', value: '',
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        addEventListener() {}, setAttribute() {}, getAttribute: () => null, removeAttribute() {},
        querySelector: () => null, querySelectorAll: () => [], appendChild() {}, closest: () => null,
    };
}

function entorno(pendiente) {
    const llamadas = { fetch: [], timeouts: [] };
    const vacio = () => elemento();
    const documento = {
        body: { addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} } },
        addEventListener() {},
        getElementById: vacio,
        querySelector: (selector) => (selector === '[data-importacion-id]' ? pendiente : null),
        querySelectorAll: () => [],
    };
    const ventana = {
        location: { href: 'http://localhost/instructor/fichas/7/planeacion?importacion_id=3', replace() {} },
        setTimeout: (fn, ms) => { llamadas.timeouts.push(ms); llamadas.pendiente = fn; return 1; },
        abrirModal() {}, cerrarModal() {}, print() {},
    };
    const contexto = {
        document: documento, window: ventana, console, URL,
        fetch: (url) => { llamadas.fetch.push(url); return Promise.resolve({ ok: false }); },
    };
    vm.createContext(contexto);
    vm.runInContext(SCRIPT, contexto);
    return { llamadas, ventana };
}

test('la plantilla carga el script externo y no trae JavaScript en línea', () => {
    assert.match(PLANTILLA, /<script src="\{\{ url_for\('static', filename='js\/planeacion\.js'\) \}\}" defer><\/script>/);
    assert.equal(/<script>\s*\(function \(\) \{/.test(PLANTILLA), false);
    assert.match(PLANTILLA, /data-estado-url="\{\{ url_for\('instructor\.estado_importacion'/);
});

test('sin importación pendiente no consulta el servidor', () => {
    const { llamadas } = entorno(null);
    assert.deepEqual(llamadas.fetch, []);
    assert.deepEqual(llamadas.timeouts, []);
});

test('con importación pendiente consulta la URL que llega en data-estado-url', () => {
    const pendiente = { dataset: { importacionId: '3', estadoUrl: '/instructor/fichas/7/importaciones/' } };
    const { llamadas } = entorno(pendiente);
    assert.deepEqual(llamadas.timeouts, [1200]);
    llamadas.pendiente();
    assert.deepEqual(llamadas.fetch, ['/instructor/fichas/7/importaciones/3']);
});

test('el script no contiene expresiones de Jinja', () => {
    assert.equal(/\{\{|\{%/.test(SCRIPT), false);
});
