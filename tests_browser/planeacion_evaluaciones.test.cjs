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
            : path.join(raiz, 'test-results', 'evaluaciones-navegador.html');
        if (!destino.startsWith(raiz + path.sep) || !fs.existsSync(destino)) { res.writeHead(404); res.end(); return; }
        const tipo = { '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html', '.svg': 'image/svg+xml' }[path.extname(destino)] || 'application/octet-stream';
        res.writeHead(200, { 'Content-Type': tipo + '; charset=utf-8' });
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

test('El recorrido real muestra juicios, RAP, filtros y foco de teclado', async () => {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    await page.goto(url);
    await page.locator('[data-evaluacion-target="tramo-0"]').click();
    assert.equal(await page.locator('#pl-evaluaciones').evaluate(d => d.open), true, JSON.stringify(errores));
    assert.match(await page.locator('#pl-evaluaciones-contador').innerText(), /2 de 3/);
    assert.deepEqual(await page.locator('.pl-eval-aprendiz h3').allTextContents(), ['Beatriz de prueba', 'Carlos de prueba']);
    assert.match(await page.locator('.pl-eval-aprendiz').first().innerText(), /Evaluación parcial/);
    assert.match(await page.locator('.pl-eval-aprendiz').first().innerText(), /Instructor Tres/);
    assert.match(await page.locator('.pl-eval-aprendiz').first().innerText(), /15\/09\/2026/);
    await page.locator('[data-evaluacion-estado="evaluado"]').click();
    assert.deepEqual(await page.locator('.pl-eval-aprendiz h3').allTextContents(), ['Ángela de prueba']);
    assert.match(await page.locator('#pl-evaluaciones-lista').innerText(), /Instructor Uno/);
    assert.match(await page.locator('#pl-evaluaciones-lista').innerText(), /Instructor Dos/);
    await page.locator('[data-evaluacion-estado="todos"]').click();
    await page.locator('#pl-evaluaciones-buscar').fill('angela');
    assert.match(await page.locator('#pl-evaluaciones-contador').innerText(), /1 de 3/);
    await page.locator('#pl-evaluaciones-buscar').fill('100003');
    assert.deepEqual(await page.locator('.pl-eval-aprendiz h3').allTextContents(), ['Carlos de prueba']);
    await page.locator('#pl-evaluaciones-buscar').fill('No existe');
    assert.match(await page.locator('.pl-eval-vacio').innerText(), /Cambie el estado/);
    await page.locator('#pl-evaluaciones-buscar').fill('');
    await page.locator('#pl-evaluaciones-instructor').selectOption('Instructor Tres');
    assert.deepEqual(await page.locator('.pl-eval-aprendiz h3').allTextContents(), ['Beatriz de prueba']);
    assert.equal(await page.locator('#pl-evaluaciones-instructor option').filter({ hasText: 'Instructor previsto' }).count(), 0);
    await page.locator('#pl-evaluaciones-rap').selectOption('0');
    await page.locator('[data-evaluacion-estado="evaluado"]').click();
    assert.equal(await page.locator('.pl-eval-aprendiz').count(), 2);
    assert.match(await page.locator('#pl-evaluaciones-lista').innerText(), /No aprobado \(NA\)/);
    assert.equal(await page.locator('#pl-evaluaciones-lista').getByText('601401', { exact: false }).count(), 0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#pl-evaluaciones').evaluate(d => d.open), false);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.evaluacionTarget), 'tramo-0');
    await page.locator('[data-evaluacion-target="tramo-1"]').click();
    assert.match(await page.locator('#pl-evaluaciones-contexto').innerText(), /PLANEACIÓN/);
    assert.equal(await page.locator('#pl-evaluaciones-rap option').count(), 2);
    assert.equal(await page.locator('#pl-evaluaciones-rap option').filter({ hasText: '601390' }).count(), 0);
    await page.locator('#pl-evaluaciones-cerrar').click();
    assert.deepEqual(errores, []);
    await page.close();
});

test('Las tarjetas, los RAP y el diálogo caben desde 320 px y al ampliar al 200 %', async () => {
    for (const width of [320, 390, 768, 1440, 1920, 2560]) {
        const page = await browser.newPage({ viewport: { width, height: 1000 } });
        await page.goto(url);
        await page.locator('.pl-gantt-resultados').first().locator('summary').click();
        assert.equal(await page.locator('.pl-gantt-rap h4').first().isVisible(), true);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `La página desborda a ${width} px: ` + JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1 && e.getBoundingClientRect().width > 0).slice(0, 15).map(e => ({ tag: e.tagName, clase: e.className, ancho: e.getBoundingClientRect().width, derecha: e.getBoundingClientRect().right })))));
        await page.locator('[data-evaluacion-target="tramo-0"]').click();
        const medidas = await page.locator('#pl-evaluaciones').evaluate(d => ({ width: d.getBoundingClientRect().width, scroll: d.scrollWidth, client: d.clientWidth }));
        assert.ok(medidas.width <= width && medidas.scroll <= medidas.client + 1, `El diálogo desborda a ${width} px`);
        assert.ok(await page.locator('#pl-evaluaciones-cerrar').evaluate(b => b.getBoundingClientRect().height >= 44));
        if (width === 390) await page.screenshot({ path: path.join(raiz, 'test-results', 'evaluaciones-mobile.png') });
        if (width === 1440) await page.screenshot({ path: path.join(raiz, 'test-results', 'evaluaciones-desktop.png') });
        await page.keyboard.press('Escape');
        if (width === 390) await page.locator('#seccion-gantt').screenshot({ path: path.join(raiz, 'test-results', 'cronograma-mobile.png') });
        if (width === 1440) await page.locator('#seccion-gantt').screenshot({ path: path.join(raiz, 'test-results', 'cronograma-desktop.png') });
        if (width >= 768) {
            // El zoom de navegador al 200 % reduce a la mitad el ancho disponible en píxeles CSS.
            await page.setViewportSize({ width: width / 2, height: 500 });
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `La página desborda con el ancho disponible al 200 % de ${width} px`);
        }
        await page.close();
    }
});
