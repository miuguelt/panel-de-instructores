const test = require('node:test');
const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const { crearMotor } = require('../app/static/js/uploads_reanudables.js');

class Elemento {
    constructor() { this.children = []; this.style = {}; this.listeners = {}; this.attributes = {}; }
    appendChild(child) { this.children.push(child); return child; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, listener) { this.listeners[name] = listener; }
    click() { return this.listeners.click?.(); }
}

function entorno(opciones = {}) {
    const registro = opciones.registro || new Map();
    const llamadas = [];
    const sesiones = opciones.sesiones || new Map();
    let contador = 0;
    let confirmar = 0;
    const estado = { fallos: opciones.fallos || 0, romperRespuesta: opciones.romperRespuesta || false };
    const listeners = {};
    const window = {
        crypto: webcrypto, URL, FormData, AbortController,
        location: { href: 'http://localhost/formulario', origin: 'http://localhost' },
        navigator: { onLine: true },
        localStorage: { getItem: key => registro.get(key) || null, setItem: (key, value) => registro.set(key, value), removeItem: key => registro.delete(key) },
        addEventListener: (key, fn) => { listeners[key] = fn; },
        removeEventListener: key => { delete listeners[key]; },
        setTimeout: (fn, ms) => ms < 120000 ? setTimeout(fn, 1) : setTimeout(fn, ms).unref(), clearTimeout,
        fetch: async (url, init = {}) => {
            llamadas.push({ url, ...init });
            if (opciones.interceptar) {
                const respuesta = await opciones.interceptar(url, init, sesiones);
                if (respuesta) return respuesta;
            }
            const id = String(url).split('/').pop();
            const method = init.method || 'GET';
            if (url === '/cargas' && method === 'POST') {
                const entrada = JSON.parse(init.body);
                const carga = { ok: true, id: String(++contador), estado: 'subiendo', offset: 0, tamano: entrada.tamano, chunk_bytes: 4, huellas: [], vence_en: new Date(Date.now() + 86400000).toISOString() };
                sesiones.set(carga.id, carga);
                return respuesta(201, carga);
            }
            if (String(url).startsWith('/cargas/')) {
                const carga = sesiones.get(id);
                if (!carga) return respuesta(404, { message: 'No existe.' });
                if (method === 'DELETE') { sesiones.delete(id); return respuesta(200, { ok: true }); }
                if (method === 'PATCH') {
                    if (estado.fallos-- > 0) return respuesta(503, { message: 'Servicio ocupado.' }, { 'Retry-After': '0' });
                    assert.equal(Number(init.headers['Upload-Offset']), carga.offset);
                    const hash = Buffer.from(await webcrypto.subtle.digest('SHA-256', await init.body.arrayBuffer())).toString('hex');
                    assert.equal(init.headers['X-Chunk-SHA256'], hash);
                    carga.huellas.push(hash); carga.offset += init.body.size;
                    if (carga.offset === carga.tamano) carga.estado = 'recibido';
                    if (estado.romperRespuesta) { estado.romperRespuesta = false; throw Error('Respuesta perdida'); }
                }
                return respuesta(200, { ...carga });
            }
            confirmar++;
            return respuesta(200, opciones.confirmacion || { ok: true, redirect: '/confirmado' });
        },
    };
    const document = { createElement: () => new Elemento(), querySelector: () => ({ content: 'csrf-de-prueba' }) };
    const ui = { panel: new Elemento(), texto: new Elemento(), relleno: new Elemento() };
    const form = { action: '/guardar', method: 'POST' };
    const datos = new FormData(); datos.append('descripcion', 'Mi evidencia'); datos.append('archivo', new Blob(['abcdefghij']), 'prueba.zip');
    const archivo = new Blob(['abcdefghij'], { type: 'application/zip' }); archivo.name = 'prueba.zip'; archivo.lastModified = 123;
    const seleccion = [{ archivo, input: { name: 'archivo' } }];
    const errores = [];
    const motor = crearMotor(window, document);
    const iniciar = () => motor.iniciar(form, datos, seleccion, ui, { fallar: (...args) => errores.push(args) }, { url: '/cargas', chunkBytes: 4 });
    return { window, document, ui, form, datos, seleccion, errores, llamadas, sesiones, registro, iniciar, motor, confirmar: () => confirmar, listeners };
}

