const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

const script = path.resolve(__dirname, '../app/static/js/uploads.js');

class Elemento {
    constructor(tag = 'div') {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.attributes = new Map();
        this.style = {};
        this.disabled = false;
        this.className = '';
        this.textContent = '';
        this.listeners = new Map();
    }
    appendChild(child) { child.parent = this; this.children.push(child); return child; }
    remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
    setAttribute(key, value) { this.attributes.set(key, String(value)); }
    getAttribute(key) { return this.attributes.get(key) ?? null; }
    hasAttribute(key) { return this.attributes.has(key); }
    removeAttribute(key) { this.attributes.delete(key); }
    addEventListener(name, handler) { this.listeners.set(name, handler); }
    emitir(name, event = {}) { this.listeners.get(name)?.(event); }
    focus() { this.focused = true; }
    querySelector(selector) {
        return this.children.find(child => `.${child.className}` === selector)
            ?? this.children.map(child => child.querySelector(selector)).find(Boolean) ?? null;
    }
}

function entorno(opciones = {}) {
    const solicitudes = [];
    class XHR extends Elemento {
        constructor() { super(); this.upload = new Elemento(); solicitudes.push(this); }
        open(method, url) { if (opciones.fallaAbrir) throw Error('sin conexión'); this.method = method; this.url = url; }
        setRequestHeader(name, value) { this.setAttribute(name, value); }
        getResponseHeader() { return this.tipo ?? ''; }
        send(datos) { if (opciones.fallaEnviar) throw Error('sin conexión'); this.datos = datos; }
        responder(status, cuerpo, tipo = 'application/json', responseURL = '/destino') {
            this.status = status;
            this.responseText = typeof cuerpo === 'string' ? cuerpo : JSON.stringify(cuerpo);
            this.tipo = tipo;
            this.responseURL = responseURL;
            this.emitir('load');
        }
    }
    class Datos {
        constructor(form) {
            if (opciones.fallaDatos) throw Error('archivo no disponible');
            this.campos = form.botones.filter(boton => !boton.disabled).map(boton => boton.name);
            this.anexos = [];
        }
        append(name, value) { this.anexos.push([name, value]); }
    }
    const document = new Elemento('document');
    document.createElement = tag => new Elemento(tag);
    let recargas = 0;
    const window = {
        FormData: opciones.sinSoporte ? undefined : Datos,
        XMLHttpRequest: XHR,
        ADSO_MAX_UPLOAD_BYTES: opciones.limite ?? 1000,
        ADSO_MAX_REQUEST_BYTES: opciones.limiteTotal ?? 1500,
        location: { href: '/origen', reload() { recargas++; } },
    };
    const reanudadas = [];
    let restauraciones = 0;
    if (opciones.reanudable) {
        window.ADSO_RESUMABLE_UPLOAD = { enabled: true, maxBytes: 10000, url: '/cargas' };
        window.crypto = { subtle: {}, randomUUID() { return 'id-de-prueba'; } }; window.fetch = () => {};
        window.ADSOCargasReanudables = {
            restaurar() { restauraciones++; },
            iniciar(...args) { reanudadas.push(args); },
        };
    }
    global.document = document;
    global.window = window;
    global.XMLHttpRequest = XHR;
    global.FormData = Datos;
    global.DOMParser = class {
        parseFromString(texto) {
            return { querySelector(selector) {
                if (selector.includes('password')) return texto.includes('type="password"') ? {} : null;
                return texto.includes('alert-error') ? { textContent: 'El archivo está dañado.' } : null;
            } };
        }
    };
    delete require.cache[require.resolve(script)];
    require(script);
    function formulario(archivos = [{ name: 'proyecto.zip', size: 100, type: 'application/zip' }], accept = '.zip') {
        const form = new Elemento('form');
        form.method = 'POST'; form.action = '/cargar'; form.enctype = 'multipart/form-data';
        const input = new Elemento('input'); input.files = archivos; input.name = 'archivo';
        input.setAttribute('accept', accept);
        const activo = new Elemento('button'); activo.name = 'accion'; activo.value = 'subir';
        const inactivo = new Elemento('button'); inactivo.disabled = true;
        form.botones = [activo, inactivo]; form.inputs = [input];
        form.querySelectorAll = selector => selector === 'input[type="file"]' ? form.inputs : form.botones;
        return form;
    }
    function enviar(form, extras = {}) {
        const evento = { target: form, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extras };
        document.emitir('submit', evento);
        return evento;
    }
    return { solicitudes, document, window, formulario, enviar, reanudadas, restauraciones: () => restauraciones, recargas: () => recargas };
}

