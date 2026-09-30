const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const loadingScriptPath = path.resolve(__dirname, '../app/static/js/loading-indicator.js');
const baseTemplatePath = path.resolve(__dirname, '../app/templates/base.html');
const loadingStylesPath = path.resolve(__dirname, '../app/static/css/loading-indicator.css');

function crearEntorno(readyState = 'interactive') {
    const listeners = new Map();
    const listenersVentana = new Map();
    const atributosCuerpo = new Map();
    const atributosIndicador = new Map([['aria-hidden', 'false']]);
    const indicador = {
        hidden: false,
        setAttribute(nombre, valor) { atributosIndicador.set(nombre, String(valor)); },
        getAttribute(nombre) { return atributosIndicador.get(nombre) ?? null; }
    };
    const body = {
        setAttribute(nombre, valor) { atributosCuerpo.set(nombre, String(valor)); },
        getAttribute(nombre) { return atributosCuerpo.get(nombre) ?? null; },
        removeAttribute(nombre) { atributosCuerpo.delete(nombre); }
    };
    const document = {
        readyState,
        body,
        getElementById(id) { return id === 'app-loading-overlay' ? indicador : null; },
        addEventListener(nombre, callback) {
            const callbacks = listeners.get(nombre) ?? [];
            callbacks.push(callback);
            listeners.set(nombre, callbacks);
        },
        emitir(nombre, evento = {}) {
            (listeners.get(nombre) ?? []).forEach((callback) => callback(evento));
        }
    };
    const window = {
        location: new URL('https://panel.example/instructor/dashboard'),
        addEventListener(nombre, callback) {
            const callbacks = listenersVentana.get(nombre) ?? [];
            callbacks.push(callback);
            listenersVentana.set(nombre, callbacks);
        },
        emitir(nombre, evento = {}) {
            (listenersVentana.get(nombre) ?? []).forEach((callback) => callback(evento));
        }
    };

    global.document = document;
    global.window = window;
    global.URL = URL;
    global.queueMicrotask = queueMicrotask;
    delete require.cache[require.resolve(loadingScriptPath)];
    require(loadingScriptPath);
    return { document, window, indicador, body };
}

function crearEnlace(href, opciones = {}) {
    const url = new URL(href, 'https://panel.example/instructor/dashboard');
    return {
        href: url.href,
        origin: url.origin,
        target: opciones.target ?? '',
        getAttribute(nombre) {
            if (nombre === 'href') return href;
            if (nombre === 'hx-boost') return opciones.hxBoost ?? null;
            return null;
        },
        hasAttribute(nombre) {
            if (nombre === 'download') return Boolean(opciones.descarga);
            if (nombre === 'data-no-loading') return Boolean(opciones.sinCarga);
            return false;
        }
    };
}

function objetivo(enlace = null, formulario = null) {
    return {
        closest(selector) {
            if (selector === 'a[href]') return enlace;
            if (selector === 'form') return formulario;
            return null;
        }
    };
}

async function vaciarMicrotareas() {
    await Promise.resolve();
}

test('la plantilla incluye el indicador bloqueante y sus estilos', () => {
    const plantilla = fs.readFileSync(baseTemplatePath, 'utf8');
    const estilos = fs.readFileSync(loadingStylesPath, 'utf8');

    assert.match(plantilla, /id="app-loading-overlay"/);
    assert.match(plantilla, /Cargando la aplicación/);
    assert.match(plantilla, /css\/loading-indicator\.css/);
    assert.match(plantilla, /js\/loading-indicator\.js/);
    assert.match(estilos, /position: fixed/);
    assert.match(estilos, /inset: 0/);
    assert.match(estilos, /\.app-loading-overlay\[hidden\]/);
    assert.match(estilos, /prefers-reduced-motion/);
});

test('el indicador se oculta cuando termina la carga inicial del documento', () => {
    const entorno = crearEntorno('loading');

    assert.equal(entorno.indicador.hidden, false);
    entorno.document.emitir('DOMContentLoaded');
    assert.equal(entorno.indicador.hidden, true);
    assert.equal(entorno.indicador.getAttribute('aria-hidden'), 'true');
    assert.equal(entorno.body.getAttribute('aria-busy'), 'false');
});

test('muestra y bloquea la interfaz al abrir una ruta interna', async () => {
    const entorno = crearEntorno();
    const evento = {
        target: objetivo(crearEnlace('/instructor/fichas')),
        button: 0,
        defaultPrevented: false
    };

    entorno.document.emitir('click', evento);
    await vaciarMicrotareas();

    assert.equal(entorno.indicador.hidden, false);
    assert.equal(entorno.indicador.getAttribute('aria-hidden'), 'false');
    assert.equal(entorno.body.getAttribute('aria-busy'), 'true');
});

