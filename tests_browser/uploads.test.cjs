const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const script = fs.readFileSync(path.resolve(__dirname, '../app/static/js/uploads.js'), 'utf8');
let servidor, browser, url, respuesta;
const recibidas = [];

const pagina = `<!doctype html><html lang="es-CO"><meta charset="utf-8"><title>Carga de archivos</title>
<form method="POST" action="/cargar" enctype="multipart/form-data">
<label>Archivo <input name="archivo" type="file" accept=".zip,application/zip" required></label>
<button type="submit" name="accion" value="subir">Cargar archivo</button>
<button type="submit" disabled id="bloqueado">Acción no disponible</button>
</form><script>window.ADSO_MAX_UPLOAD_BYTES=1000;window.ADSO_MAX_REQUEST_BYTES=1500;</script><script src="/uploads.js"></script></html>`;

function paginaPlaneacion() {
    // Ejecutar el controlador vigente de la plantilla conserva la regresión entre ambos listeners.
    const plantilla = fs.readFileSync(path.resolve(__dirname, '../app/templates/instructor/planeacion.html'), 'utf8');
    const controlador = plantilla.slice(plantilla.indexOf('// 2. Drag & Drop'), plantilla.indexOf('// 3. Catálogo'));
    return pagina.replace('<form method=', '<form id="form-carga-unificada" method=')
        .replace('<label>Archivo <input name="archivo" type="file" accept=".zip,application/zip" required></label>',
            '<div class="pl-dropzone" data-input-target="input-planeacion"><span class="pl-dropzone-text">Seleccione la planeación</span>' +
            '<span class="pl-file-preview" style="display:none"></span><input id="input-planeacion" name="archivo_planeacion" type="file" accept=".xlsx"></div>')
        .replace('</form>', '<p id="pl-carga-feedback"></p></form>')
        .replace('</html>', `<script>${controlador}</script></html>`);
}

function paginaMateriales() {
    const plantilla = fs.readFileSync(path.resolve(__dirname, '../app/templates/instructor/materiales.html'), 'utf8');
    const bloque = plantilla.slice(plantilla.indexOf('{% block scripts %}'));
    const controlador = bloque.slice(bloque.indexOf('<script>') + 8, bloque.indexOf('</script>'));
    const cuerpo = `<dialog id="modalSubir" open><form id="formSubir" method="POST" action="/cargar" enctype="multipart/form-data">
        <div id="dropZone"><input id="archivoInput" name="archivo" type="file" accept=".zip" required onchange="onFileSelect(this)">
        <span id="dropZoneFileName"></span></div><p id="materialCargaError" role="alert" hidden></p>
        <button type="button" id="quitar" onclick="limpiarArchivo()">Quitar archivo</button>
        <button type="button" id="btnCancelarSubir">Cancelar</button>
        <button type="submit" id="btnSubirArchivo">Subir Archivo</button>
        </form></dialog>`;
    return '<!doctype html><html lang="es-CO"><meta charset="utf-8"><title>Materiales</title>' + cuerpo +
        `<script>window.ADSO_MAX_UPLOAD_BYTES=1000;window.ADSO_MAX_REQUEST_BYTES=1500;</script><script src="/uploads.js"></script><script>${controlador}</script></html>`;
}