test('evita envíos simultáneos y conserva la acción del botón antes de bloquear', () => {
    const e = entorno(); const form = e.formulario();
    e.enviar(form, { submitter: form.botones[0] });
    e.enviar(form);
    assert.equal(e.solicitudes.filter(xhr => xhr.datos).length, 1);
    const xhr = e.solicitudes.find(xhr => xhr.datos);
    assert.ok(xhr.datos.campos.includes('accion'));
    assert.deepEqual(xhr.datos.anexos, [['accion', 'subir']]);
    assert.equal(form.botones[0].disabled, true);
});

test('recupera el formulario sin habilitar botones que ya estaban bloqueados', () => {
    const e = entorno(); const form = e.formulario();
    e.enviar(form);
    e.solicitudes.at(-1).responder(400, { ok: false, error: 'El ZIP está dañado.' });
    assert.equal(form.botones[0].disabled, false);
    assert.equal(form.botones[1].disabled, true);
    assert.equal(form.querySelector('.upload-progress'), null);
    assert.equal(form.querySelector('.upload-error').textContent, 'El ZIP está dañado.');
    e.enviar(form);
    assert.equal(form.querySelector('.upload-error'), null);
    assert.equal(e.solicitudes.filter(xhr => xhr.datos).length, 2);
});

test('respeta formularios sin archivo, envíos cancelados y formularios con controlador propio', () => {
    const e = entorno();
    for (const form of [null, new Elemento(), e.formulario([])]) assert.equal(e.enviar(form).defaultPrevented, false);
    const normal = e.formulario(); normal.enctype = '';
    assert.equal(e.enviar(normal).defaultPrevented, false);
    const propio = e.formulario(); propio.setAttribute('data-sin-progreso', '');
    assert.equal(e.enviar(propio).defaultPrevented, false);
    assert.equal(e.enviar(e.formulario(), { defaultPrevented: true }).defaultPrevented, true);
    assert.equal(e.solicitudes.filter(xhr => xhr.datos).length, 0);
    const sinSoporte = entorno({ sinSoporte: true });
    assert.equal(sinSoporte.enviar(sinSoporte.formulario()).defaultPrevented, false);
});

test('valida MIME y extensiones combinadas sin bloquear formatos aceptados', () => {
    const e = entorno();
    const casos = [
        ['imagen.webp', 'image/webp', ' .zip , image/* '],
        ['imagen.webp', 'image/webp', 'image/webp'],
        ['PROYECTO.ZIP', '', '.zip'],
        ['archivo', '', ''],
    ];
    for (const [name, type, accept] of casos) {
        const form = e.formulario([{ name, type, size: 100 }], accept);
        assert.equal(e.enviar(form).defaultPrevented, true);
        assert.equal(form.querySelector('.upload-error'), null);
        e.solicitudes.at(-1).emitir('abort');
    }
    const invalido = e.formulario([{ name: 'app.exe', type: 'application/octet-stream', size: 20 }], '.zip,image/*');
    e.enviar(invalido);
    assert.match(invalido.querySelector('.upload-error').textContent, /formato permitido/);
    assert.equal(invalido.querySelector('.upload-error').getAttribute('role'), 'alert');
});

test('informa archivos vacíos, límites por archivo y por solicitud y carpetas', () => {
    const e = entorno();
    const casos = [
        [[{ name: 'vacio.zip', size: 0 }], /vacío/],
        [[{ name: 'grande.zip', size: 1100 }], /máximo permitido/],
        [[{ name: 'a.zip', size: 800 }, { name: 'b.zip', size: 800 }], /subida.*máximo/i],
        [[{ name: 'a.zip', size: 10, webkitRelativePath: 'carpeta/a.zip' }], /comprime.*ZIP/i],
    ];
    for (const [archivos, mensaje] of casos) {
        const form = e.formulario(archivos); e.enviar(form);
        assert.match(form.querySelector('.upload-error').textContent, mensaje);
        e.enviar(form);
        assert.equal(form.children.filter(child => child.className === 'upload-error').length, 1);
    }
    const carpeta = e.formulario([]); carpeta.inputs[0].setAttribute('webkitdirectory', '');
    e.enviar(carpeta);
    assert.match(carpeta.querySelector('.upload-error').textContent, /comprime.*ZIP/i);
});

test('muestra progreso y navega únicamente cuando se confirma la carga', () => {
    const e = entorno(); const form = e.formulario(); e.enviar(form);
    const xhr = e.solicitudes.at(-1);
    xhr.upload.emitir('progress', { lengthComputable: false });
    assert.match(form.querySelector('.upload-progress-text').textContent, /Subiendo archivo/);
    xhr.upload.emitir('progress', { lengthComputable: true, loaded: 50, total: 100 });
    assert.match(form.querySelector('.upload-progress-text').textContent, /50%/);
    xhr.upload.emitir('load');
    assert.match(form.querySelector('.upload-progress-text').textContent, /Esperando confirmación/);
    xhr.responder(200, { ok: true, redirect: '/confirmado' });
    assert.equal(e.window.location.href, '/confirmado');
});