function respuesta(status, body, headers = {}) {
    return { status, ok: status >= 200 && status < 300, redirected: false, headers: { get: key => headers[key] || null }, json: async () => structuredClone(body) };
}

async function hasta(condicion) {
    for (let i = 0; i < 100; i++) {
        if (condicion()) return;
        await new Promise(resolve => setTimeout(resolve, 2));
    }
    throw Error('La condición no se cumplió.');
}

test('sube bloques verificados y confirma los campos originales sin volver a enviar el archivo', async () => {
    const e = entorno(); await e.iniciar();
    const bloques = e.llamadas.filter(c => c.method === 'PATCH');
    assert.deepEqual(bloques.map(c => c.body.size), [4, 4, 2]);
    const final = e.llamadas.find(c => c.url === '/guardar');
    assert.equal(final.body.has('archivo'), false);
    assert.equal(final.body.get('descripcion'), 'Mi evidencia');
    assert.deepEqual(JSON.parse(final.body.get('_cargas')), { archivo: '1' });
    assert.match(final.body.get('_carga_envio'), /^[a-f0-9-]+$/);
    assert.equal(final.headers['X-CSRFToken'], 'csrf-de-prueba');
    assert.equal(e.window.location.href, '/confirmado');
    assert.equal(e.registro.size, 0);
});

test('una respuesta perdida consulta el avance y no retransmite el bloque confirmado', async () => {
    const e = entorno({ romperRespuesta: true }); await e.iniciar();
    assert.equal(e.llamadas.filter(c => c.method === 'PATCH').length, 3);
    assert.ok(e.llamadas.some(c => c.url === '/cargas/1' && !c.method));
    assert.equal(e.confirmar(), 1);
});

test('reintenta indisponibilidad temporal y mantiene el progreso confirmado', async () => {
    const e = entorno({ fallos: 2 }); await e.iniciar();
    assert.equal(e.llamadas.filter(c => c.method === 'PATCH').length, 5);
    assert.equal(e.errores.length, 0);
    assert.equal(e.window.location.href, '/confirmado');
});

test('un rechazo definitivo informa el mensaje y conserva la referencia para corregir', async () => {
    const e = entorno({ interceptar: async (url, init) => init.method === 'PATCH' ? respuesta(403, { message: 'La actividad ya no acepta archivos.' }) : null });
    await e.iniciar();
    assert.equal(e.errores[0][0], 'La actividad ya no acepta archivos.');
    assert.equal(e.confirmar(), 0);
    assert.equal(e.registro.size, 1);
});

test('reanuda tras recargar verificando los bloques del mismo archivo', async () => {
    const e = entorno({ interceptar: async (url, init, sesiones) => init.method === 'PATCH' && sesiones.get('1')?.offset === 4 ? respuesta(403, { message: 'Pausa de prueba' }) : null });
    await e.iniciar();
    assert.equal(e.sesiones.get('1').offset, 4);
    const siguiente = entorno({ registro: e.registro, sesiones: e.sesiones });
    await siguiente.iniciar();
    assert.deepEqual(siguiente.llamadas.filter(c => c.method === 'PATCH').map(c => Number(c.headers['Upload-Offset'])), [4, 8]);
    assert.equal(siguiente.window.location.href, '/confirmado');
});

test('rechaza una reselección cuyo contenido no coincide con el bloque guardado', async () => {
    const e = entorno({ interceptar: async (url, init, sesiones) => init.method === 'PATCH' && sesiones.get('1')?.offset === 4 ? respuesta(403, { message: 'Pausa de prueba' }) : null });
    await e.iniciar();
    const siguiente = entorno({ registro: e.registro, sesiones: e.sesiones });
    const archivo = new Blob(['XXXXXXXXXX']); archivo.name = 'prueba.zip'; archivo.lastModified = 123;
    siguiente.seleccion[0].archivo = archivo;
    await siguiente.iniciar();
    assert.match(siguiente.errores[0][0], /no coincide/);
    assert.equal(siguiente.llamadas.filter(c => c.method === 'PATCH').length, 0);
});

