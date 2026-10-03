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
    await page.locator('[data-gantt-target="evento-0-0"]').click();
    await page.locator('#evento-0-0 [data-gantt-tab="aprendices"]').click();
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
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.ganttTarget), 'evento-0-0');
    await page.locator('[data-gantt-target="evento-1-0"]').click();
    await page.locator('#evento-1-0 [data-gantt-tab="aprendices"]').click();
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
        await page.locator('[data-gantt-target="evento-0-0"]').click();
        await page.locator('#evento-0-0 [data-gantt-tab="resultados"]').click();
        assert.equal(await page.locator('.pl-gantt-rap h4').first().isVisible(), true);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `La página desborda a ${width} px: ` + JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1 && e.getBoundingClientRect().width > 0).slice(0, 15).map(e => ({ tag: e.tagName, clase: e.className, ancho: e.getBoundingClientRect().width, derecha: e.getBoundingClientRect().right })))));
        await page.locator('#evento-0-0 [data-gantt-tab="aprendices"]').click();
        await page.locator('[data-evaluacion-target="tramo-0"]').click();
        const medidas = await page.locator('#pl-evaluaciones').evaluate(d => ({ width: d.getBoundingClientRect().width, scroll: d.scrollWidth, client: d.clientWidth }));
        assert.ok(medidas.width <= width && medidas.scroll <= medidas.client + 1, `El diálogo desborda a ${width} px`);
        assert.ok(await page.locator('#pl-evaluaciones-cerrar').evaluate(b => b.getBoundingClientRect().height >= 44));
        if (width === 390) await page.screenshot({ path: path.join(raiz, 'test-results', 'evaluaciones-mobile.png') });
        if (width === 1440) await page.screenshot({ path: path.join(raiz, 'test-results', 'evaluaciones-desktop.png') });
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#pl-gantt-evento').evaluate(d => d.open), true);
        const detalle = await page.locator('#pl-gantt-evento').evaluate(d => ({ width: d.getBoundingClientRect().width, scroll: d.scrollWidth, client: d.clientWidth }));
        assert.ok(detalle.width <= width && detalle.scroll <= detalle.client + 1, `El detalle del evento desborda a ${width} px`);
        if (width === 1440) await page.locator('#pl-gantt-evento').screenshot({ path: path.join(raiz, 'test-results', 'cronograma-evento.png') });
        await page.keyboard.press('Escape');
        await page.locator('[data-gantt-target="evento-0-0"]').evaluate(e => e.blur());
        await page.locator('.pl-gantt-name strong').first().evaluate(e => { e.textContent = 'Especificación de requisitos del software y análisis de las necesidades de información'; });
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `El nombre largo desborda a ${width} px`);
        if (width === 390 || width === 1440) await page.locator('#seccion-gantt').screenshot({
            path: path.join(raiz, 'test-results', width === 390 ? 'cronograma-mobile.png' : 'cronograma-desktop.png'),
            style: '.app-header, .pl-subnav, .app-notice-region, .skip-link { opacity: 0 !important; }',
        });
        if (width >= 768) {
            // El zoom de navegador al 200 % reduce a la mitad el ancho disponible en píxeles CSS.
            await page.setViewportSize({ width: width / 2, height: 500 });
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `La página desborda con el ancho disponible al 200 % de ${width} px`);
        }
        await page.close();
    }
});

