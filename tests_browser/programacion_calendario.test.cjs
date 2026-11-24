const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
const resultados = path.join(raiz, 'test-results');
const base = path.join(resultados, `programacion-e2e-${process.pid}.sqlite`);
let proceso, browser, url;

async function iniciar() {
    const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    proceso = spawn(python, ['-u', '-m', 'tests.servidor_programacion', base], {
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

async function entrarComoCoordinacion(contexto) {
    const page = await contexto.newPage();
    await page.goto(`${url}/__pruebas__/entrar/2`);
    await page.waitForURL('**/programacion/');
    return page;
}

test.before(async () => {
    fs.mkdirSync(resultados, { recursive: true });
    await iniciar();
    browser = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
});
test.after(async () => {
    if (browser) await browser.close();
    await detener();
    for (const ruta of [base, `${base}-wal`, `${base}-shm`]) {
        if (fs.existsSync(ruta)) await fs.promises.rm(ruta, { force: true, maxRetries: 10, retryDelay: 100 });
    }
});

test('el calendario no desborda la página de 320 a 2560 px y conserva el texto completo', async () => {
    for (const ancho of [320, 390, 768, 1440, 1920, 2560]) {
        const contexto = await browser.newContext({ viewport: { width: ancho, height: 900 } });
        const page = await entrarComoCoordinacion(contexto);
        const medidas = await page.evaluate(() => ({
            pagina: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            competencia: [...document.querySelectorAll('.prg-chip-competencia')].map(e => e.textContent.trim()),
        }));
        assert.ok(medidas.pagina <= 1, `Desborde horizontal de ${medidas.pagina}px a ${ancho}px`);
        assert.ok(medidas.competencia.some(t => t.endsWith('metodologías de desarrollo')), 'El nombre de la competencia debe verse completo');
        await page.screenshot({ path: path.join(resultados, `programacion-${ancho}.png`), fullPage: true });
        await contexto.close();
    }
});

test('el formulario cubre entrada vacía, inválida, válida y reinicio', async () => {
    const contexto = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await entrarComoCoordinacion(contexto);
    const modal = page.locator('#modal-asignacion');
    const abrir = async () => {
        await page.getByRole('button', { name: 'Programar instructor' }).click();
        await assert.doesNotReject(modal.waitFor({ state: 'visible' }));
    };

    // Vacía: el navegador bloquea el envío y el diálogo sigue abierto.
    await abrir();
    await modal.getByRole('button', { name: 'Guardar' }).click();
    assert.equal(await modal.isVisible(), true);
    assert.equal(await page.locator('#prg-instructor').evaluate(e => e.validity.valueMissing), true);

    // Reinicio: «Limpiar» vacía los campos y vuelve a mostrar los días de la semana.
    await page.locator('#prg-instructor').selectOption({ label: 'Beto Agrícola · Agrícola' });
    await page.getByText('Un día', { exact: true }).click();
    assert.equal(await page.locator('#prg-fin').isVisible(), false);
    await modal.getByRole('button', { name: 'Limpiar' }).click();
    await page.waitForFunction(() => document.getElementById('prg-fin').offsetParent !== null);
    assert.equal(await page.locator('#prg-instructor').inputValue(), '');

    // Inválida: la fecha final es anterior a la inicial; el servidor explica qué corregir.
    const hoy = new Date();
    const iso = d => d.toISOString().slice(0, 10);
    const lunes = new Date(hoy); lunes.setDate(hoy.getDate() - ((hoy.getDay() + 6) % 7));
    const proximo = new Date(lunes); proximo.setDate(lunes.getDate() + 7);
    const sabado = new Date(proximo); sabado.setDate(proximo.getDate() + 5);
    await page.locator('#prg-instructor').selectOption({ label: 'Beto Agrícola · Agrícola' });
    await page.locator('#prg-ficha').selectOption('2');
    await page.locator('#prg-competencia').fill('Aplicar prácticas de protección ambiental');
    await page.locator('#prg-inicio').fill(iso(sabado));
    await page.locator('#prg-fin').fill(iso(proximo));
    await modal.getByRole('button', { name: 'Guardar' }).click();
    await page.waitForLoadState('domcontentloaded');
    assert.match(await page.locator('.flash-messages').innerText(), /anterior a la de inicio/);

    // Válida: queda programado y aparece en la semana siguiente.
    await abrir();
    await page.locator('#prg-instructor').selectOption({ label: 'Beto Agrícola · Agrícola' });
    await page.locator('#prg-ficha').selectOption('2');
    await page.locator('#prg-competencia').fill('Aplicar prácticas de protección ambiental');
    await page.locator('#prg-inicio').fill(iso(proximo));
    await page.locator('#prg-fin').fill(iso(sabado));
    await page.getByText('Tarde', { exact: true }).click();
    await modal.getByRole('button', { name: 'Guardar' }).click();
    await page.waitForLoadState('domcontentloaded');
    assert.match(await page.locator('.flash-messages').innerText(), /Programaste a Beto Agrícola en la ficha 2900002/);
    assert.ok(await page.locator('.prg-chip--tarde').count() >= 1);
    await contexto.close();
});

test('la vista Mi equipo es de solo lectura y no desborda de 320 a 2560 px', async () => {
    for (const ancho of [320, 390, 768, 1440, 1920, 2560]) {
        const contexto = await browser.newContext({ viewport: { width: ancho, height: 900 } });
        const page = await entrarComoCoordinacion(contexto);
        await page.goto(`${url}/programacion/equipo`);
        const medidas = await page.evaluate(() => ({
            pagina: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            titulo: document.querySelector('h1') ? document.querySelector('h1').textContent : '',
            programar: document.querySelectorAll('[data-prg-programar], [data-prg-editar], #form-asignacion').length,
        }));
        assert.ok(medidas.pagina <= 1, `Desborde horizontal de ${medidas.pagina}px a ${ancho}px`);
        assert.match(medidas.titulo, /Aún no perteneces|Mi equipo/);
        assert.equal(medidas.programar, 0);
        await contexto.close();
    }
    const contexto = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await contexto.newPage();
    await page.goto(`${url}/__pruebas__/entrar/3`);
    await page.goto(`${url}/programacion/equipo`);
    assert.match(await page.locator('h1').innerText(), /Equipo Sistemas/);
    assert.equal(await page.locator('[data-prg-programar], [data-prg-editar], #form-asignacion').count(), 0);
    assert.ok((await page.locator('.prg-chip-competencia').allInnerTexts()).some(t => t.endsWith('metodologías de desarrollo')));
    await page.screenshot({ path: path.join(resultados, 'programacion-mi-equipo-1440.png'), fullPage: true });
    await contexto.close();
});