test('pausa dos transferencias activas y las continúa sin dejar una espera bloqueada', async () => {
    let pendientes = 0;
    const e = entorno({ interceptar: async (url, init) => {
        if (init.method === 'PATCH' && pendientes < 2) {
            pendientes++;
            return new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(Error('Abortada'))));
        }
    } });
    const segundo = new Blob(['segundo']); segundo.name = 'otro.zip';
    e.seleccion.push({ archivo: segundo, input: { name: 'archivo2' } });
    const carga = e.iniciar();
    await hasta(() => pendientes === 2);
    await e.ui.panel.children[0].click();
    await hasta(() => e.ui.panel.children[0].textContent === 'Continuar');
    assert.match(e.ui.texto.textContent, /pausada/);
    await e.ui.panel.children[0].click();
    await carga;
    assert.equal(e.errores.length, 0);
    assert.equal(e.confirmar(), 1);
    assert.deepEqual(Object.keys(JSON.parse(e.llamadas.at(-1).body.get('_cargas'))).sort(), ['archivo', 'archivo2']);
});

test('cancela transferencias y elimina las sesiones incompletas', async () => {
    let pendiente = false;
    const e = entorno({ interceptar: async (url, init) => {
        if (init.method === 'PATCH') {
            pendiente = true;
            return new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(Error('Abortada'))));
        }
    } });
    const carga = e.iniciar(); await hasta(() => pendiente);
    await e.ui.panel.children[1].click(); await carga;
    assert.equal(e.sesiones.size, 0);
    assert.equal(e.registro.size, 0);
    assert.match(e.errores[0][0], /canceló/);
    assert.equal(e.confirmar(), 0);
});

test('espera la conexión y solo continúa después del evento de reconexión', async () => {
    const e = entorno(); e.window.navigator.onLine = false;
    const carga = e.iniciar();
    await hasta(() => e.ui.texto.textContent?.includes('conexión'));
    e.listeners.online();
    assert.equal(e.llamadas.length, 0);
    e.window.navigator.onLine = true; e.listeners.online();
    await carga;
    assert.equal(e.window.location.href, '/confirmado');
    assert.equal(Object.keys(e.listeners).length, 0);
});

test('después de cinco reintentos ofrece continuar y conserva la misma sesión', async () => {
    const e = entorno({ fallos: 6 });
    const carga = e.iniciar();
    await hasta(() => e.ui.panel.children[0].textContent === 'Continuar');
    assert.equal(e.registro.size, 1);
    assert.match(e.ui.texto.textContent, /avance se conserva/);
    e.ui.panel.children[0].click(); await carga;
    assert.equal(e.sesiones.size, 1);
    assert.equal(e.confirmar(), 1);
});

test('informa las etapas del procesamiento y espera su confirmación', async () => {
    const observados = [];
    let consultas = 0;
    const e = entorno({ confirmacion: { ok: true, status_url: '/estado', redirect: '/listo' }, interceptar: async url => {
        if (url === '/estado') {
            observados.push(e.ui.texto.textContent);
            return respuesta(200, { ok: true, estado: ['encolado', 'procesando', 'completado'][consultas++] });
        }
    } });
    await e.iniciar();
    assert.equal(consultas, 3);
    assert.match(observados[0], /Guardado/);
    assert.match(observados[2], /Procesando/);
    assert.equal(e.window.location.href, '/listo');
});

test('un error posterior al guardado no anuncia éxito ni elimina la referencia', async () => {
    const e = entorno({ confirmacion: { ok: true, status_url: '/estado' }, interceptar: async url => url === '/estado' ? respuesta(200, { ok: true, estado: 'error', message: 'Archivo guardado; revise el formato del reporte.' }) : null });
    await e.iniciar();
    assert.match(e.errores[0][0], /Archivo guardado/);
    assert.equal(e.window.location.href, 'http://localhost/formulario');
    assert.equal(e.registro.size, 1);
});

test('la sesión vencida ofrece ingresar de nuevo sin reintentos de subida', async () => {
    const e = entorno({ interceptar: async (url, init) => init.method === 'PATCH' ? respuesta(401, {}) : null });
    await e.iniciar();
    assert.match(e.errores[0][0], /sesión terminó/);
    assert.equal(e.errores[0][1], true);
    assert.equal(e.llamadas.filter(c => c.method === 'PATCH').length, 1);
});

