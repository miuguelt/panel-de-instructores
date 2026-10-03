const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
let servidor, browser, url;

test.before(async () => {
    servidor = http.createServer((req, res) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        const destino = pathname.startsWith('/static/')
            ? path.resolve(raiz, 'app', pathname.slice(1))
            : path.join(raiz, 'test-results', 'grupos-navegador.html');
        if (!destino.startsWith(raiz + path.sep) || !fs.existsSync(destino)) {
            res.writeHead(404);
            res.end();
            return;
        }
        const tipo = {
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.html': 'text/html',
            '.svg': 'image/svg+xml'
        }[path.extname(destino)] || 'application/octet-stream';
        res.writeHead(200, { 'Content-Type': `${tipo}; charset=utf-8` });
        res.end(fs.readFileSync(destino));
    });
    await new Promise(resolve => servidor.listen(0, '127.0.0.1', resolve));
    url = `http://127.0.0.1:${servidor.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
});

test.after(async () => {
    if (browser) await browser.close();
    if (servidor) await new Promise(resolve => servidor.close(resolve));
});

test('la vista de grupos abre el modal de edición sin errores de scripts y sincroniza datos', async () => {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));

    // Bloquear CDNs externos para verificar autonomía local
    await page.route('**/*', route => new URL(route.request().url()).origin === url ? route.continue() : route.abort());

    await page.goto(url);
    await page.waitForTimeout(200);

    // 1. Verificar que el botón de edición exista y funcione
    const btnEditar = page.locator('.btn-group-edit').first();
    assert.equal(await btnEditar.isVisible(), true, 'El botón de editar debe ser visible');
    await btnEditar.click();
    await page.waitForTimeout(200);

    // 2. Verificar apertura del diálogo y campos poblados
    const estadoModal = await page.evaluate(() => {
        const d = document.getElementById('modalEditarGrupo');
        return {
            open: d ? d.open : false,
            title: document.getElementById('textoModalEditarTitulo')?.textContent?.trim(),
            nombre: document.getElementById('editNombreGrupo')?.value,
            action: document.getElementById('formEditarGrupo')?.getAttribute('action'),
            contador: document.getElementById('contadorEditSeleccionados')?.textContent?.trim()
        };
    });

    assert.equal(estadoModal.open, true, 'El diálogo de edición debe abrirse');
    assert.match(estadoModal.title, /Editar Equipo Alfa/, 'El título debe mostrar el nombre del equipo');
    assert.equal(estadoModal.nombre, 'Equipo Alfa', 'El campo de nombre debe precargarse');
    assert.match(estadoModal.action, /\/instructor\/fichas\/2\/grupos\/10\/editar/, 'La acción del formulario debe coincidir con la ruta de edición');
    assert.equal(estadoModal.contador, '1 seleccionados', 'Debe reflejar el miembro actual asignado');

    // 3. Probar buscador de aprendices en el modal
    await page.locator('#buscadorEditAprendices').fill('Ana');
    await page.waitForTimeout(100);
    const visiblesAna = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('.edit-aprendiz-row'))
            .filter(r => r.style.display !== 'none')
            .map(r => r.id);
    });
    assert.deepEqual(visiblesAna, ['edit-row-2'], 'Solo debe mostrarse Ana');

    // 4. Limpiar búsqueda y probar seleccionar todos
    await page.locator('#buscadorEditAprendices').fill('');
    await page.getByRole('button', { name: 'Seleccionar Todos', exact: true }).click();
    const contadorTodos = await page.locator('#contadorEditSeleccionados').textContent();
    assert.equal(contadorTodos.trim(), '3 seleccionados');

    // 5. Probar deseleccionar todos
    await page.getByRole('button', { name: 'Deseleccionar Todos', exact: true }).click();
    const contadorNinguno = await page.locator('#contadorEditSeleccionados').textContent();
    assert.equal(contadorNinguno.trim(), '0 seleccionados');

    // 6. Cerrar modal
    await page.locator('#modalEditarGrupo button:has-text("Cancelar")').click();
    await page.waitForTimeout(150);
    const cerrado = await page.evaluate(() => !document.getElementById('modalEditarGrupo').open);
    assert.equal(cerrado, true, 'El modal debe cerrarse al cancelar');

    // 7. Abrir creación manual y verificar reseteo
    await page.locator('button:has-text("Nuevo Equipo")').first().click();
    await page.waitForTimeout(150);
    const estadoCrear = await page.evaluate(() => {
        const d = document.getElementById('modalEditarGrupo');
        return {
            open: d ? d.open : false,
            title: document.getElementById('textoModalEditarTitulo')?.textContent?.trim(),
            nombre: document.getElementById('editNombreGrupo')?.value,
            action: document.getElementById('formEditarGrupo')?.getAttribute('action')
        };
    });
    assert.equal(estadoCrear.open, true, 'El diálogo debe abrirse para nuevo equipo');
    assert.equal(estadoCrear.title, 'Nuevo Equipo');
    assert.equal(estadoCrear.nombre, '');
    assert.match(estadoCrear.action, /\/instructor\/fichas\/2\/grupos\/crear/);

    // No debe haber ningún error en la página
    assert.deepEqual(errores, [], 'No debe registrarse ningún error JavaScript en la página');
    await page.close();
});
