const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const modalScript = path.resolve(__dirname, '../app/static/js/modal-system.js');
const modalStyles = path.resolve(__dirname, '../app/static/css/modal-system.css');
const baseTemplate = path.resolve(__dirname, '../app/templates/base.html');
const templatesRoot = path.resolve(__dirname, '../app/templates');

function listarPlantillas(carpeta) {
    return fs.readdirSync(carpeta, { withFileTypes: true }).flatMap((entrada) => {
        const ruta = path.join(carpeta, entrada.name);
        return entrada.isDirectory() ? listarPlantillas(ruta) : ruta.endsWith('.html') ? [ruta] : [];
    });
}

class ClassList {
    constructor(...names) { this.names = new Set(names); }
    add(...names) { names.forEach((name) => this.names.add(name)); }
    remove(...names) { names.forEach((name) => this.names.delete(name)); }
    contains(name) { return this.names.has(name); }
    toggle(name, force) {
        const enabled = force ?? !this.contains(name);
        if (enabled) this.add(name); else this.remove(name);
        return enabled;
    }
}

class Elemento {
    constructor(tagName = 'DIV', id = '', classes = []) {
        this.tagName = tagName.toUpperCase();
        this.id = id;
        this.classList = new ClassList(...classes);
        this.attributes = new Map();
        this.dataset = {};
        this.listeners = new Map();
        this.children = [];
        this.focusables = [];
        this.open = false;
        this.hidden = false;
        this.disabled = false;
        this.isConnected = true;
        this.returnValue = '';
        this.textContent = '';
        this.submitCount = 0;
        this.ownerDocument = null;
        this.parentNode = null;
    }

    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    hasAttribute(name) { return this.attributes.has(name); }
    addEventListener(name, callback) {
        const callbacks = this.listeners.get(name) ?? [];
        callbacks.push(callback);
        this.listeners.set(name, callbacks);
    }
    dispatch(name, detail = {}) {
        const event = { target: this, currentTarget: this, preventDefault() { this.defaultPrevented = true; }, ...detail };
        (this.listeners.get(name) ?? []).forEach((callback) => callback.call(this, event));
        if (name === 'close' && this.ownerDocument) this.ownerDocument.dispatch(name, { target: this });
        return event;
    }
    querySelectorAll(selector) {
        if (selector.includes('button') || selector.includes('input') || selector.includes('a[href')) return this.focusables;
        return this.children;
    }
    querySelector(selector) {
        return this.selectors?.[selector] ?? this.querySelectorAll(selector)[0] ?? null;
    }
    contains(element) { return this === element || this.children.some((child) => child.contains(element)); }
    appendChild(element) {
        element.parentNode = this;
        element.ownerDocument = this.ownerDocument;
        this.children.push(element);
        return element;
    }
    remove() {
        this.isConnected = false;
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    }
    focus() { this.ownerDocument.activeElement = this; this.focused = true; }
    showModal() { this.open = true; }
    close(value = '') {
        this.open = false;
        this.returnValue = value;
        this.dispatch('close');
    }
    requestSubmit(submitter) {
        this.submitCount += 1;
        this.ownerDocument.dispatch('submit', { target: this, submitter, preventDefault() { this.defaultPrevented = true; } });
    }
}

