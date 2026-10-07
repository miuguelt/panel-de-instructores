const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
const base = path.join(raiz, 'test-results', `experiencia-e2e-${process.pid}.sqlite`);
let proceso, browser, url;

async function iniciar() {
    proceso = spawn(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
        ['-u', '-m', 'tests.servidor_experiencia', base], { cwd: raiz, windowsHide: true,
            env: { ...process.env, FLASK_ENV: 'testing', REDIS_URL: '', DATABASE_URL: 'sqlite:///:memory:', LOG_LEVEL: 'ERROR' },
            stdio: ['ignore', 'pipe', 'pipe'] });
    url = await new Promise((resolve, reject) => {
        let salida = '', errores = '';
        const timer = setTimeout(() => reject(new Error('No inició el servidor de experiencia.')), 20000);
        proceso.stderr.on('data', dato => { errores += dato; });
        proceso.once('exit', code => { clearTimeout(timer); reject(new Error(`Servidor terminó (${code}): ${errores.slice(-1000)}`)); });
        proceso.stdout.on('data', dato => {
            salida += dato;
            const encontrado = salida.match(/URL=(http:\/\/127\.0\.0\.1:\d+)/);
            if (encontrado) { clearTimeout(timer); resolve(encontrado[1]); }
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
    await page.waitForFunction(() => window.learnerExperience && !document.getElementById('experience-save').disabled);
}

async function ajustar(page, valores) {
    await page.locator('#experience-settings').evaluate(el => { el.open = true; });
    await page.evaluate(valores => {
        for (const [nombre, valor] of Object.entries(valores)) {
            const el = document.getElementById('experience-' + nombre);
            if (typeof valor === 'boolean') el.checked = valor;
            else el.value = String(valor);
        }
    }, valores);
    const respuesta = page.waitForResponse(r => r.url().endsWith('/experiencia') && r.request().method() === 'POST');
    await page.locator('#experience-save').click();
    return respuesta;
}

test.before(async () => {
    fs.mkdirSync(path.dirname(base), { recursive: true });
    await iniciar();
    browser = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
});
test.after(async () => {
    if (browser) await browser.close();
    await detener();
    for (const archivo of [base, `${base}-wal`, `${base}-shm`]) {
        if (fs.existsSync(archivo)) await fs.promises.rm(archivo, { force: true, maxRetries: 10, retryDelay: 100 });
    }
});

test('la acción prioritaria revela la corrección y continuar abre una entrega colapsada pese a filtros', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    await ingresar(page);
    await page.locator('#experience-next-action').click();
    assert.equal(await page.locator('#btn-tab-evidencias-main').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#experiencia-tarea-1').isVisible(), true);
    assert.match(await page.locator('#experiencia-tarea-1').textContent(), /Requiere ajustes/);
    await page.locator('#task-search-input').fill('Sin coincidencias');
    await page.evaluate(() => window.learnerExperience.navigate({ tab: 'evidencias', taskId: 2 }));
    assert.equal(await page.locator('#task-search-input').inputValue(), '');
    assert.equal(await page.locator('#experiencia-tarea-2').isVisible(), true);
    assert.equal(await page.locator('.entregadas-details').evaluate(el => el.open), true);
    assert.equal(await page.locator('#experiencia-tarea-2').evaluate(el => document.activeElement === el), true);
    await page.waitForFunction(() => document.getElementById('experiencia-tarea-2').getBoundingClientRect().top >= document.querySelector('.app-header').getBoundingClientRect().bottom);
    await page.waitForFunction(() => document.getElementById('experience-status').dataset.kind === 'success');
    await page.reload();
    await page.locator('#experience-resume').waitFor({ state: 'visible' });
    await page.locator('#experience-resume').click();
    assert.equal(await page.locator('#experiencia-tarea-2').isVisible(), true);
    assert.deepEqual(errores, []);
    await contexto.close();
});

test('metas y preferencias sobreviven otra sesión y reinicio sin localStorage', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page);
    const respuesta = await ajustar(page, { 'weekly-goal': 8, 'notification-mode': 'quiet', 'ranking-visible': false,
        'reduced-motion': true, density: 'compact' });
    assert.equal(respuesta.status(), 200, await respuesta.text());
    await page.waitForFunction(() => document.getElementById('experience-status').dataset.kind === 'success');
    assert.equal(await page.locator('#panel-aprendiz-root').getAttribute('data-experience-density'), 'compact');
    assert.equal(await page.locator('#panel-aprendiz-root').evaluate(el => el.classList.contains('experience-reduced-motion')), true);
    assert.equal(await page.locator('[data-experience-ranking]:visible').count(), 0);
    await page.evaluate(() => localStorage.clear());
    await contexto.close();
    await detener();
    await iniciar();
    const nuevo = await browser.newContext();
    const otra = await nuevo.newPage();
    await ingresar(otra);
    assert.equal(await otra.locator('#experience-weekly-goal').inputValue(), '8');
    assert.equal(await otra.locator('#experience-notification-mode').inputValue(), 'quiet');
    assert.equal(await otra.locator('#experience-weekly-progress').getAttribute('aria-valuenow'), '25');
    await ingresar(otra, '1002');
    assert.equal(await otra.locator('#experience-weekly-goal').inputValue(), '2');
    assert.equal(await otra.locator('#experience-ranking-visible').isChecked(), true);
    assert.equal(await otra.locator('#experience-weekly-count').textContent(), '0');
    await nuevo.close();
});

test('un error mantiene ajustes pendientes y reintentar confirma el guardado real', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page);
    await page.route('**/aprendiz/1/experiencia', route => route.request().method() === 'POST'
        ? route.fulfill({ status: 503, contentType: 'application/problem+json', body: JSON.stringify({ ok: false, detail: 'No se pudo guardar. Reintenta.' }) }) : route.continue());
    assert.equal((await ajustar(page, { 'weekly-goal': 9 })).status(), 503);
    await page.locator('#experience-retry').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#experience-weekly-goal').inputValue(), '9');
    assert.equal(await page.locator('#experience-weekly-target').textContent(), '8');
    assert.equal(await page.locator('#experience-status').getAttribute('role'), 'alert');
    await page.unroute('**/aprendiz/1/experiencia');
    const respuesta = page.waitForResponse(r => r.url().endsWith('/experiencia') && r.request().method() === 'POST');
    await page.locator('#experience-retry').click();
    assert.equal((await respuesta).status(), 200);
    await page.waitForFunction(() => document.getElementById('experience-weekly-target').textContent === '9');
    await contexto.close();
});

