const assert = require('node:assert/strict');
const test = require('node:test');
const {
    claveServidorPush,
    crearControlNotificacionesAprendiz,
    iniciarNotificacionesAprendiz,
} = require('../app/static/js/notificaciones_aprendiz.js');

class Elemento {
    constructor() { this.dataset = {}; this.children = []; this.listeners = {}; this.textContent = ''; }
    addEventListener(nombre, callback) { (this.listeners[nombre] ??= []).push(callback); }
    appendChild(elemento) { this.children.push(elemento); elemento.parentElement = this; return elemento; }
    async click() { for (const callback of this.listeners.click || []) await callback({ preventDefault() {} }); }
}

function entorno({ permiso = 'granted', respuestaSuscripcion = true, audioDisponible = true, fallaAudio = false, soportaPush = true, suscripcionExistente = false, fallaRecuperacion = false } = {}) {
    const raiz = new Elemento();
    Object.assign(raiz.dataset, {
        notificationCursor: '0', notificationPollUrl: '/aprendiz/9/notificaciones/nuevas',
        subscriptionUrl: '/aprendiz/9/notificaciones/suscripcion',
        serviceWorkerUrl: '/aprendiz/service-worker.js', vapidPublicKey: 'AQID',
        pushEnabled: 'true', csrfToken: 'csrf-test',
    });
    const live = new Elemento();
    const status = new Elemento();
    const sonido = new Elemento();
    const push = new Elemento();
    const experiencia = new Elemento();
    experiencia.dataset.experienceNotificationMode = 'all';
    const doc = {
        querySelector(selector) { return selector === '[data-aprendiz-notifications]' || selector === '.learner-notifications' ? raiz : null; },
        getElementById(id) { return id === 'panel-aprendiz-root' ? experiencia : null; },
        createElement() { return new Elemento(); },
    };
    const intervalos = [];
    const observadores = [];
    const tonos = [];
    const llamadas = [];
    const suscripcion = {
        endpoint: 'https://updates.push.services.mozilla.com/push/v1/subscription',
        toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'llave', auth: 'secreto' } }; },
        async unsubscribe() { this.retirada = true; return true; },
    };
    const registro = { pushManager: {
        async getSubscription() { return suscripcionExistente ? suscripcion : null; },
        async subscribe() { return suscripcion; },
    } };
    class AudioContext {
        constructor() { this.destination = {}; this.currentTime = 0; }
        async resume() { this.reanudado = true; if (fallaAudio) throw new Error('Audio bloqueado'); }
        createOscillator() {
            const tono = { frequency: {}, connect() {}, start() { tonos.push('inicio'); }, stop() { tonos.push('fin'); } };
            return tono;
        }
        createGain() { return { gain: {}, connect() {} }; }
    }
    class MutationObserver {
        constructor(callback) { this.callback = callback; observadores.push(this); }
        observe() {}
    }
    const win = {
        atob: global.atob,
        fetch: async (url, options = {}) => {
            llamadas.push({ url, options });
            if (options.method === 'POST' || options.method === 'DELETE') return { ok: respuestaSuscripcion };
            const datos = respuestas.shift() || { notificaciones: [] };
            if (datos instanceof Error) throw datos;
            return { ok: true, async json() { return datos; } };
        },
        setInterval(callback, delay) { intervalos.push({ callback, delay }); return intervalos.length; },
        clearInterval(id) { win.intervaloCancelado = id; },
        Notification: { async requestPermission() { return permiso; } },
        navigator: { serviceWorker: {
            async getRegistration() {
                if (fallaRecuperacion) throw new Error('No se pudo consultar el registro.');
                return suscripcionExistente ? registro : null;
            },
            async register() { return registro; },
        } },
        PushManager: soportaPush ? class PushManager {} : undefined,
        AudioContext: audioDisponible ? AudioContext : undefined,
        MutationObserver,
    };
    let respuestas = [];
    return {
        raiz, live, status, sonido, push, experiencia, doc, win, intervalos, observadores,
        tonos, llamadas, suscripcion, registro,
        prepararRespuestas(...valores) { respuestas = valores; },
        obtenerRespuestas() { return respuestas; },
    };
}