function entorno({ elementos = [], activo = null } = {}) {
    const listeners = new Map();
    const body = new Elemento('BODY');
    const document = {
        body,
        activeElement: activo ?? body,
        getElementById(id) {
            const buscar = (padre) => padre.id === id ? padre : padre.children.map(buscar).find(Boolean) ?? null;
            return elementos.find((element) => element.id === id) ?? buscar(body);
        },
        createElement(tag) { const element = new Elemento(tag); element.ownerDocument = document; return element; },
        querySelectorAll() {
            return elementos.filter((element) => element.open || element.classList.contains('is-open'));
        },
        addEventListener(name, callback) {
            const callbacks = listeners.get(name) ?? [];
            callbacks.push(callback);
            listeners.set(name, callbacks);
        },
        dispatch(name, detail = {}) {
            const event = { preventDefault() { this.defaultPrevented = true; }, ...detail };
            (listeners.get(name) ?? []).forEach((callback) => callback(event));
            return event;
        },
    };
    if (activo) activo.ownerDocument = document;
    const asignarDocumento = (element) => {
        element.ownerDocument = document;
        element.children.forEach(asignarDocumento);
        element.focusables.forEach(asignarDocumento);
    };
    elementos.forEach(asignarDocumento);
    body.ownerDocument = document;
    const window = { document, setTimeout(callback) { window.pendingTimer = callback; return 1; } };
    delete require.cache[require.resolve(modalScript)];
    global.window = window;
    global.document = document;
    require(modalScript);
    delete global.window;
    delete global.document;
    return { window, document, body };
}

function boton(document, label = '') {
    const element = new Elemento('BUTTON');
    element.textContent = label;
    element.ownerDocument = document;
    return element;
}

test('los diálogos nativos abren, bloquean el fondo y devuelven el foco', () => {
    const disparador = new Elemento('BUTTON', 'abrir');
    const modal = new Elemento('DIALOG', 'detalle', ['app-modal-overlay']);
    const cerrar = boton(null, 'Cerrar');
    modal.focusables = [cerrar];
    modal.children = [cerrar];
    const { window, document, body } = entorno({ elementos: [modal], activo: disparador });

    assert.equal(window.ModalSystem.open('detalle'), true);
    assert.equal(modal.open, true);
    assert.equal(body.classList.contains('modal-open'), true);
    assert.equal(document.activeElement, cerrar);

    assert.equal(window.ModalSystem.close('detalle'), true);
    assert.equal(modal.open, false);
    assert.equal(body.classList.contains('modal-open'), false);
    assert.equal(document.activeElement, disparador);
});

test('los diálogos propios limitan el foco y responden a Escape y al fondo', () => {
    const modal = new Elemento('DIV', 'propio', ['app-modal-overlay']);
    modal.setAttribute('role', 'dialog');
    const primero = boton(null, 'Cerrar');
    const ultimo = boton(null, 'Guardar');
    modal.focusables = [primero, ultimo];
    modal.children = [primero, ultimo];
    const { window, document, body } = entorno({ elementos: [modal] });

    window.ModalSystem.open('propio');
    assert.equal(modal.classList.contains('is-open'), true);
    assert.equal(modal.getAttribute('aria-hidden'), 'false');
    assert.equal(document.activeElement, primero);

    ultimo.focus();
    document.dispatch('keydown', { key: 'Tab', shiftKey: false, target: ultimo });
    assert.equal(document.activeElement, primero);
    primero.focus();
    document.dispatch('keydown', { key: 'Tab', shiftKey: true, target: primero });
    assert.equal(document.activeElement, ultimo);

    const escape = document.dispatch('keydown', { key: 'Escape', target: ultimo });
    assert.equal(escape.defaultPrevented, true);
    assert.equal(modal.classList.contains('is-open'), false);
    assert.equal(body.classList.contains('modal-open'), false);

    window.ModalSystem.open('propio');
    document.dispatch('click', { target: modal });
    assert.equal(modal.classList.contains('is-open'), false);
});

test('no cierra por el fondo una ventana en estado de carga', () => {
    const modal = new Elemento('DIV', 'cargando', ['app-modal-overlay', 'is-loading', 'is-open']);
    const { window, document } = entorno({ elementos: [modal] });
    document.dispatch('click', { target: modal });
    assert.equal(modal.classList.contains('is-open'), true);
    assert.equal(window.ModalSystem.close('inexistente'), false);
});

