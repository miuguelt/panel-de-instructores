const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
let servidor, browser, url;

test.before(async () => {
    const destinoHtml = path.join(raiz, 'test-results', 'aprendices-navegador.html');
    if (!fs.existsSync(destinoHtml)) {
        const pythonBin = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
        try {
            execFileSync(pythonBin, ['-m', 'tests.exportar_rendimiento'], { cwd: raiz, stdio: 'ignore' });
        } catch {
            try {
                execFileSync('python', ['-m', 'tests.exportar_rendimiento'], { cwd: raiz, stdio: 'ignore' });
            } catch {}
        }
    }

    servidor = http.createServer((req, res) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        const destino = pathname.startsWith('/static/')
            ? path.resolve(raiz, 'app', pathname.slice(1))
            : path.join(raiz, 'test-results', 'aprendices-navegador.html');
        if (!destino.startsWith(raiz + path.sep) || !fs.existsSync(destino)) {
            res.writeHead(404); res.end(); return;
        }
        const tipo = { '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html' }[path.extname(destino)] || 'application/octet-stream';
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

test('el directorio y los QR funcionan sin conexión a los CDN', async () => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    await page.route('**/*', route => new URL(route.request().url()).origin === url ? route.continue() : route.abort());
    await page.goto(url);
    assert.equal(await page.locator('#app-loading-overlay').isVisible(), false);
    assert.equal(await page.evaluate(() => htmx.version), '2.0.4');
    await page.waitForFunction(() => document.querySelector('#qr-code canvas')?.width === 320);
    await page.locator('#aprendices-search').fill('9000001');
    await page.waitForFunction(() => document.querySelector('#search-counter').textContent.includes('1 encontrado'));
    assert.equal(await page.locator('#tabla-aprendices tbody tr:visible').count(), 1);
    await page.locator('#aprendices-search').fill('');
    await page.locator('#herramientas-card > summary').click();
    await page.locator('#btn-open-tv-modal').click();
    assert.equal(await page.locator('#qr-code-tv canvas').getAttribute('width'), '1024');
    const descarga = page.waitForEvent('download');
    await page.locator('#btn-download-qr-hd').click();
    assert.match((await descarga).suggestedFilename(), /^QR_Acceso_Ficha_.*_HD\.png$/);
    assert.equal(await page.locator('#app-loading-overlay').isVisible(), false);
    assert.deepEqual(errores, []);
    await page.screenshot({ path: path.join(raiz, 'test-results', 'aprendices-carga.png') });
    await page.close();
});

test('un script pendiente no deja el HTML cubierto por el indicador', async () => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    let liberar;
    const espera = new Promise(resolve => { liberar = resolve; });
    await page.route('**/qrcode.min.js*', async route => { await espera; await route.abort(); });
    await page.goto(url, { waitUntil: 'commit' });
    await page.locator('#tabla-aprendices tbody tr').first().waitFor({ state: 'visible' });
    assert.equal(await page.locator('#app-loading-overlay').isVisible(), false);
    await page.waitForFunction(() => document.readyState === 'interactive');
    liberar();
    await page.waitForLoadState('domcontentloaded');
    await page.close();
});

test('la página permanece visible con JavaScript deshabilitado', async () => {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await page.goto(url);
    assert.equal(await page.locator('#app-loading-overlay').isVisible(), false);
    assert.equal(await page.locator('#tabla-aprendices tbody tr:visible').count(), 4);
    await context.close();
});