test('presenta errores HTTP, JSON inválido y la recuperación de sesión', () => {
    const e = entorno();
    for (const status of [400, 401, 403, 413, 429, 502, 503, 504, 418]) {
        const form = e.formulario(); e.enviar(form);
        e.solicitudes.at(-1).responder(status, 'no es JSON', 'application/json');
        assert.ok(form.querySelector('.upload-error').textContent.length > 15);
        assert.equal(e.window.location.href, '/origen');
    }
    const form = e.formulario(); e.enviar(form);
    e.solicitudes.at(-1).responder(400, { ok: false, message: 'La sesión expiró.', reload: true });
    const aviso = form.querySelector('.upload-error');
    assert.equal(aviso.textContent, 'La sesión expiró.');
    aviso.children[0].emitir('click');
    assert.equal(e.recargas(), 1);
});

test('conserva mensajes de error de HTML heredado y admite su éxito', () => {
    const e = entorno(); const form = e.formulario(); e.enviar(form);
    e.solicitudes.at(-1).responder(200, '<p class="alert-error">El archivo está dañado.</p>', 'text/html');
    assert.match(form.querySelector('.upload-error').textContent, /dañado/);
    assert.equal(e.window.location.href, '/origen');
    e.enviar(form);
    e.solicitudes.at(-1).responder(200, '<h1>Materiales</h1>', 'text/html', '/materiales');
    assert.equal(e.window.location.href, '/materiales');
});

test('una respuesta JSON incompleta no se presenta como una carga exitosa', () => {
    const e = entorno(); const form = e.formulario(); e.enviar(form);
    e.solicitudes.at(-1).responder(200, '{', 'application/json');
    assert.equal(e.window.location.href, '/origen');
    assert.match(form.querySelector('.upload-error').textContent, /confirmar.*carga/i);
    assert.equal(form.botones[0].disabled, false);
});

test('muestra errores problem+json y permite recuperar una sesión incluso sin reload explícito', () => {
    const e = entorno(); const form = e.formulario(); e.enviar(form);
    e.solicitudes.at(-1).responder(400, { detail: 'La fotografía está dañada.', error: 'invalid' }, 'application/problem+json; charset=utf-8');
    assert.equal(form.querySelector('.upload-error').textContent, 'La fotografía está dañada.');
    e.enviar(form);
    e.solicitudes.at(-1).responder(401, { message: 'La sesión terminó.' });
    assert.equal(form.querySelector('.upload-error').children[0].textContent, 'Recargar formulario');
    assert.equal(e.window.location.href, '/origen');
});

test('detecta una redirección heredada al formulario de ingreso sin anunciar éxito', () => {
    const e = entorno(); const form = e.formulario(); e.enviar(form);
    e.solicitudes.at(-1).responder(200, '<form class="auth-form"><input type="password"></form>', 'text/html', '/auth/login');
    assert.equal(e.window.location.href, '/origen');
    assert.match(form.querySelector('.upload-error').textContent, /sesión terminó/i);
    assert.equal(form.querySelector('.upload-error').children[0].textContent, 'Recargar formulario');
});

test('recupera fallas de red, cancelación, tiempo agotado y arranque de XHR', () => {
    for (const evento of ['error', 'abort', 'timeout']) {
        const e = entorno(); const form = e.formulario(); e.enviar(form);
        e.solicitudes.at(-1).emitir(evento);
        assert.match(form.querySelector('.upload-error').textContent, /antes de volver/);
        assert.equal(form.botones[0].disabled, false);
    }
    for (const opciones of [{ fallaEnviar: true }, { fallaAbrir: true }, { fallaDatos: true }]) {
        const e = entorno(opciones); const form = e.formulario();
        assert.doesNotThrow(() => e.enviar(form));
        assert.match(form.querySelector('.upload-error').textContent, /iniciar la subida/);
        assert.equal(form.botones[0].disabled, false);
    }
});

test('el flujo reanudable admite el límite por archivo y conserva los campos y la acción del formulario', () => {
    const e = entorno({ reanudable: true, limite: 10, limiteTotal: 15 });
    const form = e.formulario([{ name: 'grande.zip', size: 2000, type: 'application/zip' }]);
    e.enviar(form, { submitter: form.botones[0] });
    assert.equal(e.restauraciones(), 1);
    assert.equal(e.reanudadas.length, 1);
    const [recibido, datos, seleccion, _ui, callbacks, config] = e.reanudadas[0];
    assert.equal(recibido, form);
    assert.equal(seleccion[0].archivo.size, 2000);
    assert.deepEqual(datos.anexos, [['accion', 'subir']]);
    assert.equal(config.maxBytes, 10000);
    assert.equal(e.solicitudes.filter(xhr => xhr.datos).length, 0);
    callbacks.fallar('Conservamos el avance.');
    assert.equal(form.botones[0].disabled, false);
    assert.match(form.querySelector('.upload-error').textContent, /avance/);
});