test.before(async () => {
    servidor = http.createServer((req, res) => {
        if (req.url === '/uploads.js') {
            res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8' }); res.end(script); return;
        }
        if (req.method === 'POST') {
            const partes = [];
            req.on('data', chunk => partes.push(chunk));
            req.on('end', () => {
                recibidas.push({ body: Buffer.concat(partes).toString(), xhr: req.headers['x-requested-with'] });
                res.writeHead(respuesta.status, { 'Content-Type': respuesta.tipo ?? 'application/json' });
                res.end(typeof respuesta.body === 'string' ? respuesta.body : JSON.stringify(respuesta.body));
            });
            return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(req.url === '/guardado' ? '<h1>Archivo guardado</h1>' : req.url === '/planeacion' ? paginaPlaneacion() : req.url === '/materiales' ? paginaMateriales() : pagina);
    });
    await new Promise(resolve => servidor.listen(0, '127.0.0.1', resolve));
    url = `http://127.0.0.1:${servidor.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
});

test.after(async () => {
    if (browser) await browser.close();
    if (servidor) await new Promise(resolve => servidor.close(resolve));
});

test('un ZIP conserva selección y acción, evita doble envío y permite corregir el error', async () => {
    const page = await browser.newPage();
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    const inicio = recibidas.length;
    respuesta = { status: 400, body: { ok: false, message: 'El ZIP está incompleto. Vuelve a comprimir la carpeta.' } };
    await page.goto(url);
    await page.locator('input[type=file]').setInputFiles({ name: 'proyecto.zip', mimeType: 'application/octet-stream', buffer: Buffer.from('contenido de la evidencia') });
    await page.evaluate(() => {
        const form = document.querySelector('form');
        const boton = form.querySelector('button');
        for (let i = 0; i < 2; i++) form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: boton }));
    });
    await page.getByRole('alert').waitFor();
    assert.equal(recibidas.length - inicio, 1);
    assert.match(recibidas.at(-1).body, /name="accion"\r\n\r\nsubir/);
    assert.match(recibidas.at(-1).body, /filename="proyecto.zip"/);
    assert.equal(recibidas.at(-1).xhr, 'XMLHttpRequest');
    assert.match(await page.getByRole('alert').textContent(), /ZIP está incompleto/);
    assert.equal(await page.locator('input[type=file]').evaluate(input => input.files[0].name), 'proyecto.zip');
    assert.equal(await page.getByRole('button', { name: 'Cargar archivo' }).isEnabled(), true);
    assert.equal(await page.locator('#bloqueado').isEnabled(), false);
    assert.equal(await page.locator('.upload-progress').count(), 0);
    respuesta = { status: 200, body: { ok: true, redirect: '/guardado' } };
    await page.getByRole('button', { name: 'Cargar archivo' }).click();
    await page.waitForURL(`${url}/guardado`);
    assert.equal(await page.getByRole('heading').textContent(), 'Archivo guardado');
    assert.equal(recibidas.length - inicio, 2);
    assert.deepEqual(errores, []);
    await page.close();
});

test('un validador local puede cancelar el envío y una sesión expirada ofrece recarga', async () => {
    const page = await browser.newPage();
    const inicio = recibidas.length;
    await page.goto(url);
    await page.locator('input[type=file]').setInputFiles({ name: 'proyecto.zip', mimeType: 'application/zip', buffer: Buffer.from('contenido') });
    await page.evaluate(() => {
        document.querySelector('form').addEventListener('submit', evento => evento.preventDefault(), { once: true });
    });
    await page.getByRole('button', { name: 'Cargar archivo' }).click();
    assert.equal(await page.locator('.upload-progress').count(), 0);
    assert.equal(recibidas.length, inicio);
    respuesta = { status: 400, body: { ok: false, message: 'La sesión del formulario expiró.', reload: true } };
    await page.getByRole('button', { name: 'Cargar archivo' }).click();
    await page.getByRole('alert').waitFor();
    assert.equal(await page.getByRole('button', { name: 'Recargar formulario' }).isVisible(), true);
    const recarga = page.waitForEvent('load');
    await page.getByRole('button', { name: 'Recargar formulario' }).click();
    await recarga;
    assert.equal(await page.locator('.upload-error').count(), 0);
    assert.equal(recibidas.length - inicio, 1);
    await page.close();
});

test('una página heredada con error mantiene el mensaje visible sin otra navegación', async () => {
    const page = await browser.newPage();
    respuesta = { status: 200, tipo: 'text/html', body: '<div class="flash-messages"><p class="alert-error">El formato del archivo no coincide con su contenido.</p></div>' };
    await page.goto(url);
    await page.locator('input[type=file]').setInputFiles({ name: 'proyecto.zip', mimeType: 'application/zip', buffer: Buffer.from('contenido') });
    await page.getByRole('button', { name: 'Cargar archivo' }).click();
    await page.getByRole('alert').waitFor();
    assert.match(await page.getByRole('alert').textContent(), /formato del archivo/);
    assert.equal(page.url(), `${url}/`);
    await page.close();
});

test('la carga unificada de planeación usa un solo controlador y conserva su validación', async () => {
    const page = await browser.newPage();
    const inicio = recibidas.length;
    respuesta = { status: 400, body: { ok: false, message: 'La planeación no contiene las columnas requeridas.' } };
    await page.goto(`${url}/planeacion`);
    await page.getByRole('button', { name: 'Cargar archivo' }).click();
    assert.match(await page.locator('#pl-carga-feedback').textContent(), /al menos un archivo/);
    assert.equal(recibidas.length, inicio);
    await page.locator('input[type=file]').setInputFiles({ name: 'planeacion.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('contenido') });
    await page.getByRole('button', { name: 'Cargar archivo' }).click();
    await page.getByRole('alert').waitFor();
    assert.match(await page.getByRole('alert').textContent(), /columnas requeridas/);
    assert.equal(recibidas.length - inicio, 1);
    assert.match(recibidas.at(-1).body, /name="archivo_planeacion"/);
    assert.equal(await page.getByRole('button', { name: 'Cargar archivo' }).isEnabled(), true);
    await page.close();
});

test('la selección de planeación muestra el nombre literalmente y permite quitarlo', async () => {
    const page = await browser.newPage();
    await page.goto(`${url}/planeacion`);
    const nombre = '<img src=x onerror=window.nombreInyectado=true>.xlsx';
    await page.locator('input[type=file]').setInputFiles({ name: nombre, mimeType: 'application/octet-stream', buffer: Buffer.from('contenido') });
    assert.ok((await page.locator('.pl-file-preview').textContent()).includes(nombre));
    assert.equal(await page.locator('.pl-file-preview img').count(), 0);
    assert.equal(await page.evaluate(() => Boolean(window.nombreInyectado)), false);
    await page.locator('input[type=file]').setInputFiles([]);
    assert.equal(await page.locator('.pl-file-preview').isVisible(), false);
    assert.equal(await page.locator('.pl-dropzone-text').isVisible(), true);
    await page.close();
});

test('arrastrar una carpeta o varios documentos avisa y no carga un archivo parcial', async () => {
    const page = await browser.newPage();
    await page.goto(`${url}/planeacion`);
    await page.evaluate(() => {
        const evento = new Event('drop', { bubbles: true, cancelable: true });
        Object.defineProperty(evento, 'dataTransfer', { value: {
            items: [{ webkitGetAsEntry() { return { isDirectory: true }; } }], files: new DataTransfer().files,
        } });
        document.querySelector('.pl-dropzone').dispatchEvent(evento);
    });
    assert.match(await page.locator('#pl-carga-feedback').textContent(), /carpeta|ZIP/i);
    assert.equal(await page.locator('input[type=file]').evaluate(input => input.files.length), 0);
    await page.evaluate(() => {
        const datos = new DataTransfer();
        datos.items.add(new File(['contenido'], 'a.xlsx'));
        datos.items.add(new File(['contenido'], 'b.xlsx'));
        document.querySelector('.pl-dropzone').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: datos }));
    });
    assert.match(await page.locator('#pl-carga-feedback').textContent(), /un.*archivo|varios/i);
    assert.equal(await page.locator('input[type=file]').evaluate(input => input.files.length), 0);
    await page.close();
});

test('materiales permite reintentar y cancelar después de un error de carga', async () => {
    const page = await browser.newPage();
    const inicio = recibidas.length;
    respuesta = { status: 400, body: { ok: false, message: 'El ZIP está incompleto.' } };
    await page.goto(`${url}/materiales`);
    await page.locator('input[type=file]').setInputFiles({ name: 'material.zip', mimeType: 'application/zip', buffer: Buffer.from('contenido') });
    await page.getByRole('button', { name: 'Subir Archivo', exact: true }).click();
    await page.locator('.upload-error').waitFor();
    assert.equal(recibidas.length - inicio, 1);
    assert.equal(await page.locator('#btnSubirArchivo').isEnabled(), true);
    assert.equal(await page.locator('#btnSubirArchivo').textContent(), 'Subir Archivo');
    assert.notEqual(await page.locator('#btnCancelarSubir').evaluate(el => getComputedStyle(el).pointerEvents), 'none');
    assert.equal(await page.locator('#modalSubir').evaluate(el => el.classList.contains('is-loading')), false);
    respuesta = { status: 200, body: { ok: true, redirect: '/guardado' } };
    await page.getByRole('button', { name: 'Subir Archivo', exact: true }).click();
    await page.waitForURL(`${url}/guardado`);
    assert.equal(recibidas.length - inicio, 2);
    await page.close();
});

test('materiales rechaza carpetas y varios archivos sin quedarse solo con el primero', async () => {
    const page = await browser.newPage();
    await page.goto(`${url}/materiales`);
    await page.evaluate(() => {
        const evento = new Event('drop', { bubbles: true, cancelable: true });
        Object.defineProperty(evento, 'dataTransfer', { value: {
            items: [{ webkitGetAsEntry() { return { isDirectory: true }; } }], files: new DataTransfer().files,
        } });
        document.querySelector('#dropZone').dispatchEvent(evento);
    });
    assert.match(await page.locator('#materialCargaError').textContent(), /carpeta.*ZIP/i);
    assert.equal(await page.locator('input[type=file]').evaluate(input => input.files.length), 0);
    await page.evaluate(() => {
        const datos = new DataTransfer();
        datos.items.add(new File(['contenido'], 'a.zip'));
        datos.items.add(new File(['contenido'], 'b.zip'));
        document.querySelector('#dropZone').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: datos }));
    });
    assert.match(await page.locator('#materialCargaError').textContent(), /un.*archivo|varios/i);
    assert.equal(await page.locator('input[type=file]').evaluate(input => input.files.length), 0);
    await page.evaluate(() => {
        const datos = new DataTransfer();
        datos.items.add(new File(['contenido'], '<img src=x>.zip'));
        document.querySelector('#dropZone').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: datos }));
    });
    assert.equal(await page.locator('#dropZoneFileName').textContent(), '<img src=x>.zip');
    assert.equal(await page.locator('#dropZoneFileName img').count(), 0);
    assert.equal(await page.locator('#materialCargaError').isVisible(), false);
    await page.getByRole('button', { name: 'Quitar archivo' }).click();
    assert.equal(await page.locator('input[type=file]').evaluate(input => input.files.length), 0);
    assert.equal(await page.locator('#dropZone').evaluate(el => el.classList.contains('has-file')), false);
    await page.close();
});