test('decodifica una clave VAPID pública a bytes', () => {
    assert.deepEqual(Array.from(claveServidorPush('AQID', { atob: global.atob })), [1, 2, 3]);
});

test('sondea cada quince segundos, deduplica por id y silencia el tono en Lectura tranquila', async () => {
    const e = entorno();
    e.raiz.querySelector = selector => ({
        '[data-notification-live]': e.live,
        '[data-notification-status]': e.status,
        '[data-enable-notification-sound]': e.sonido,
        '[data-toggle-push]': e.push,
    })[selector] || null;
    e.prepararRespuestas({ notificaciones: [
        { id: 1, tipo: 'calificacion', mensaje: 'Tu instructor publicó una calificación.', url: '/aprendiz/9/notificaciones' },
    ] });
    const control = crearControlNotificacionesAprendiz(e.raiz, e.win, e.doc);
    await control.inicio;
    assert.equal(e.intervalos[0].delay, 15000);
    assert.equal(e.live.children.length, 1);
    assert.equal(e.live.children[0].children[0].textContent, 'Tu instructor publicó una calificación.');
    assert.equal(e.live.children[0].children[1].href, '/aprendiz/9/notificaciones');

    await e.sonido.click();
    e.prepararRespuestas({ notificaciones: [
        { id: 2, tipo: 'calificacion', mensaje: 'Nueva nota publicada.', url: '/aprendiz/9/notificaciones' },
    ] });
    await e.intervalos[0].callback();
    assert.equal(e.tonos.length, 2);
    e.experiencia.dataset.experienceNotificationMode = 'quiet';
    e.observadores[0].callback();
    assert.match(e.status.textContent, /silencia el sonido/);
    e.prepararRespuestas({ notificaciones: [
        { id: 2, tipo: 'calificacion', mensaje: 'Duplicada', url: '/aprendiz/9/notificaciones' },
        { id: 3, tipo: 'juicio_evaluativo', mensaje: 'Juicio actualizado', url: '/aprendiz/9/notificaciones' },
    ] });
    await e.intervalos[0].callback();
    assert.equal(e.live.children.length, 3);
    assert.equal(e.tonos.length, 2);
    await e.intervalos[0].callback();
    assert.match(e.llamadas.at(-1).url, /desde_id=3$/);
    control.detener();
    assert.equal(e.win.intervaloCancelado, 1);
});

test('permite activar y retirar Push mediante una acción del aprendiz', async () => {
    const e = entorno();
    e.raiz.querySelector = selector => ({
        '[data-notification-live]': e.live,
        '[data-notification-status]': e.status,
        '[data-enable-notification-sound]': e.sonido,
        '[data-toggle-push]': e.push,
    })[selector] || null;
    e.prepararRespuestas({ notificaciones: [] });
    const control = crearControlNotificacionesAprendiz(e.raiz, e.win, e.doc);
    await e.push.click();
    assert.equal(e.push.textContent, 'Desactivar avisos del navegador');
    const alta = e.llamadas.find(llamada => llamada.options.method === 'POST');
    assert.equal(alta.options.headers['X-CSRFToken'], 'csrf-test');
    assert.equal(JSON.parse(alta.options.body).endpoint, e.suscripcion.endpoint);
    await e.push.click();
    assert.equal(e.suscripcion.retirada, true);
    assert.equal(e.push.textContent, 'Activar avisos del navegador');
    const baja = e.llamadas.find(llamada => llamada.options.method === 'DELETE');
    assert.equal(JSON.parse(baja.options.body).endpoint, e.suscripcion.endpoint);

    const fallo = entorno();
    fallo.raiz.querySelector = selector => selector === '[data-notification-status]' ? fallo.status : null;
    fallo.prepararRespuestas({ notificaciones: [] });
    const controlConFallo = crearControlNotificacionesAprendiz(fallo.raiz, fallo.win, fallo.doc);
    await controlConFallo.actualizarSuscripcion();
    fallo.suscripcion.unsubscribe = async () => { throw new Error('No se pudo retirar'); };
    assert.equal(await controlConFallo.retirarSuscripcion(), false);
    assert.match(fallo.status.textContent, /No fue posible desactivar/);
});