test('no bloquea interacciones que no navegan dentro de la aplicación', async () => {
    const enlaceInvalido = crearEnlace('/instructor/fichas');
    enlaceInvalido.href = 'http://[';
    const casos = [
        { enlace: crearEnlace('#contenido') },
        { enlace: crearEnlace('https://externo.example/recurso') },
        { enlace: crearEnlace('/descargar/archivo') },
        { enlace: crearEnlace('/reporte/exportar') },
        { enlace: crearEnlace('/archivo/plantilla') },
        { enlace: crearEnlace('/auth/logout') },
        { enlace: enlaceInvalido },
        { enlace: crearEnlace('/instructor/fichas', { target: '_blank' }) },
        { enlace: crearEnlace('/archivo', { descarga: true }) },
        { enlace: crearEnlace('/instructor/fichas', { sinCarga: true }) },
        { enlace: crearEnlace('/instructor/fichas', { hxBoost: 'false' }) },
        { enlace: crearEnlace('/instructor/fichas'), button: 1 },
        { enlace: crearEnlace('/instructor/fichas'), ctrlKey: true },
        { enlace: crearEnlace('/instructor/fichas'), metaKey: true },
        { enlace: crearEnlace('/instructor/fichas'), shiftKey: true },
        { enlace: crearEnlace('/instructor/fichas'), altKey: true },
        { enlace: crearEnlace('/instructor/fichas'), defaultPrevented: true },
        { enlace: null }
    ];

    for (const caso of casos) {
        const entorno = crearEntorno();
        entorno.document.emitir('click', {
            target: objetivo(caso.enlace),
            button: caso.button ?? 0,
            ctrlKey: caso.ctrlKey ?? false,
            metaKey: caso.metaKey ?? false,
            shiftKey: caso.shiftKey ?? false,
            altKey: caso.altKey ?? false,
            defaultPrevented: caso.defaultPrevented ?? false
        });
        await vaciarMicrotareas();
        assert.equal(entorno.indicador.hidden, true);
    }
});

test('muestra el indicador al enviar formularios de la aplicación', async () => {
    const entorno = crearEntorno();
    const formulario = {
        target: '',
        getAttribute(nombre) { return nombre === 'method' ? 'post' : null; },
        hasAttribute() { return false; }
    };

    entorno.document.emitir('submit', { target: objetivo(null, formulario), defaultPrevented: false });
    await vaciarMicrotareas();

    assert.equal(entorno.indicador.hidden, false);
    assert.equal(entorno.body.getAttribute('aria-busy'), 'true');
});

test('ignora envíos cancelados, de diálogo y dirigidos a otra pestaña', async () => {
    const casos = [
        { defaultPrevented: true, target: '', method: 'post' },
        { defaultPrevented: false, target: '_blank', method: 'post' },
        { defaultPrevented: false, target: '', method: 'dialog' },
        { defaultPrevented: false, target: '', method: 'post', sinCarga: true },
        { defaultPrevented: false, target: '', method: 'post', hxBoost: 'false' }
    ];

    for (const caso of casos) {
        const entorno = crearEntorno();
        const formulario = {
            target: caso.target,
            getAttribute(nombre) {
                if (nombre === 'method') return caso.method;
                if (nombre === 'hx-boost') return caso.hxBoost ?? null;
                return null;
            },
            hasAttribute(nombre) {
                return nombre === 'data-no-loading' && Boolean(caso.sinCarga);
            }
        };

        entorno.document.emitir('submit', {
            target: objetivo(null, formulario),
            defaultPrevented: caso.defaultPrevented
        });
        await vaciarMicrotareas();
        assert.equal(entorno.indicador.hidden, true);
    }
});

test('omite la carga si otro controlador cancela el evento después del indicador', async () => {
    const entorno = crearEntorno();
    entorno.document.addEventListener('submit', (evento) => { evento.defaultPrevented = true; });
    const formulario = {
        target: '',
        getAttribute() { return 'post'; },
        hasAttribute() { return false; }
    };

    entorno.document.emitir('submit', { target: objetivo(null, formulario), defaultPrevented: false });
    await vaciarMicrotareas();

    assert.equal(entorno.indicador.hidden, true);
});

test('mantiene el indicador durante solicitudes simultáneas de HTMX', async () => {
    const entorno = crearEntorno();

    entorno.document.emitir('htmx:beforeRequest', { defaultPrevented: false });
    entorno.document.emitir('htmx:beforeRequest', { defaultPrevented: false });
    await vaciarMicrotareas();
    assert.equal(entorno.indicador.hidden, false);

    entorno.document.emitir('htmx:afterRequest');
    assert.equal(entorno.indicador.hidden, false);
    entorno.document.emitir('htmx:afterRequest');
    assert.equal(entorno.indicador.hidden, true);
    entorno.document.emitir('htmx:afterRequest');
    assert.equal(entorno.indicador.hidden, true);
});

test('limpia la carga al cancelar HTMX y al volver a la página', async () => {
    const entorno = crearEntorno();

    entorno.document.emitir('htmx:beforeRequest', { defaultPrevented: true });
    await vaciarMicrotareas();
    assert.equal(entorno.indicador.hidden, true);

    entorno.window.emitir('beforeunload');
    assert.equal(entorno.indicador.hidden, false);
    entorno.window.emitir('pageshow');
    assert.equal(entorno.indicador.hidden, true);
    assert.equal(entorno.body.getAttribute('aria-busy'), 'false');
});
