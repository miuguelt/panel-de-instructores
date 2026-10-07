const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
const base = path.join(raiz, 'test-results', `personalizacion-e2e-${process.pid}.sqlite`);
let proceso, browser, url;

async function iniciar() {
    const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    proceso = spawn(python, ['-u', '-m', 'tests.servidor_personalizacion', base], {
        cwd: raiz,
        env: { ...process.env, FLASK_ENV: 'testing', REDIS_URL: '', DATABASE_URL: 'sqlite:///:memory:', LOG_LEVEL: 'ERROR' },
        stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    });
    url = await new Promise((resolve, reject) => {
        let salida = '', errores = '';
        const timer = setTimeout(() => reject(new Error('El servidor de pruebas no inició.')), 20000);
        proceso.stderr.on('data', data => { errores += data.toString(); });
        proceso.once('exit', code => { clearTimeout(timer); reject(new Error(`Servidor terminado (${code}): ${errores.slice(-1500)}`)); });
        proceso.stdout.on('data', data => {
            salida += data.toString();
            const encontrada = salida.match(/URL=(http:\/\/127\.0\.0\.1:\d+)/);
            if (encontrada) { clearTimeout(timer); resolve(encontrada[1]); }
        });
    });
}

async function detener() {
    if (!proceso || proceso.exitCode !== null) return;
    const terminado = new Promise(resolve => proceso.once('exit', resolve));
    await fetch(`${url}/__pruebas__/detener`, { method: 'POST' });
    await terminado;
}

async function ingresar(page, documento = '1001') {
    await page.goto(`${url}/aprendiz/1`);
    await page.locator('#documento').fill(documento);
    await page.getByRole('button', { name: 'Ver mi estado' }).click();
    await page.waitForURL('**/aprendiz/1/panel');
    await page.waitForFunction(() => !document.getElementById('btn-save-personalizacion').disabled);
}

async function guardar(page) {
    const respuesta = page.waitForResponse(r => r.url() === `${url}/aprendiz/1/personalizacion` && r.request().method() === 'POST');
    await page.locator('#btn-save-personalizacion').click();
    const r = await respuesta;
    assert.equal(r.status(), 200, await r.text());
    await page.waitForFunction(() => !document.getElementById('personalizacion-modal').open);
    return r.json();
}

test.before(async () => {
    fs.mkdirSync(path.dirname(base), { recursive: true });
    await iniciar();
    browser = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
});
test.after(async () => {
    if (browser) await browser.close();
    await detener();
    for (const ruta of [base, `${base}-wal`, `${base}-shm`]) {
        if (fs.existsSync(ruta)) await fs.promises.rm(ruta, { force: true, maxRetries: 10, retryDelay: 100, recursive: true });
    }
});