test('la confirmación accesible permite cancelar o continuar el envío del formulario', async () => {
    const titulo = new Elemento('H2');
    const mensaje = new Elemento('P');
    const aceptar = boton(null, 'Confirmar');
    const cancelar = boton(null, 'Cancelar');
    aceptar.dataset.confirmAccept = '';
    cancelar.dataset.confirmCancel = '';
    const dialogo = new Elemento('DIALOG', 'modal-confirmacion', ['app-modal-overlay']);
    dialogo.focusables = [cancelar, aceptar];
    dialogo.children = [titulo, mensaje, cancelar, aceptar];
    dialogo.selectors = {
        '[data-confirm-title]': titulo,
        '[data-confirm-message]': mensaje,
        '[data-confirm-accept]': aceptar,
        '[data-confirm-cancel]': cancelar,
    };
    const formulario = new Elemento('FORM');
    formulario.dataset.confirm = '¿Continuar?';
    const enviar = boton(null, 'Eliminar');
    enviar.dataset.confirmLabel = 'Eliminar';
    const { window, document, body } = entorno({ elementos: [dialogo, formulario] });
    aceptar.ownerDocument = document;
    cancelar.ownerDocument = document;
    formulario.requestSubmit = function (submitter) {
        this.submitCount += 1;
        document.dispatch('submit', { target: this, submitter });
    };

    const intento = document.dispatch('submit', { target: formulario, submitter: enviar });
    assert.equal(intento.defaultPrevented, true);
    assert.equal(dialogo.open, true);
    assert.equal(mensaje.textContent, '¿Continuar?');
    assert.equal(aceptar.textContent, 'Eliminar');
    assert.equal(body.classList.contains('modal-open'), true);

    document.dispatch('click', { target: cancelar });
    await Promise.resolve();
    assert.equal(formulario.submitCount, 0);
    assert.equal(body.classList.contains('modal-open'), false);

    document.dispatch('submit', { target: formulario, submitter: enviar });
    document.dispatch('click', { target: aceptar });
    await Promise.resolve();
    assert.equal(formulario.submitCount, 1);
    assert.equal(dialogo.open, false);
});

test('los avisos se anuncian, permiten cerrarse y desaparecen al terminar su plazo', () => {
    const { window, document, body } = entorno();
    const aviso = window.mostrarAviso('No se pudo guardar.', { title: 'Error', intent: 'danger', duration: 2500 });
    const region = document.getElementById('avisos-emergentes');

    assert.equal(region.getAttribute('aria-live'), 'polite');
    assert.equal(aviso.getAttribute('role'), 'alert');
    assert.equal(aviso.classList.contains('is-danger'), true);
    assert.equal(aviso.children[0].children[0].textContent, 'Error');
    assert.equal(aviso.children[0].children[1].textContent, 'No se pudo guardar.');
    assert.equal(body.children.includes(region), true);

    aviso.children[1].dispatch('click');
    assert.equal(aviso.isConnected, false);

    const avisoTemporal = window.mostrarAviso('Cambios guardados.');
    window.pendingTimer();
    assert.equal(avisoTemporal.isConnected, false);
});

test('el diseño compartido conserva uso móvil, teclado y movimiento reducido', () => {
    const css = fs.readFileSync(modalStyles, 'utf8');
    const base = fs.readFileSync(baseTemplate, 'utf8');
    assert.match(css, /@media \(max-width: 600px\)/);
    assert.match(css, /prefers-reduced-motion/);
    assert.match(css, /min-height: 42px/);
    assert.match(base, /id="modal-confirmacion"/);
    assert.match(base, /js\/modal-system\.js/);
});

test('las plantillas no invocan cuadros nativos de confirmación o alerta', () => {
    listarPlantillas(templatesRoot).forEach((ruta) => {
        const contenido = fs.readFileSync(ruta, 'utf8');
        assert.doesNotMatch(contenido, /\b(?:window\.)?confirm\s*\(|\balert\s*\(/, ruta);
    });
});