test('recupera la suscripción existente después de recargar el panel', async () => {
    const e = entorno({ suscripcionExistente: true });
    e.raiz.querySelector = selector => ({
        '[data-notification-live]': e.live,
        '[data-notification-status]': e.status,
        '[data-enable-notification-sound]': e.sonido,
        '[data-toggle-push]': e.push,
    })[selector] || null;
    e.prepararRespuestas({ notificaciones: [] });
    const control = crearControlNotificacionesAprendiz(e.raiz, e.win, e.doc);
    await control.inicio;

    assert.equal(e.push.textContent, 'Desactivar avisos del navegador');
    await e.push.click();
    const baja = e.llamadas.find(llamada => llamada.options.method === 'DELETE');
    assert.equal(JSON.parse(baja.options.body).endpoint, e.suscripcion.endpoint);
    assert.equal(e.suscripcion.retirada, true);
});

test('informa el fallo al recuperar la suscripción y conserva los avisos de texto', async () => {
    const e = entorno({ fallaRecuperacion: true });
    e.raiz.querySelector = selector => ({
        '[data-notification-live]': e.live,
        '[data-notification-status]': e.status,
        '[data-enable-notification-sound]': e.sonido,
        '[data-toggle-push]': e.push,
    })[selector] || null;
    e.prepararRespuestas({ notificaciones: [] });
    const control = crearControlNotificacionesAprendiz(e.raiz, e.win, e.doc);
    await control.inicio;

    assert.match(e.status.textContent, /No se pudo comprobar/);
    assert.equal(e.intervalos.length, 1);
});

test('conserva los avisos de texto si faltan permisos, audio o soporte del navegador', async () => {
    const denegado = entorno({ permiso: 'denied' });
    denegado.raiz.querySelector = selector => selector === '[data-notification-status]' ? denegado.status : null;
    const control = crearControlNotificacionesAprendiz(denegado.raiz, denegado.win, denegado.doc);
    assert.equal(await control.actualizarSuscripcion(), false);
    assert.match(denegado.status.textContent, /permiso está desactivado/);

    const sinSoporte = entorno({ soportaPush: false, audioDisponible: false });
    sinSoporte.raiz.querySelector = selector => selector === '[data-notification-status]' ? sinSoporte.status : null;
    const controlSinSoporte = crearControlNotificacionesAprendiz(sinSoporte.raiz, sinSoporte.win, sinSoporte.doc);
    assert.equal(await controlSinSoporte.actualizarSuscripcion(), false);
    assert.equal(await controlSinSoporte.activarSonido(), false);
    assert.match(sinSoporte.status.textContent, /no admite sonido/);
});

test('muestra avisos en texto aunque falle la consulta o el registro Push', async () => {
    const e = entorno({ respuestaSuscripcion: false });
    e.raiz.querySelector = selector => ({
        '[data-notification-live]': e.live,
        '[data-notification-status]': e.status,
    })[selector] || null;
    e.prepararRespuestas(new Error('sin conexión'));
    const control = crearControlNotificacionesAprendiz(e.raiz, e.win, e.doc);
    await control.consultarNuevas();
    assert.match(e.status.textContent, /volverán a consultar/);
    assert.equal(await control.actualizarSuscripcion(), false);
    assert.match(e.status.textContent, /seguir consultándolos en el panel/);
    assert.equal(iniciarNotificacionesAprendiz({ querySelector() { return null; } }, e.win), null);

    const audioBloqueado = entorno({ fallaAudio: true });
    audioBloqueado.raiz.querySelector = selector => selector === '[data-notification-status]' ? audioBloqueado.status : null;
    const controlAudioBloqueado = crearControlNotificacionesAprendiz(audioBloqueado.raiz, audioBloqueado.win, audioBloqueado.doc);
    assert.equal(await controlAudioBloqueado.activarSonido(), false);
    assert.match(audioBloqueado.status.textContent, /no permitió activar el sonido/);
});

