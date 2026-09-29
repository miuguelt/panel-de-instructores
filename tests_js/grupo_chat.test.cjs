const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const chatScript = path.resolve(__dirname, '../app/static/js/grupo_chat.js');
const chatSource = fs.readFileSync(chatScript, 'utf8');

class ElementoFalso {
    constructor({ connected = true, value = '' } = {}) {
        this.children = [];
        this.connected = connected;
        this.dataset = {};
        this.disabled = false;
        this.listeners = new Map();
        this.parentNode = null;
        this.scrollHeight = 120;
        this.scrollTop = 0;
        this.clientHeight = 80;
        this.textContent = '';
        this.value = value;
        this.className = '';
        this.dateTime = '';
        this.focused = false;
        this.members = new Set();
        this.classList = {
            toggle: (name, force) => {
                if (force) this.members.add(name);
                else this.members.delete(name);
            },
        };
    }

    get isConnected() {
        return this.connected;
    }

    appendChild(child) {
        child.parentNode = this;
        child.connected = this.connected;
        this.children.push(child);
        return child;
    }

    remove() {
        if (this.parentNode) {
            this.parentNode.children = this.parentNode.children.filter(
                (child) => child !== this,
            );
        }
        this.connected = false;
    }

    addEventListener(name, callback) {
        this.listeners.set(name, callback);
    }

    async dispatch(name, event = {}) {
        const callback = this.listeners.get(name);
        if (!callback) return undefined;
        return callback({ preventDefault() {}, ...event });
    }

    querySelector(selector) {
        if (this.selectors && selector in this.selectors) {
            return this.selectors[selector];
        }
        if (selector.startsWith('.')) {
            const className = selector.slice(1);
            return this.children.find((child) =>
                child.className.split(/\s+/).includes(className),
            ) || null;
        }
        return null;
    }

    focus() {
        this.focused = true;
    }
}

function crearChat({ conChat = true, csrf = true, fetcher = null } = {}) {
    const mensajes = new ElementoFalso();
    const vacio = new ElementoFalso();
    vacio.className = 'learner-group-chat-empty';
    vacio.textContent = 'Cargando conversación…';
    mensajes.appendChild(vacio);
    const estado = new ElementoFalso();
    const formulario = new ElementoFalso();
    const entrada = new ElementoFalso();
    const contador = new ElementoFalso();
    const boton = new ElementoFalso();
    const token = csrf ? new ElementoFalso({ value: 'csrf-prueba' }) : null;

    formulario.selectors = { 'input[name="csrf_token"]': token };
    const selectores = {
        '[data-chat-messages]': mensajes,
        '[data-chat-empty]': vacio,
        '[data-chat-status]': estado,
        '[data-chat-form]': formulario,
        '[data-chat-input]': entrada,
        '[data-chat-count]': contador,
        '[data-chat-submit]': boton,
    };
    const chat = new ElementoFalso();
    chat.dataset.chatUrl = '/aprendiz/7/grupo/mensajes';
    chat.querySelector = (selector) => selectores[selector] || null;

    const calls = [];
    const listeners = new Map();
    const intervalos = [];
    const document = {
        hidden: false,
        querySelectorAll: () => conChat ? [chat] : [],
        createElement: () => new ElementoFalso(),
        addEventListener(name, callback) {
            listeners.set(name, callback);
        },
    };
    const window = {
        location: { href: 'https://panel.example/aprendiz/7/panel' },
        fetch: async (...args) => {
            calls.push(args);
            if (fetcher) return fetcher(...args);
            return { ok: true, json: async () => ({ messages: [] }) };
        },
        setInterval(callback, delay) {
            intervalos.push({ callback, delay });
            return intervalos.length;
        },
    };
    const contexto = vm.createContext({ document, window, URL });
    vm.runInContext(chatSource, contexto, { filename: chatScript });

    return {
        boton,
        calls,
        contador,
        document,
        entrada,
        estado,
        formulario,
        intervalos,
        listeners,
        mensajes,
        token,
        vacio,
        window,
    };
}

function respuesta(datos, ok = true) {
    return { ok, json: async () => datos };
}

async function esperarTareasPendientes() {
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
}