test('se recupera de un JSON incompleto y de un bloqueo del almacenamiento local', async () => {
    let fallo = true;
    const e = entorno({ interceptar: async (url, init) => {
        if (init.method === 'PATCH' && fallo) {
            fallo = false;
            return { ...respuesta(200, {}), json: async () => { throw Error('JSON incompleto'); } };
        }
    } });
    e.window.localStorage.getItem = () => { throw Error('Almacenamiento bloqueado'); };
    e.window.localStorage.setItem = e.window.localStorage.removeItem = () => { throw Error('Almacenamiento bloqueado'); };
    e.document.querySelector = () => null;
    await e.iniciar();
    assert.equal(e.window.location.href, '/confirmado');
    assert.equal(e.llamadas[0].headers['X-CSRFToken'], '');
});

test('descarta una referencia vencida y empieza otra sesión', async () => {
    const e = entorno({ interceptar: async (url, init, sesiones) => init.method === 'PATCH' && sesiones.get('1')?.offset === 4 ? respuesta(403, { message: 'Pausa de prueba' }) : null });
    await e.iniciar(); e.sesiones.clear();
    const siguiente = entorno({ registro: e.registro, sesiones: e.sesiones });
    await siguiente.iniciar();
    assert.equal(siguiente.llamadas.filter(c => c.url === '/cargas' && c.method === 'POST').length, 1);
    assert.equal(siguiente.window.location.href, '/confirmado');
});

test('el límite de espera aborta una solicitud detenida y recupera su avance', async () => {
    let pendiente = false;
    const limites = [];
    const e = entorno({ interceptar: async (url, init) => {
        if (init.method === 'PATCH' && !pendiente) {
            pendiente = true;
            return new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(Error('Tiempo agotado'))));
        }
    } });
    const temporizador = e.window.setTimeout;
    e.window.setTimeout = (fn, ms) => { if (ms === 120000) limites.push(fn); return temporizador(fn, ms); };
    const carga = e.iniciar(); await hasta(() => pendiente);
    limites.at(-1)(); await carga;
    assert.equal(e.window.location.href, '/confirmado');
    assert.equal(e.llamadas.filter(c => c.method === 'PATCH').length, 4);
});

test('al regresar al formulario informa cómo continuar una carga pendiente', () => {
    const e = entorno();
    const form = new Elemento(); form.action = '/guardar';
    form.querySelector = () => form.children.find(c => c.className === 'upload-resume-notice');
    e.document.querySelectorAll = () => [form, { action: '/otra', querySelector: () => null }];
    e.registro.set('adso:cargas:v1:/guardar', JSON.stringify({ archivos: { archivo: '1' } }));
    e.motor.restaurar(); e.motor.restaurar();
    assert.equal(form.children.length, 1);
    assert.match(form.children[0].textContent, /archivo original/);
    assert.equal(form.children[0].attributes.role, 'status');
});

test('reintenta el procesamiento por su acción específica sin retransmitir bytes', async () => {
    let reintentado = false;
    const e = entorno({ confirmacion: { ok: true, status_url: '/estado' }, interceptar: async (url, init) => {
        if (url === '/estado') return respuesta(200, { ok: true, estado: reintentado ? 'completado' : 'error', resultado: { ok: reintentado, message: 'El archivo quedó guardado; el proceso no pudo terminar.', retry_url: '/reintentar', redirect: '/listo' } });
        if (url === '/reintentar') { assert.equal(init.method, 'POST'); reintentado = true; return respuesta(200, { ok: true, estado: 'encolado' }); }
    } });
    const carga = e.iniciar();
    await hasta(() => e.ui.panel.children[0].textContent === 'Reintentar procesamiento');
    assert.match(e.ui.texto.textContent, /quedó guardado/);
    e.ui.panel.children[0].click(); await carga;
    assert.equal(e.window.location.href, '/listo');
    assert.equal(e.llamadas.filter(c => c.method === 'PATCH').length, 3);
});

test('la recuperación de sesión usa tú para el aprendiz', async () => {
    const e = entorno({ interceptar: async (url, init) => init.method === 'PATCH' ? respuesta(401, {}) : null });
    e.form.action = '/aprendiz/1/subir-evidencia/1';
    await e.iniciar();
    assert.match(e.errores[0][0], /^Tu sesión terminó\. Ingresa nuevamente/);
});

test('la falta de espacio y un conflicto de confirmación no repiten la transferencia', async () => {
    for (const [status, body] of [[507, { message: 'No hay espacio disponible.' }], [409, { code: 'archivo_registrado', message: 'El archivo ya quedó registrado.' }]]) {
        const e = entorno({ interceptar: async (url, init) => init.method === 'PATCH' ? respuesta(status, body) : null });
        await e.iniciar();
        assert.equal(e.llamadas.filter(c => c.method === 'PATCH').length, 1);
        assert.equal(e.errores[0][0], body.message);
        assert.equal(e.registro.size, 1);
    }
});