test('inicializa el control cuando se carga el panel del aprendiz', () => {
    const e = entorno();
    e.raiz.querySelector = () => null;
    e.prepararRespuestas({ notificaciones: [] });
    let inicializador;
    const doc = {
        querySelector() { return e.raiz; },
        getElementById() { return null; },
        createElement() { return new Elemento(); },
        addEventListener(nombre, callback) { if (nombre === 'DOMContentLoaded') inicializador = callback; },
    };
    const modulo = require.resolve('../app/static/js/notificaciones_aprendiz.js');
    const documentoAnterior = global.document;
    const ventanaAnterior = global.window;
    global.document = doc;
    global.window = e.win;
    delete require.cache[modulo];
    require(modulo);
    assert.equal(typeof inicializador, 'function');
    inicializador();
    assert.equal(e.intervalos[0].delay, 15000);
    delete require.cache[modulo];
    if (documentoAnterior === undefined) delete global.document; else global.document = documentoAnterior;
    if (ventanaAnterior === undefined) delete global.window; else global.window = ventanaAnterior;
});

test('service worker mantiene el aviso genérico y abre solo la ruta de notificaciones', async () => {
    const eventos = {};
    const mostradas = [];
    const llamadas = [];
    const existente = {
        url: 'https://panel.example/aprendiz/9/panel',
        async navigate(url) { llamadas.push(['navigate', url]); },
        async focus() { llamadas.push(['focus']); },
    };
    const self = {
        location: { origin: 'https://panel.example' },
        registration: { async showNotification(titulo, opciones) { mostradas.push({ titulo, opciones }); } },
        clients: {
            visibles: [],
            async matchAll() { return this.visibles; },
            async openWindow(url) { llamadas.push(['open', url]); },
        },
        addEventListener(nombre, callback) { eventos[nombre] = callback; },
    };
    const rutaWorker = require.resolve('../app/static/js/aprendiz-service-worker.js');
    const selfAnterior = global.self;
    global.self = self;
    delete require.cache[rutaWorker];
    require(rutaWorker);

    const pushVisible = { waitUntil(promesa) { this.promesa = promesa; }, data: { json: () => ({ url: '/aprendiz/9/notificaciones' }) } };
    self.clients.visibles = [{ visibilityState: 'visible' }];
    await eventos.push(pushVisible);
    await pushVisible.promesa;
    assert.equal(mostradas.length, 0);

    self.clients.visibles = [];
    const pushOculto = { waitUntil(promesa) { this.promesa = promesa; }, data: { json: () => ({ url: 'https://attacker.example/?documento=secreto', silent: true, body: 'nota 5.0' }) } };
    await eventos.push(pushOculto);
    await pushOculto.promesa;
    assert.equal(mostradas[0].titulo, 'Resultados formativos actualizados');
    assert.equal(mostradas[0].opciones.body, 'Entra al panel para consultar la información.');
    assert.equal(mostradas[0].opciones.silent, true);
    assert.equal(mostradas[0].opciones.data.ruta, '/aprendiz/');
    assert.doesNotMatch(JSON.stringify(mostradas[0]), /secreto|5\.0/);

    const notificacion = { data: { ruta: '/aprendiz/9/notificaciones' }, close() { llamadas.push(['close']); } };
    self.clients.visibles = [existente];
    const clic = { notification: notificacion, waitUntil(promesa) { this.promesa = promesa; } };
    await eventos.notificationclick(clic);
    await clic.promesa;
    assert.deepEqual(llamadas.map(llamada => llamada[0]), ['close', 'navigate', 'focus']);
    const clienteInstructor = {
        url: 'https://panel.example/instructor/entregas',
        async navigate(url) { llamadas.push(['navegar-instructor', url]); },
        async focus() { llamadas.push(['enfocar-instructor']); },
    };
    self.clients.visibles = [clienteInstructor];
    const clicConInstructorAbierto = { notification: notificacion, waitUntil(promesa) { this.promesa = promesa; } };
    await eventos.notificationclick(clicConInstructorAbierto);
    await clicConInstructorAbierto.promesa;
    assert.deepEqual(llamadas.slice(-2), [
        ['close'],
        ['open', 'https://panel.example/aprendiz/9/notificaciones'],
    ]);
    self.clients.visibles = [];
    const clicSinCliente = { notification: { data: {}, close() {} }, waitUntil(promesa) { this.promesa = promesa; } };
    await eventos.notificationclick(clicSinCliente);
    await clicSinCliente.promesa;
    assert.deepEqual(llamadas.at(-1), ['open', 'https://panel.example/aprendiz/']);
    delete require.cache[rutaWorker];
    if (selfAnterior === undefined) delete global.self; else global.self = selfAnterior;
});