test('las preferencias y la foto sobreviven a recarga, otro navegador y reinicio del servidor', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    await ingresar(page);
    await page.locator('#btn-open-customizer').click();
    assert.equal(await page.locator('#personalizacion-modal').evaluate(el => el.open), true);
    await page.locator('#customizer-alias-input').fill('Ana desarrolladora');
    await page.locator('#customizer-motto-input').fill('Código claro y metas propias.');
    await page.locator('.color-option-btn[data-theme-name="purple"]').click();
    await page.locator('#customizer-background-input').selectOption('dots');
    await page.locator('#customizer-view-mode-input').selectOption('cascade');
    // PNG preparado para pruebas; la API verifica y normaliza el contenido real.
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGNkYPjPgA0wYRUdtBIAy0MBD1YkjLoAAAAASUVORK5CYII=', 'base64');
    await page.locator('#customizer-photo-input').setInputFiles({ name: 'perfil.png', mimeType: 'image/png', buffer: png });
    const datos = await guardar(page);
    assert.equal(datos.preferences.alias, 'Ana desarrolladora');
    assert.ok(datos.photoUrl);
    assert.equal(await page.locator('#learner-display-name').textContent(), 'Ana desarrolladora');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForFunction(() => document.getElementById('learner-display-name').textContent === 'Ana desarrolladora');
    assert.equal(await page.locator('#panel-aprendiz-root').evaluate(el => el.classList.contains('is-cascade-mode')), true);
    assert.match(await page.locator('#learner-motto-text').textContent(), /Código claro/);
    await contexto.close();

    await detener();
    await iniciar();
    const nuevo = await browser.newContext();
    const otra = await nuevo.newPage();
    await ingresar(otra);
    await otra.waitForFunction(() => document.getElementById('learner-display-name').textContent === 'Ana desarrolladora');
    const recuperado = await (await nuevo.request.get(`${url}/aprendiz/1/personalizacion`)).json();
    assert.equal(recuperado.preferences.background, 'dots');
    assert.equal(recuperado.preferences.accent, '#7c3aed');
    const foto = await nuevo.request.get(`${url}${recuperado.photoUrl}`);
    assert.equal(foto.status(), 200);
    assert.match(foto.headers()['content-type'], /image\/jpeg/);
    assert.ok((await foto.body()).length > 100);
    await ingresar(otra, '1002');
    const ajeno = await (await nuevo.request.get(`${url}/aprendiz/1/personalizacion`)).json();
    assert.equal(ajeno.configured, false);
    assert.equal(ajeno.photoUrl, null);
    assert.equal(await otra.locator('#learner-display-name').textContent(), 'Luis');
    assert.deepEqual(errores, []);
    await nuevo.close();
});

test('un guardado fallido conserva el borrador y permite reintentar sin anunciar éxito', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page);
    const anterior = await page.locator('#learner-display-name').textContent();
    await page.locator('#btn-open-customizer').click();
    await page.locator('#customizer-alias-input').fill('Borrador recuperable');
    await page.route('**/aprendiz/1/personalizacion', route => route.request().method() === 'POST'
        ? route.fulfill({ status: 503, contentType: 'application/problem+json', body: JSON.stringify({ ok: false, detail: 'No se pudo guardar. Intenta de nuevo.' }) })
        : route.continue());
    const error = page.waitForResponse(r => r.request().method() === 'POST' && r.status() === 503);
    await page.locator('#btn-save-personalizacion').click();
    await error;
    await page.locator('#personalizacion-retry').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#personalizacion-modal').evaluate(el => el.open), true);
    assert.equal(await page.locator('#customizer-alias-input').inputValue(), 'Borrador recuperable');
    assert.equal(await page.locator('#learner-display-name').textContent(), anterior);
    await page.unroute('**/aprendiz/1/personalizacion');
    const respuesta = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/personalizacion'));
    await page.locator('#personalizacion-retry').click();
    assert.equal((await respuesta).status(), 200);
    await page.waitForFunction(() => document.getElementById('learner-display-name').textContent === 'Borrador recuperable');
    await contexto.close();
});

test('dos pestañas detectan conflicto y cancelar un restablecimiento conserva datos guardados', async () => {
    const contexto = await browser.newContext();
    const primera = await contexto.newPage();
    await ingresar(primera);
    const segunda = await contexto.newPage();
    await segunda.goto(`${url}/aprendiz/1/panel`);
    await segunda.waitForFunction(() => !document.getElementById('btn-save-personalizacion').disabled);
    await segunda.locator('#btn-open-customizer').click();
    await segunda.locator('#customizer-alias-input').fill('Cambio obsoleto');
    await primera.locator('#btn-open-customizer').click();
    await primera.locator('#customizer-alias-input').fill('Cambio reciente');
    await guardar(primera);
    const conflicto = segunda.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/personalizacion'));
    await segunda.locator('#btn-save-personalizacion').click();
    assert.equal((await conflicto).status(), 409);
    await segunda.locator('#personalizacion-reload').waitFor({ state: 'visible' });
    assert.equal(await segunda.locator('#customizer-alias-input').inputValue(), 'Cambio obsoleto');
    await segunda.locator('#personalizacion-reload').click();
    await segunda.waitForFunction(() => document.getElementById('customizer-alias-input').value === 'Cambio reciente');
    await segunda.locator('#btn-reset-personalizacion').click();
    await segunda.getByRole('button', { name: 'Cancelar', exact: true }).first().click();
    assert.equal(await segunda.locator('#learner-display-name').textContent(), 'Cambio reciente');
    const datos = await (await contexto.request.get(`${url}/aprendiz/1/personalizacion`)).json();
    assert.equal(datos.preferences.alias, 'Cambio reciente');
    assert.ok(datos.photoUrl);
    await segunda.locator('#btn-open-customizer').click();
    await segunda.locator('#btn-reset-personalizacion').click();
    const restablecido = await guardar(segunda);
    assert.equal(restablecido.preferences.alias, '');
    assert.equal(restablecido.photoUrl, null);
    assert.equal(await segunda.locator('#learner-display-name').textContent(), 'Ana');
    await contexto.close();
});