test('El cronograma reserva el ancho para la línea de tiempo y abre eventos desde cualquier punto', async () => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    await page.goto(url);
    const fila = page.locator('.pl-gantt-row').first();
    const medidas = await fila.evaluate(e => {
        const label = e.querySelector('.pl-gantt-label').getBoundingClientRect();
        const track = e.querySelector('.pl-gantt-track').getBoundingClientRect();
        const escala = document.querySelector('.pl-gantt-scale-cols').getBoundingClientRect();
        return { alto: e.getBoundingClientRect().height, etiqueta: label.width, linea: track.width, diferencia: Math.abs(track.left - escala.left), diferenciaAncho: Math.abs(track.width - escala.width) };
    });
    assert.ok(medidas.alto <= 150, 'La tarjeta debe ser compacta: ' + JSON.stringify(medidas));
    assert.ok(medidas.linea >= medidas.etiqueta * 2, 'La línea de tiempo debe ocupar al menos el doble que el resumen');
    assert.ok(medidas.diferencia <= 2 && medidas.diferenciaAncho <= 2, 'La escala y las barras deben quedar alineadas');
    assert.equal(await fila.locator('.pl-gantt-acciones, .pl-gantt-evaluacion, .pl-gantt-resultados').count(), 0);
    assert.match(await page.locator('.pl-gantt-scale-cols').innerText(), /jul\. – oct\. 2025/);
    const track = page.locator('[data-gantt-target="evento-0-0"]');
    const ancho = await track.evaluate(e => e.clientWidth);
    await track.click({ position: { x: ancho - 30, y: 25 } });
    assert.equal(await page.locator('#pl-gantt-evento').evaluate(e => e.open), true);
    assert.equal(await page.locator('#pl-gantt-evento-titulo').innerText(), 'Inducción');
    assert.match(await page.locator('#evento-0-0').innerText(), /Periodo planeado/);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.ganttTarget), 'evento-0-0');
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#pl-gantt-evento').evaluate(e => e.open), true);
    await page.locator('#pl-gantt-evento-cerrar').click();
    await page.keyboard.press('Space');
    assert.equal(await page.locator('#pl-gantt-evento').evaluate(e => e.open), true);
    await page.locator('#evento-0-0 [data-gantt-tab="pedagogia"]').click();
    await page.locator('#evento-0-0 [data-pedagogico-target]').click();
    assert.equal(await page.locator('#pl-gantt-evento').evaluate(e => e.open), false);
    await page.waitForFunction(() => document.querySelector('#modal-pedagogico').getAttribute('aria-hidden') === 'false', null, { timeout: 2000 });
    assert.equal(await page.locator('#modal-pedagogico').getAttribute('aria-hidden'), 'false');
    await page.waitForFunction(() => document.querySelector('#modal-pedagogico').contains(document.activeElement), null, { timeout: 2000 });
    assert.equal(await page.evaluate(() => document.querySelector('#modal-pedagogico').contains(document.activeElement)), true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement.dataset.ganttTarget === 'evento-0-0', null, { timeout: 2000 });
    assert.equal(await page.evaluate(() => document.activeElement.dataset.ganttTarget), 'evento-0-0');
    for (let repeticion = 0; repeticion < 3; repeticion++) {
        await track.click();
        await page.locator('#evento-0-0 [data-gantt-tab="pedagogia"]').click();
        await page.locator('#evento-0-0 [data-pedagogico-target]').click();
        await page.waitForFunction(() => document.querySelector('#modal-pedagogico').contains(document.activeElement), null, { timeout: 2000 });
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => document.activeElement.dataset.ganttTarget === 'evento-0-0', null, { timeout: 2000 });
    }
    assert.deepEqual(errores, []);
    await page.close();
});

test('Ocultar la columna amplía el calendario, conserva los nombres y permite navegar las pestañas', async () => {
    for (const width of [320, 390, 768, 1440, 1920, 2560]) {
        const page = await browser.newPage({ viewport: { width, height: 1000 } });
        await page.goto(url);
        const control = page.locator('#pl-gantt-columnas');
        assert.equal(await control.count(), 1, 'El cronograma necesita un control para la columna');
        assert.ok(await page.locator('#contenido-principal').evaluate(e => e.getBoundingClientRect().width >= innerWidth * .95), 'La vista debe usar el ancho de pantalla');
        if (width >= 800) await control.click();
        assert.equal(await control.getAttribute('aria-expanded'), 'false');
        assert.equal(await page.locator('.pl-gantt-label').first().isVisible(), false);
        const fila = page.locator('.pl-gantt-row').first();
        assert.match(await fila.locator('.pl-gantt-evento-nombre').innerText(), /Inducción/);
        assert.ok(await fila.evaluate(e => e.querySelector('.pl-gantt-track').getBoundingClientRect().width >= e.clientWidth - 36), 'El evento debe usar todo el carril');
        if (width >= 1440) assert.ok(await fila.evaluate(e => e.clientHeight <= 120), 'La fila colapsada debe ser compacta: ' + await fila.evaluate(e => e.clientHeight));
        if (width === 1440) await page.locator('#seccion-gantt').screenshot({ path: path.join(raiz, 'test-results', 'cronograma-sin-columna.png'), style: '.app-header, .pl-subnav, .app-notice-region, .skip-link { opacity: 0 !important; }' });
        await control.click();
        assert.equal(await page.locator('.pl-gantt-label').first().isVisible(), true);
        await fila.locator('.pl-gantt-track').click();
        const tabs = page.locator('#evento-0-0 [role="tab"]');
        assert.equal(await tabs.count(), 4);
        await tabs.first().focus();
        await page.keyboard.press('ArrowRight');
        assert.equal(await tabs.nth(1).getAttribute('aria-selected'), 'true');
        assert.equal(await page.locator('#evento-0-0-resultados-pane').isVisible(), true);
        assert.equal(await page.locator('#evento-0-0-resumen-pane').isVisible(), false);
        await page.keyboard.press('End');
        assert.equal(await tabs.nth(3).getAttribute('aria-selected'), 'true');
        assert.match(await page.locator('#evento-0-0-pedagogia-pane').innerText(), /programa de formación/i);
        await page.keyboard.press('Home');
        assert.equal(await tabs.first().getAttribute('aria-selected'), 'true');
        for (const tab of await tabs.all()) {
            await tab.click();
            assert.equal(await page.locator('#evento-0-0 [role="tabpanel"]:visible').count(), 1);
            assert.ok(await tab.evaluate(e => e.getBoundingClientRect().height >= 44));
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        }
        if (width === 390) await page.locator('#pl-gantt-evento').screenshot({ path: path.join(raiz, 'test-results', 'cronograma-pestanas-mobile.png') });
        await page.keyboard.press('Escape');
        await fila.locator('.pl-gantt-track').click();
        assert.equal(await tabs.first().getAttribute('aria-selected'), 'true');
        await page.close();
    }
});

