const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { createHash } = require('node:crypto');
const { chromium } = require('playwright');

let servidor, browser, origen, temporal;
let sesiones, inicios, bloques, formularios, modo, contador;
const script = nombre => fs.readFileSync(path.join(__dirname, '../app/static/js', nombre), 'utf8');

test.before(async () => {
    temporal = fs.mkdtempSync(path.join(os.tmpdir(), 'adso-cargas-ui-'));
    fs.writeFileSync(path.join(temporal, 'evidencia.zip'), 'abcdefghijklmn');
    servidor = http.createServer(async (req, res) => {
        const piezas = [];
        for await (const pieza of req) piezas.push(pieza);
        const datos = Buffer.concat(piezas);
        const json = (status, body) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
        if (req.url === '/') {
            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(`<!doctype html><html lang="es-CO"><meta charset="utf-8"><meta name="csrf-token" content="csrf-ui-prueba"><title>Carga reanudable</title>
                <form method="POST" action="/guardar" enctype="multipart/form-data"><label>Evidencia <input name="archivo" type="file" accept=".zip"></label>
                <input name="descripcion" value="Evidencia revisada"><button type="submit" name="accion" value="guardar">Guardar</button></form>
                <script>window.ADSO_MAX_UPLOAD_BYTES=3;window.ADSO_MAX_REQUEST_BYTES=5;window.ADSO_RESUMABLE_UPLOAD={enabled:true,maxBytes:2147483648,chunkBytes:4,url:'/cargas'};</script>
                <script src="/uploads_reanudables.js"></script><script src="/uploads.js"></script></html>`);
        } else if (req.url === '/uploads.js' || req.url === '/uploads_reanudables.js') {
            res.writeHead(200, { 'Content-Type': 'text/javascript' }); res.end(script(req.url.slice(1)));
        } else if (req.url === '/cargas' && req.method === 'POST') {
            assert.equal(req.headers['x-csrftoken'], 'csrf-ui-prueba');
            const clave = req.headers['idempotency-key'];
            assert.match(clave, /^[a-f0-9-]{36}$/);
            if (inicios.has(clave)) return json(201, inicios.get(clave));
            const entrada = JSON.parse(datos.toString());
            const carga = { ok: true, id: String(++contador), estado: 'subiendo', tamano: entrada.tamano, offset: 0, chunk_bytes: 4, huellas: [], vence_en: new Date(Date.now() + 86400000).toISOString() };
            sesiones.set(carga.id, carga); inicios.set(clave, carga);
            if (modo === 'perder-inicio') { modo = 'normal'; req.socket.destroy(); return; }
            json(201, carga);
        } else if (req.url.startsWith('/cargas/')) {
            const carga = sesiones.get(req.url.split('/').pop());
            if (!carga) return json(404, { ok: false });
            if (req.method === 'PATCH') {
                if (modo === 'detener' && carga.offset >= 4) return json(403, { ok: false, message: 'Pausa para comprobar la recuperación.' });
                assert.equal(req.headers['x-chunk-sha256'], createHash('sha256').update(datos).digest('hex'));
                if (Number(req.headers['upload-offset']) !== carga.offset) return json(409, { ok: false, message: 'El bloque ya fue recibido.' });
                bloques.push(carga.offset); carga.offset += datos.length; carga.huellas.push(req.headers['x-chunk-sha256']);
                if (carga.offset === carga.tamano) carga.estado = 'recibido';
                if (modo === 'perder') { modo = 'normal'; req.socket.destroy(); return; }
            }
            json(200, carga);
        } else if (req.url === '/guardar') {
            formularios.push(datos.toString()); json(200, { ok: true, redirect: '/confirmado' });
        } else if (req.url === '/confirmado') {
            res.writeHead(200, { 'Content-Type': 'text/html' }); res.end('<h1>Carga confirmada</h1>');
        } else { res.writeHead(404); res.end(); }
    });
    await new Promise(resolve => servidor.listen(0, '127.0.0.1', resolve));
    origen = `http://127.0.0.1:${servidor.address().port}`;
    browser = await chromium.launch();
});

test.beforeEach(() => { sesiones = new Map(); inicios = new Map(); bloques = []; formularios = []; contador = 0; modo = 'normal'; });
test.after(async () => {
    await browser?.close(); await new Promise(resolve => servidor?.close(resolve));
    fs.unlinkSync(path.join(temporal, 'evidencia.zip')); fs.rmdirSync(temporal);
});

test('Chromium envía bloques firmados y confirma sin incluir el archivo completo en el formulario', async () => {
    const page = await browser.newPage(); await page.goto(origen);
    await page.locator('input[type=file]').setInputFiles(path.join(temporal, 'evidencia.zip'));
    await page.getByRole('button', { name: 'Guardar', exact: true }).click();
    await page.waitForURL('**/confirmado', { timeout: 10000 });
    assert.deepEqual(bloques, [0, 4, 8, 12]);
    assert.equal(formularios.length, 1);
    assert.ok(formularios[0].includes('Evidencia revisada'));
    assert.ok(formularios[0].includes('_cargas'));
    assert.ok(formularios[0].includes('_carga_envio'));
    assert.ok(formularios[0].includes('guardar'));
    assert.equal(formularios[0].includes('filename='), false);
    await page.close();
});

test('Chromium recupera una respuesta perdida sin retransmitir el bloque recibido', async () => {
    modo = 'perder';
    const page = await browser.newPage(); await page.goto(origen);
    await page.locator('input[type=file]').setInputFiles(path.join(temporal, 'evidencia.zip'));
    await page.getByRole('button', { name: 'Guardar', exact: true }).click();
    try { await page.waitForURL('**/confirmado', { timeout: 10000 }); }
    catch (error) { error.message += '\n' + await page.locator('body').innerText() + '\n' + JSON.stringify(bloques); throw error; }
    assert.deepEqual(bloques, [0, 4, 8, 12]);
    assert.equal(formularios.length, 1);
    await page.close();
});

test('Chromium conserva el avance tras recargar y verifica el archivo reseleccionado', async () => {
    modo = 'detener';
    const page = await browser.newPage(); await page.goto(origen);
    await page.locator('input[type=file]').setInputFiles(path.join(temporal, 'evidencia.zip'));
    await page.getByRole('button', { name: 'Guardar', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Pausa para comprobar' }).waitFor();
    assert.deepEqual(bloques, [0]);
    await page.reload(); modo = 'normal';
    await page.locator('input[type=file]').setInputFiles(path.join(temporal, 'evidencia.zip'));
    await page.getByRole('button', { name: 'Guardar', exact: true }).click();
    await page.waitForURL('**/confirmado', { timeout: 10000 });
    assert.deepEqual(bloques, [0, 4, 8, 12]);
    assert.equal(sesiones.size, 1);
    await page.close();
});

test('Chromium recupera una respuesta de inicio perdida sin crear otra sesión', async () => {
    modo = 'perder-inicio';
    const page = await browser.newPage(); await page.goto(origen);
    await page.locator('input[type=file]').setInputFiles(path.join(temporal, 'evidencia.zip'));
    await page.getByRole('button', { name: 'Guardar', exact: true }).click();
    await page.waitForURL('**/confirmado', { timeout: 10000 });
    assert.equal(inicios.size, 1);
    assert.equal(sesiones.size, 1);
    assert.deepEqual(bloques, [0, 4, 8, 12]);
    assert.equal(formularios.length, 1);
    await page.close();
});