test('el personalizador conserva controles legibles en celular, escritorio y zoom del 200 %', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page);
    await page.locator('#btn-open-customizer').click();
    for (const ancho of [320, 390, 768, 1440, 1920, 2560]) {
        await page.setViewportSize({ width: ancho, height: 900 });
        await page.locator('#btn-save-personalizacion').click({ trial: true });
        const medidas = await page.locator('#personalizacion-modal').evaluate(el => {
            const panel = el.querySelector('.app-modal-content');
            const rect = panel.getBoundingClientRect();
            const campos = [...panel.querySelectorAll('input:not([type="hidden"]), select')];
            return { left: rect.left, right: rect.right, viewport: window.innerWidth,
                scroll: panel.scrollWidth, ancho: panel.clientWidth,
                campos: campos.map(c => ({ ancho: c.getBoundingClientRect().width, alto: c.getBoundingClientRect().height })) };
        });
        assert.ok(medidas.left >= 0 && medidas.right <= medidas.viewport + 1, `Ventana fuera del viewport a ${ancho}px: ${JSON.stringify(medidas)}`);
        assert.ok(medidas.scroll <= medidas.ancho + 1, `Desbordamiento del personalizador a ${ancho}px`);
        for (const campo of medidas.campos) assert.ok(campo.ancho >= 100 && campo.alto >= 42, `Control ilegible a ${ancho}px`);
        if ([390, 1440].includes(ancho)) await page.screenshot({ path: path.join(raiz, 'test-results', `personalizacion-${ancho}.png`) });
    }
    await page.setViewportSize({ width: 390, height: 900 });
    await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
    await page.locator('#btn-save-personalizacion').click({ trial: true });
    const temaOscuro = await page.locator('#personalizacion-modal .app-modal-content').evaluate(el => ({ fondo: getComputedStyle(el).backgroundColor, texto: getComputedStyle(el).color }));
    assert.notEqual(temaOscuro.fondo, 'rgb(255, 255, 255)');
    assert.notEqual(temaOscuro.fondo, temaOscuro.texto);
    const contrasteGuardar = await page.locator('#btn-save-personalizacion').evaluate(el => {
        const probe = document.createElement('span');
        probe.style.backgroundColor = 'var(--accent-primary)';
        el.appendChild(probe);
        const rgb = color => color.match(/[\d.]+/g).slice(0, 3).map(Number);
        const luminancia = color => rgb(color).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((s, v, i) => s + v * [.2126, .7152, .0722][i], 0);
        const texto = luminancia(getComputedStyle(el).color);
        const fondo = luminancia(getComputedStyle(probe).backgroundColor);
        probe.remove();
        return (Math.max(texto, fondo) + .05) / (Math.min(texto, fondo) + .05);
    });
    assert.ok(contrasteGuardar >= 4.5, `Contraste insuficiente del botón Guardar en tema oscuro: ${contrasteGuardar}`);
    await page.screenshot({ path: path.join(raiz, 'test-results', 'personalizacion-oscuro.png') });
    // El zoom del navegador reduce el viewport CSS y aumenta su densidad de píxeles.
    // CSS zoom conserva 100dvh y no representa esa geometría de los diálogos.
    const ampliado = await browser.newContext({ viewport: { width: 320, height: 450 }, deviceScaleFactor: 2 });
    const zoomPage = await ampliado.newPage();
    await ingresar(zoomPage);
    await zoomPage.locator('#btn-open-customizer').click();
    await zoomPage.locator('#btn-save-personalizacion').click({ trial: true });
    const zoom = await zoomPage.locator('#personalizacion-modal .app-modal-content').boundingBox();
    assert.ok(zoom.x >= 0 && zoom.x + zoom.width <= 321, 'El diálogo debe caber al ampliar el 200 %.');
    await zoomPage.locator('#btn-save-personalizacion').scrollIntoViewIfNeeded();
    assert.equal(await zoomPage.locator('#btn-save-personalizacion').isVisible(), true);
    await zoomPage.locator('#btn-save-personalizacion').click({ trial: true });
    await zoomPage.screenshot({ path: path.join(raiz, 'test-results', 'personalizacion-zoom.png') });
    await ampliado.close();
    await contexto.close();
});