test('repite el inicio con la misma clave después de perder su respuesta y crea una sola sesión', async () => {
    const inicios = new Map();
    let intentos = 0;
    const e = entorno({ interceptar: async (url, init, sesiones) => {
        if (url !== '/cargas' || init.method !== 'POST') return;
        const clave = init.headers['Idempotency-Key'] || webcrypto.randomUUID();
        if (!inicios.has(clave)) {
            const carga = { ok: true, id: String(inicios.size + 1), estado: 'subiendo', tamano: 10, offset: 0, chunk_bytes: 4, huellas: [] };
            inicios.set(clave, carga); sesiones.set(carga.id, carga);
        }
        if (++intentos === 1) throw Error('La respuesta de inicio se perdió');
        return respuesta(201, inicios.get(clave));
    } });
    await e.iniciar();
    assert.equal(inicios.size, 1);
    const solicitudes = e.llamadas.filter(c => c.url === '/cargas' && c.method === 'POST');
    assert.equal(solicitudes.length, 2);
    assert.match(solicitudes[0].headers['Idempotency-Key'], /^[a-f0-9-]{36}$/);
    assert.equal(solicitudes[0].headers['Idempotency-Key'], solicitudes[1].headers['Idempotency-Key']);
    assert.equal(e.confirmar(), 1);
});

test('al vencer una sesión cambia su clave de inicio y conserva la clave de confirmación', async () => {
    const e = entorno({ interceptar: async (url, init, sesiones) => init.method === 'PATCH' && sesiones.get('1')?.offset === 4 ? respuesta(403, { message: 'Pausa de prueba' }) : null });
    await e.iniciar();
    const anterior = JSON.parse(e.registro.get('adso:cargas:v1:/guardar'));
    const primerInicio = e.llamadas.find(c => c.url === '/cargas' && c.method === 'POST').headers['Idempotency-Key'];
    const siguiente = entorno({ registro: e.registro, sesiones: e.sesiones, interceptar: async (url, init) => url === '/cargas/1' && !init.method ? respuesta(410, { message: 'La carga venció.' }) : null });
    await siguiente.iniciar();
    const nuevoInicio = siguiente.llamadas.find(c => c.url === '/cargas' && c.method === 'POST').headers['Idempotency-Key'];
    assert.equal(typeof primerInicio, 'string');
    assert.notEqual(nuevoInicio, primerInicio);
    assert.equal(siguiente.llamadas.at(-1).body.get('_carga_envio'), anterior.envio);
    assert.equal(siguiente.confirmar(), 1);
});

test('un bloqueo temporal del inicio respeta Retry-After y vuelve a intentar con la misma clave', async () => {
    let intentos = 0;
    const demoras = [];
    const e = entorno({ interceptar: async (url, init) => {
        if (url === '/cargas' && init.method === 'POST' && ++intentos === 1) return respuesta(409, { code: 'carga_ocupada', message: 'La reserva está ocupada.' }, { 'Retry-After': '2' });
    } });
    const temporizador = e.window.setTimeout;
    e.window.setTimeout = (fn, ms) => { demoras.push(ms); return temporizador(fn, ms); };
    await e.iniciar();
    assert.equal(e.window.location.href, '/confirmado');
    assert.equal(intentos, 2);
    assert.ok(demoras.some(ms => ms === 2000));
    const solicitudes = e.llamadas.filter(c => c.url === '/cargas' && c.method === 'POST');
    assert.equal(solicitudes[0].headers['Idempotency-Key'], solicitudes[1].headers['Idempotency-Key']);
});

test('un CSRF vencido y una respuesta reload ofrecen recargar el formulario', async () => {
    for (const cuerpo of [{ code: 'csrf_vencido', message: 'El formulario venció.' }, { reload: true, message: 'Recargue el formulario.' }]) {
        const e = entorno({ interceptar: async (url, init) => init.method === 'PATCH' ? respuesta(400, cuerpo) : null });
        await e.iniciar();
        assert.equal(e.errores[0][0], cuerpo.message);
        assert.equal(e.errores[0][1], true);
        assert.equal(e.registro.size, 1);
    }
});
