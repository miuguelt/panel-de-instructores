const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
let proceso, navegador, contexto, origen, temporal;
let salida = '';

test.before(async () => {
    temporal = fs.mkdtempSync(path.join(os.tmpdir(), 'adso-cargas-servidor-'));
    const local = path.join(raiz, 'venv_win', 'Scripts', 'python.exe');
    const python = process.env.PYTHON || (fs.existsSync(local) ? local : process.platform === 'win32' ? 'python' : 'python3');
    proceso = spawn(python, ['-m', 'tests.servidor_cargas_e2e', temporal], {
        cwd: raiz, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    origen = await new Promise((resolve, reject) => {
        const limite = setTimeout(() => reject(new Error('El servidor de pruebas no inició.\n' + salida)), 25000);
        proceso.once('error', error => { clearTimeout(limite); reject(error); });
        proceso.once('exit', codigo => { clearTimeout(limite); reject(new Error(`El servidor terminó (${codigo}).\n${salida}`)); });
        proceso.stderr.on('data', datos => { salida += datos.toString(); });
        proceso.stdout.on('data', datos => {
            salida += datos.toString();
            const coincidencia = salida.match(/URL=(http:\/\/127\.0\.0\.1:\d+)/);
            if (coincidencia) { clearTimeout(limite); resolve(coincidencia[1]); }
        });
    });
    navegador = await chromium.launch({ headless: true });
    contexto = await navegador.newContext();
});

test.after(async () => {
    if (contexto && origen) await contexto.request.post(origen + '/__pruebas__/detener').catch(() => {});
    await navegador?.close();
    if (proceso && proceso.exitCode === null) {
        await new Promise(resolve => {
            const limite = setTimeout(() => { proceso.kill(); resolve(); }, 5000);
            proceso.once('exit', () => { clearTimeout(limite); resolve(); });
        });
    }
    if (temporal) {
        const destino = path.resolve(temporal);
        assert.equal(path.dirname(destino), path.resolve(os.tmpdir()));
        assert.ok(path.basename(destino).startsWith('adso-cargas-servidor-'));
        fs.rmSync(destino, { recursive: true, force: true });
    }
});

async function pagina(formulario) {
    const page = await contexto.newPage();
    await page.route('**/*', route => new URL(route.request().url()).origin === origen ? route.continue() : route.abort());
    await page.goto(origen + '/__pruebas__/ingresar?formulario=' + formulario);
    return page;
}

async function estado() {
    const respuesta = await contexto.request.get(origen + '/__pruebas__/estado');
    assert.equal(respuesta.status(), 200);
    return respuesta.json();
}

async function esperarEstado(predicado) {
    const inicio = Date.now();
    while (Date.now() - inicio < 15000) {
        const actual = await estado();
        if (predicado(actual)) return actual;
        await new Promise(resolve => setTimeout(resolve, 75));
    }
    throw new Error('El estado esperado no se confirmó.\n' + JSON.stringify(await estado()) + '\n' + salida);
}

test('Flask rechaza una creación sin CSRF antes de reservar espacio', async () => {
    const page = await pagina('material');
    const respuesta = await contexto.request.post(origen + '/cargas', { data: {
        destino: '/instructor/fichas/1/materiales', campo: 'archivo', nombre: 'guia.pdf', tamano: 42,
    } });
    assert.equal(respuesta.status(), 400);
    assert.equal((await estado()).cargas.length, 0);
    await page.close();
});

test('el recorrido real recupera respuestas perdidas y conserva una sola copia registrada', async () => {
    const page = await pagina('material');
    const bytes = Buffer.concat([Buffer.from('%PDF-1.4\n'), Buffer.alloc(2800, 65), Buffer.from('\n%%EOF')]);
    let bloquePerdido = false, confirmacionPerdida = false;
    const posiciones = [];
    await page.route('**/cargas/*', async route => {
        if (route.request().method() === 'PATCH') {
            posiciones.push(Number(route.request().headers()['upload-offset']));
            if (!bloquePerdido) {
                bloquePerdido = true;
                assert.equal((await route.fetch()).status(), 200);
                await route.abort('failed');
                return;
            }
        }
        await route.continue();
    });
    await page.route('**/instructor/fichas/1/materiales', async route => {
        if (route.request().method() === 'POST' && !confirmacionPerdida) {
            confirmacionPerdida = true;
            assert.equal((await route.fetch()).status(), 200);
            await route.abort('failed');
            return;
        }
        await route.continue();
    });
    await page.locator('input[type=file]').setInputFiles({ name: 'guia.pdf', mimeType: 'application/pdf', buffer: bytes });
    await page.getByRole('button', { name: 'Guardar material', exact: true }).click();
    const final = await esperarEstado(dato => dato.materiales.length === 1 && dato.envios.length === 1 && confirmacionPerdida);
    await page.waitForURL(origen + '/instructor/fichas/1/materiales', { timeout: 15000 });
    assert.equal(bloquePerdido, true);
    assert.equal(confirmacionPerdida, true);
    assert.deepEqual(posiciones, [0, 1024, 2048], 'El bloque confirmado no se vuelve a transferir.');
    assert.equal(final.materiales[0].descripcion, 'Guía revisada del grupo');
    const descarga = await contexto.request.get(origen + final.materiales[0].descarga);
    assert.equal(descarga.status(), 200);
    assert.equal(createHash('sha256').update(await descarga.body()).digest('hex'), createHash('sha256').update(bytes).digest('hex'));
    assert.equal((await estado()).materiales.length, 1);
    await page.close();
});

test('la planeación recibida queda en cola y el worker real la incorpora sin otra transferencia', async () => {
    const page = await pagina('planeacion');
    const archivo = await contexto.request.get(origen + '/__pruebas__/planeacion.xlsx');
    assert.equal(archivo.status(), 200);
    const bytes = await archivo.body();
    const peticiones = [];
    page.on('request', solicitud => { if (solicitud.method() === 'PATCH') peticiones.push(solicitud.url()); });
    await page.locator('input[type=file]').setInputFiles({ name: 'planeacion.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: bytes });
    await page.getByRole('button', { name: 'Guardar planeación', exact: true }).click();
    const pendiente = await esperarEstado(dato => dato.envios.some(envio => envio.estado === 'encolado'));
    const trabajo = pendiente.envios.find(envio => envio.estado === 'encolado');
    assert.equal(pendiente.versiones.length, 0, 'La respuesta de recepción no anticipa el procesamiento.');
    const token = await page.locator('meta[name=csrf-token]').getAttribute('content');
    const respuesta = await contexto.request.post(origen + '/__pruebas__/procesar', { headers: { 'X-CSRFToken': token } });
    assert.equal(respuesta.status(), 200);
    assert.equal((await respuesta.json()).procesados, 1);
    const terminado = await esperarEstado(dato => dato.envios.some(envio => envio.id === trabajo.id && envio.estado === 'completado'));
    assert.equal(terminado.versiones.length, 1);
    assert.equal(terminado.versiones[0].estado, 'procesado');
    assert.equal(terminado.versiones[0].sha256, createHash('sha256').update(bytes).digest('hex'));
    assert.equal(peticiones.length, Math.ceil(bytes.length / 1024));
    const repetido = await contexto.request.post(origen + '/__pruebas__/procesar', { headers: { 'X-CSRFToken': token } });
    assert.equal((await repetido.json()).procesados, 0);
    assert.equal((await estado()).versiones.length, 1);
    await page.close();
});