test('recuperar preferencias del navegador y mover tarjetas produce un guardado persistente', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page, '1002');
    await page.evaluate(async () => {
        localStorage.setItem('sena_learner_prefs_2', JSON.stringify({ alias: 'Luis con metas', motto: 'Aprender y construir', themeName: 'indigo', accent: '#2563eb', avatar: '🚀' }));
        await window.learnerPersonalization.load();
    });
    await page.locator('#btn-open-customizer').click();
    await page.locator('#personalizacion-legacy').click();
    assert.equal(await page.locator('#customizer-alias-input').inputValue(), 'Luis con metas');
    const mover = page.locator('#personalizacion-order-list li').nth(1).getByRole('button', { name: /^Subir / });
    const id = (await mover.getAttribute('id')).replace(/^customizer-move-/, '').replace(/--1$/, '');
    await mover.click();
    const resultado = await guardar(page);
    assert.equal(resultado.preferences.sectionOrder[0], id);
    assert.equal(resultado.preferences.alias, 'Luis con metas');
    assert.equal(await page.evaluate(() => localStorage.getItem('sena_learner_prefs_2')), null);
    await page.reload();
    await page.waitForFunction(() => document.getElementById('learner-display-name').textContent === 'Luis con metas');
    const persistido = await (await contexto.request.get(`${url}/aprendiz/1/personalizacion`)).json();
    assert.deepEqual(persistido.preferences.sectionOrder, resultado.preferences.sectionOrder);
    await page.locator('#btn-open-customizer').click();
    const primero = page.locator('#personalizacion-order-list li').first();
    assert.equal(await primero.getByRole('button', { name: /^Subir / }).getAttribute('id'), `customizer-move-${id}--1`);
    assert.equal(await primero.getByRole('button', { name: /^Subir / }).isDisabled(), true);
    await contexto.close();
});

test('cambiar de aprendiz en otra pestaña impide guardar desde el formulario anterior', async () => {
    const contexto = await browser.newContext();
    const anterior = await contexto.newPage();
    await ingresar(anterior, '1001');
    await anterior.locator('#btn-open-customizer').click();
    await anterior.locator('#customizer-alias-input').fill('Formulario de Ana');
    const otra = await contexto.newPage();
    await ingresar(otra, '1002');
    const preferenciasLuis = await (await contexto.request.get(`${url}/aprendiz/1/personalizacion`)).json();
    const rechazo = anterior.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/personalizacion'));
    await anterior.locator('#btn-save-personalizacion').click();
    assert.equal((await rechazo).status(), 401);
    await anterior.locator('#personalizacion-retry').waitFor({ state: 'visible' });
    assert.equal(await anterior.locator('#customizer-alias-input').inputValue(), 'Formulario de Ana');
    const despues = await (await contexto.request.get(`${url}/aprendiz/1/personalizacion`)).json();
    assert.deepEqual(despues, preferenciasLuis);
    await contexto.close();
});