test('Los filtros ocultan las fases sin coincidencias y el estado vacío permite volver al cronograma', async () => {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await page.goto(url);
    const tecnicas = await page.locator('.pl-gantt-item[data-type="tecnicas"]').count();
    await page.locator('[data-filter="tecnicas"]').click();
    assert.equal(await page.locator('.pl-gantt-item:visible').count(), tecnicas);
    assert.equal(await page.locator('[data-filter="tecnicas"]').getAttribute('aria-pressed'), 'true');
    await page.locator('[data-filter="flexibles"]').click();
    assert.equal(await page.locator('.pl-gantt-item:visible').count(), 0);
    assert.equal(await page.locator('.pl-gantt-grupo:visible').count(), 0);
    assert.equal(await page.locator('#pl-gantt-vacio').isVisible(), true);
    await page.locator('[data-gantt-reset]').click();
    assert.equal(await page.locator('.pl-gantt-item:visible').count(), await page.locator('.pl-gantt-item').count());
    assert.equal(await page.locator('[data-filter="all"]').getAttribute('aria-pressed'), 'true');
    await page.close();
});

test('El análisis de competencias vencidas muestra fechas y abre modal con RAP y aprendices pendientes', async () => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(url);
    const seccionVencidas = page.locator('#pl-analisis-vencidas');
    assert.equal(await seccionVencidas.isVisible(), true);
    assert.match(await seccionVencidas.innerText(), /Competencias que ya deberían estar evaluadas/);
    assert.match(await seccionVencidas.innerText(), /debió evaluarse el/);

    const tarjetaVencida = seccionVencidas.locator('.pl-vencida-item').first();
    assert.equal(await tarjetaVencida.isVisible(), true);
    await tarjetaVencida.click();

    const dialogo = page.locator('#pl-evaluaciones');
    assert.equal(await dialogo.evaluate(d => d.open), true);
    assert.match(await page.locator('#pl-evaluaciones-titulo').innerText(), /Inducción/);
    assert.match(await page.locator('#pl-evaluaciones-contexto').innerText(), /Debió evaluarse:/);

    // Verifica que se muestre el resumen visual de resultados de aprendizaje (RAP)
    const rapsResumen = page.locator('#pl-evaluaciones-raps');
    assert.equal(await rapsResumen.isVisible(), true);
    assert.match(await rapsResumen.innerText(), /Resultados de aprendizaje/);

    // Verifica que los aprendices pendientes estén listados por defecto
    assert.match(await page.locator('#pl-evaluaciones-contador').innerText(), /2 de 3 aprendices/);
    assert.deepEqual(await page.locator('.pl-eval-aprendiz h3').allTextContents(), ['Beatriz de prueba', 'Carlos de prueba']);

    await page.locator('#pl-evaluaciones-cerrar').click();
    assert.equal(await dialogo.evaluate(d => d.open), false);
    await page.close();
});