test('carga mensajes incrementales, evita duplicados y envía con CSRF', async () => {
    const respuestas = [
        respuesta({ messages: [
            { id: 8, contenido: '<img src=x onerror=alert(1)>', autor: 'Luz', creado_en: 'fecha-invalida', propio: false },
            { id: 7, contenido: 'Hola', autor: 'Ana', creado_en: '2026-09-28T12:00:00', propio: true },
        ] }),
        respuesta({ messages: [
            { id: 8, contenido: 'mensaje repetido', propio: false },
            { id: 9, contenido: 'Llegó el equipo', autor: 'Luz', creado_en: '2026-09-28T12:01:00', propio: false },
        ] }),
        respuesta({ message: { id: 10, contenido: 'Listo', propio: true, creado_en: null } }),
    ];
    const chat = crearChat({ fetcher: async () => respuestas.shift() });
    await esperarTareasPendientes();

    assert.deepEqual(
        chat.mensajes.children.map((fila) => fila.children[1]?.textContent),
        ['Hola', '<img src=x onerror=alert(1)>'],
    );
    assert.equal(chat.mensajes.children[1].children[1].textContent, '<img src=x onerror=alert(1)>');
    assert.equal(chat.mensajes.children[1].children[0].children[1].textContent, 'fecha-invalida');
    assert.equal(chat.vacio.isConnected, false);
    assert.equal(chat.intervalos[0].delay, 6000);

    await chat.intervalos[0].callback();
    assert.match(chat.calls[1][0], /despues_id=8/);
    assert.deepEqual(
        chat.mensajes.children.map((fila) => fila.children[1]?.textContent),
        ['Hola', '<img src=x onerror=alert(1)>', 'Llegó el equipo'],
    );

    chat.entrada.value = ' Listo ';
    await chat.entrada.dispatch('input');
    assert.equal(chat.contador.textContent, '7');
    await chat.formulario.dispatch('submit');

    const [url, opciones] = chat.calls[2];
    assert.equal(url, '/aprendiz/7/grupo/mensajes');
    assert.equal(opciones.method, 'POST');
    assert.equal(opciones.headers['X-CSRFToken'], 'csrf-prueba');
    assert.deepEqual(JSON.parse(opciones.body), { contenido: 'Listo' });
    assert.equal(chat.entrada.value, '');
    assert.equal(chat.contador.textContent, '0');
    assert.equal(chat.estado.textContent, 'Mensaje enviado.');
    assert.equal(chat.boton.disabled, false);
});

test('conserva el mensaje vacío y muestra errores de lectura o envío', async () => {
    let obtenerRespuesta = async (args) => {
        if (args[1]?.method === 'POST') {
            return respuesta({ error: 'El servicio rechazó el mensaje.' }, false);
        }
        throw new Error('Sin conexión');
    };
    const chat = crearChat({ fetcher: async (...args) => {
        return obtenerRespuesta(args);
    } });
    await esperarTareasPendientes();
    assert.equal(chat.estado.textContent, 'Sin conexión');

    chat.entrada.value = '   ';
    await chat.formulario.dispatch('submit');
    assert.equal(chat.estado.textContent, 'Escribe un mensaje antes de enviarlo.');
    assert.equal(chat.entrada.focused, true);

    chat.entrada.value = 'x'.repeat(1201);
    const llamadasAntes = chat.calls.length;
    await chat.formulario.dispatch('submit');
    assert.equal(chat.calls.length, llamadasAntes);

    chat.entrada.value = 'Mensaje válido';
    await chat.formulario.dispatch('submit');
    assert.equal(chat.estado.textContent, 'El servicio rechazó el mensaje.');
    assert.equal(chat.entrada.value, 'Mensaje válido');
    assert.equal(chat.boton.disabled, false);

    chat.document.hidden = true;
    const llamadasAlOcultar = chat.calls.length;
    await chat.intervalos[0].callback();
    assert.equal(chat.calls.length, llamadasAlOcultar);

    chat.document.hidden = false;
    obtenerRespuesta = async () => respuesta({ messages: [] });
    await chat.listeners.get('visibilitychange')();
    await esperarTareasPendientes();
    assert.equal(chat.vacio.textContent, 'Aún no hay mensajes. Inicia la conversación con tu grupo.');
    assert.equal(chat.estado.textContent, '');
});

test('no inicializa controles ausentes ni chats fuera de la página', async () => {
    const paginaSinChat = crearChat({ conChat: false });
    assert.equal(paginaSinChat.intervalos.length, 0);
    assert.equal(paginaSinChat.calls.length, 0);

    const formularioSinToken = crearChat({ csrf: false });
    await esperarTareasPendientes();
    assert.equal(formularioSinToken.intervalos.length, 0);
    assert.equal(formularioSinToken.calls.length, 0);
});