test('dos pestañas detectan conflicto y la recarga conserva el último cambio confirmado', async () => {
    const contexto = await browser.newContext();
    const primera = await contexto.newPage();
    const segunda = await contexto.newPage();
    await ingresar(primera);
    await segunda.goto(`${url}/aprendiz/1/panel`);
    await segunda.waitForFunction(() => window.learnerExperience);
    assert.equal((await ajustar(primera, { 'weekly-goal': 10 })).status(), 200);
    assert.equal((await ajustar(segunda, { 'weekly-goal': 11 })).status(), 409);
    await segunda.locator('#experience-reload').waitFor({ state: 'visible' });
    assert.equal(await segunda.locator('#experience-weekly-goal').inputValue(), '11');
    await segunda.locator('#experience-reload').click();
    await segunda.waitForFunction(() => document.getElementById('experience-weekly-goal').value === '10');
    const datos = await (await contexto.request.get(`${url}/aprendiz/1/experiencia`)).json();
    assert.equal(datos.preferences.weeklyGoal, 10);
    await contexto.close();
});

test('tarjetas y controles se leen en celular, escritorio, tema oscuro y zoom', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page);
    await ajustar(page, { 'weekly-goal': 2, 'notification-mode': 'all', 'ranking-visible': true, density: 'comfortable' });
    await page.locator('#experience-settings').evaluate(el => { el.open = true; });
    for (const width of [320, 390, 768, 1440, 1920, 2560]) {
        await page.setViewportSize({ width, height: 1000 });
        const desbordados = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(el => { if (!el.getClientRects().length || el.getBoundingClientRect().right <= innerWidth + 1) return false; let parent = el.parentElement; while (parent && parent !== document.body) { if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(parent).overflowX)) return false; parent = parent.parentElement; } return true; }).map(el => ({ tag: el.tagName, id: el.id, clase: el.className, text: el.textContent.trim().slice(0, 80), parent: el.parentElement.className, right: el.getBoundingClientRect().right })).slice(0, 15));
        await page.screenshot({ path: path.join(raiz, 'test-results', `experiencia-${width}.png`), fullPage: true });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `Desbordamiento a ${width}px: ${JSON.stringify(desbordados)}`);
        const espacios = await page.locator('#aprendiz-experiencia .experience-card,#aprendiz-experiencia .experience-feedback,#aprendiz-experiencia .experience-insights,#aprendiz-experiencia .experience-settings').evaluateAll(els => els.map(el => { const s = getComputedStyle(el); return [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft].map(parseFloat); }));
        for (const espacio of espacios) assert.ok(espacio.every(px => px >= (width >= 640 ? 20 : 16)), `Espaciado perimetral insuficiente a ${width}px: ${espacio}`);
        const controles = await page.locator('#aprendiz-experiencia button,#aprendiz-experiencia input,#aprendiz-experiencia select').evaluateAll(els => els.filter(el => !el.hidden && el.getClientRects().length).map(el => { const target = el.type === 'checkbox' ? el.closest('label') : el; return { id: el.id, width: target.getBoundingClientRect().width, height: target.getBoundingClientRect().height }; }));
        for (const el of controles) assert.ok(el.height >= 42 && el.width >= 25, `${el.id} incompleto a ${width}px`);
        if ([390, 1440].includes(width)) await page.screenshot({ path: path.join(raiz, 'test-results', `experiencia-${width}.png`), fullPage: true });
        if (width === 1440) await page.locator('#aprendiz-experiencia').screenshot({ path: path.join(raiz, 'test-results', 'experiencia-inicio.png') });
    }
    await ajustar(page, { density: 'compact' });
    for (const width of [320, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        const espacio = await page.locator('.experience-next-card').evaluate(el => parseFloat(getComputedStyle(el).paddingTop));
        assert.ok(espacio >= (width >= 640 ? 20 : 16), `Espaciado compacto insuficiente a ${width}px: ${espacio}`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    }
    await page.setViewportSize({ width: 640, height: 800 });
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; document.documentElement.setAttribute('data-theme', 'dark'); });
    await page.screenshot({ path: path.join(raiz, 'test-results', 'experiencia-zoom-oscuro.png'), fullPage: true });
    const zoom = await page.evaluate(() => ({ inner: innerWidth, scroll: document.documentElement.scrollWidth,
        offenders: [...document.querySelectorAll('body *')].filter(el => { if (!el.getClientRects().length || el.getBoundingClientRect().right <= innerWidth + 1) return false; let parent = el.parentElement; while (parent && parent !== document.body) { if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(parent).overflowX)) return false; parent = parent.parentElement; } return true; }).map(el => ({ tag: el.tagName, id: el.id, clase: el.className, text: el.textContent.trim().slice(0, 80), parent: el.parentElement.className, right: el.getBoundingClientRect().right })).slice(0, 12) }));
    assert.ok(zoom.scroll <= zoom.inner + 1, `Desbordamiento a 200 %: ${JSON.stringify(zoom)}`);
    await contexto.close();
});

test('el centro agrupa avisos, conserva los importantes y permite leerlos con sesión y CSRF', async () => {
    const contexto = await browser.newContext();
    const page = await contexto.newPage();
    await ingresar(page);
    assert.equal((await ajustar(page, { 'notification-mode': 'quiet' })).status(), 200);
    await page.goto(`${url}/aprendiz/1/notificaciones`);
    assert.equal(await page.locator('.learner-notifications').getAttribute('data-notification-mode'), 'quiet');
    assert.equal(await page.getByText('Revisa los ajustes de tu evidencia.', { exact: true }).isVisible(), true);
    assert.equal(await page.getByText('Ya registraste tu primer avance.', { exact: true }).isVisible(), false);
    await page.locator('.notification-details summary').click();
    assert.equal(await page.getByText('Ya registraste tu primer avance.', { exact: true }).isVisible(), true);
    await page.setViewportSize({ width: 320, height: 900 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
    await page.locator('.learner-notifications').screenshot({ path: path.join(raiz, 'test-results', 'experiencia-notificaciones.png') });
    const contraste = await page.locator('.learner-notifications .btn-primary').first().evaluate(el => {
        const color = value => value.match(/[\d.]+/g).slice(0, 3).map(Number);
        const luz = value => color(value).map(n => { const c = n / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
        const estilo = getComputedStyle(el), a = luz(estilo.color);
        const fondos = estilo.backgroundImage.match(/rgba?\([^)]+\)/g) || [estilo.backgroundColor];
        return Math.min(...fondos.map(fondo => { const b = luz(fondo); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }));
    });
    assert.ok(contraste >= 4.5, `Contraste de acción insuficiente: ${contraste}`);
    const feedback = page.locator('.notification-item').filter({ hasText: 'Revisa los ajustes de tu evidencia.' });
    await feedback.getByRole('button', { name: 'Marcar como leída', exact: true }).click();
    await page.waitForURL('**/aprendiz/1/notificaciones');
    assert.equal(await page.locator('.notification-item').filter({ hasText: 'Revisa los ajustes de tu evidencia.' }).getByText('Leída', { exact: true }).isVisible(), true);
    await page.locator('.notification-item').filter({ hasText: 'Revisa los ajustes de tu evidencia.' }).getByRole('link', { name: 'Revisar comentarios' }).click();
    await page.waitForURL('**/aprendiz/1/panel#tab-evidencias');
    assert.equal(await page.locator('#btn-tab-evidencias-main').getAttribute('aria-selected'), 'true');
    await contexto.close();
});
