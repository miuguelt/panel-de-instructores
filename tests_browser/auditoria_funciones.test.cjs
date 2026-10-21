const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const raiz = path.resolve(__dirname, '..');
const leer = nombre => fs.readFileSync(path.join(raiz, nombre), 'utf8');
function bloque(nombre, marcador) {
    return [...leer(nombre).matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(match => match[1]).find(texto => texto.includes(marcador)) || '';
}
function pagina(cuerpo, scripts = '') { return `<!doctype html><html lang="es-CO"><meta charset="utf-8"><title>Prueba del panel</title><body>${cuerpo}<script>${scripts}</script></body></html>`; }
function atributo(valor) { return String(valor).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'); }
function render(fragmento, contexto) {
    const python = process.env.PYTHON || (process.platform === 'win32' ? path.join(raiz, 'venv_win/Scripts/python.exe') : 'python3');
    return execFileSync(python, ['-c', 'import json,sys; from jinja2 import Environment; d=json.load(sys.stdin); e=Environment(autoescape=True); e.globals["url_for"]=lambda *a,**kw:"/archivos/imagen.png"; print(e.from_string(d["template"]).render(**d["context"]))'], { cwd: raiz, input: JSON.stringify({ template: fragmento, context: contexto }), encoding: 'utf8' });
}
let servidor, browser, url;
let respuestaImportacion = { estado: 'encolado' };
let respuestaChat = {};
const paginas = new Map();

test.before(async () => {
    servidor = http.createServer((req, res) => {
        if (req.url === '/uploads.js') { res.writeHead(200, { 'Content-Type': 'application/javascript' }); res.end(leer('app/static/js/uploads.js')); return; }
        if (req.url === '/importaciones.js' || req.url === '/grupo_chat.js') { res.writeHead(200, { 'Content-Type': 'application/javascript' }); res.end(leer('app/static/js' + req.url)); return; }
        if (req.url === '/import-job') { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(respuestaImportacion)); return; }
        if (req.url === '/import-job-redirect') { res.writeHead(302, { Location: '/auth/login' }); res.end(); return; }
        if (req.url === '/chat-mensajes') {
            req.resume(); res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(req.method === 'POST' ? respuestaChat : { messages: [] })); return;
        }
        if (req.method === 'POST') {
            req.resume();
            res.writeHead(req.url === '/competencias/toggle' ? 200 : 400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(req.url === '/competencias/toggle'
                ? { success: true, esta_seleccionada: true, seleccionada_por: { es_propia: false, nombre: '<img src=x onerror=window.inyeccion=true>' } }
                : { ok: false, message: 'El archivo no contiene un reporte válido.' }));
            return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(paginas.get(req.url) || pagina('Página de prueba'));
    });
    await new Promise(resolve => servidor.listen(0, '127.0.0.1', resolve));
    url = `http://127.0.0.1:${servidor.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
});
test.after(async () => { if (browser) await browser.close(); if (servidor) await new Promise(resolve => servidor.close(resolve)); });

test('la importación de fichas recupera su botón después del error', async () => {
    const controlador = bloque('app/templates/instructor/fichas.html', "getElementById('import-report-form')");
    paginas.set('/fichas', pagina('<form id="import-report-form" action="/importar" method="POST" enctype="multipart/form-data"><input type="file" name="archivo" accept=".xlsx"><button type="submit">Importar reporte</button></form>', controlador) + '<script src="/uploads.js"></script>');
    const page = await browser.newPage(); await page.goto(`${url}/fichas`);
    await page.locator('input').setInputFiles({ name: 'reporte.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('contenido') });
    await page.locator('button[type=submit]').click(); await page.getByRole('alert').waitFor();
    assert.equal(await page.locator('button[type=submit]').textContent(), 'Importar reporte');
    assert.equal(await page.locator('button[type=submit]').isEnabled(), true);
    assert.notEqual(await page.locator('button[type=submit]').evaluate(el => getComputedStyle(el).pointerEvents), 'none');
    await page.close();
});

test('el detalle RAP muestra contenido importado como texto y conserva apertura y cierre', async () => {
    const payload = '<img src=x onerror=window.inyeccion=true>';
    const raps = [{ competencia: payload, rap: payload, fase: payload, horas_directas: 6 }];
    paginas.set('/rap', pagina(`<button class="pl-heatmap-cell" role="button" data-raps="${atributo(JSON.stringify(raps))}" data-doc="Instructor" data-trim="Trimestre 1" data-horas-dir="6" data-horas-tot="8" data-int-dir="2">Detalle</button><div id="modal-detalle-raps" hidden><h2 id="modal-raps-titulo"></h2><p id="modal-raps-subtitulo"></p><div id="modal-raps-cuerpo"></div></div>`, 'window.abrirModal=el=>el.hidden=false;window.cerrarModal=el=>el.hidden=true;' + bloque('app/templates/instructor/_planeacion_panorama.html', 'function mostrarDetalleRap')));
    const page = await browser.newPage(); await page.goto(`${url}/rap`);
    await page.getByRole('button', { name: 'Detalle' }).press('Enter');
    assert.equal(await page.locator('#modal-detalle-raps').isVisible(), true);
    assert.equal(await page.locator('#modal-raps-cuerpo img').count(), 0);
    assert.ok((await page.locator('#modal-raps-cuerpo').textContent()).includes(payload));
    assert.equal(await page.evaluate(() => Boolean(window.inyeccion)), false);
    await page.evaluate(() => cerrarDetalleRap());
    assert.equal(await page.locator('#modal-detalle-raps').isVisible(), false);
    await page.close();
});

test('el calendario conserva etiquetas y causales como texto sin ejecutar HTML', async () => {
    const hoy = new Date(); const iso = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-01`;
    const payload = '<img src=x onerror=window.inyeccion=true>';
    const records = { [iso]: { etiqueta: payload, estado: 'ASISTE', causal: payload, clase: 'asiste' } };
    const controlador = bloque('app/templates/aprendiz/panel.html', "querySelector('.learner-attendance-calendar')").replace('{{ asistencia_calendario|tojson|safe }}', JSON.stringify(records));
    paginas.set('/calendario', pagina('<section class="learner-attendance-calendar"><button data-learner-calendar-prev>Anterior</button><button data-learner-calendar-next>Siguiente</button><h2 data-learner-calendar-month></h2><div data-learner-calendar-grid></div><p data-learner-calendar-detail></p></section>', controlador));
    const page = await browser.newPage(); await page.goto(`${url}/calendario`);
    assert.equal(await page.locator('[data-learner-calendar-grid] img').count(), 0);
    await page.locator('.learner-calendar-day.is-asiste').click();
    assert.ok((await page.locator('[data-learner-calendar-detail]').textContent()).includes(payload));
    assert.equal(await page.locator('[data-learner-calendar-detail] img').count(), 0);
    assert.equal(await page.evaluate(() => Boolean(window.inyeccion)), false);
    await page.getByRole('button', { name: 'Siguiente' }).click();
    assert.equal(await page.locator('.learner-calendar-day.is-asiste').count(), 0);
    await page.getByRole('button', { name: 'Anterior' }).click();
    assert.equal(await page.locator('.learner-calendar-day.is-asiste').count(), 1);
    await page.close();
});

test('el tema y la búsqueda del dashboard funcionan con almacenamiento bloqueado', async () => {
    const tema = bloque('app/templates/base.html', 'function setTheme');
    const dashboard = bloque('app/templates/instructor/dashboard.html', "getElementById('view-mode-cards')");
    paginas.set('/almacenamiento', pagina('<button id="view-mode-cards">Tarjetas</button><button id="view-mode-compact">Lista</button><div id="dashboard-cards-grid"><article class="card-ficha">Ficha ADSO</article></div><div id="dashboard-compact-view"><div class="compact-ficha-row">Ficha ADSO</div></div><input id="dashboard-ficha-search"><span id="dashboard-result-count"></span><button class="theme-dot" data-theme-btn="ocean" onclick="setTheme(\'ocean\')">Tema océano</button>', tema + dashboard));
    const page = await browser.newPage(); const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    await page.addInitScript(() => Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Almacenamiento bloqueado', 'SecurityError'); } }));
    await page.goto(`${url}/almacenamiento`);
    await page.locator('#dashboard-ficha-search').fill('sin coincidencia');
    assert.equal(await page.locator('.card-ficha').isVisible(), false);
    assert.equal(await page.locator('#dashboard-result-count').textContent(), '0 fichas');
    await page.getByRole('button', { name: 'Lista', exact: true }).click();
    assert.equal(await page.locator('#dashboard-compact-view').evaluate(el => el.classList.contains('is-visible')), true);
    await page.getByRole('button', { name: 'Tema océano' }).click();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'ocean');
    assert.deepEqual(errores, []);
    await page.close();
});

test('los argumentos de botones conservan apóstrofes y nunca se interpretan como código', async () => {
    const nombre = "D'Ávila <img src=x>.png";
    const enlace = "https://github.com/example/repo?q=';window.inyeccion=true;//";
    const materiales = leer('app/templates/instructor/materiales.html').split('\n').filter(linea => linea.includes('<button') && (linea.includes('vistaPrevia(') || linea.includes('confirmarEliminar('))).join('\n');
    const botonesPanel = leer('app/templates/aprendiz/panel.html').split('\n').filter(linea => linea.includes('<button') && linea.includes('enlace_github')).map(linea => linea + 'Copiar</button>').join('\n');
    const botonesHistorial = leer('app/templates/instructor/historial_aprendiz.html').split('\n').filter(linea => linea.includes('<button') && linea.includes('enlace_github')).join('\n');
    const html = render(materiales + botonesPanel + botonesHistorial, { m: { id: 9, nombre_archivo: nombre, url_archivo: 'material.png' }, aprendiz: { enlace_github: enlace } });
    paginas.set('/argumentos', pagina(html, 'window.vistaPrevia=(url,nombre)=>window.recibido=nombre;window.confirmarEliminar=(id,nombre)=>window.recibido=nombre;window.copiarTexto=valor=>window.enlace=valor;'));
    const page = await browser.newPage(); const errores = []; page.on('pageerror', error => errores.push(error.message));
    await page.goto(`${url}/argumentos`);
    await page.getByRole('button', { name: 'Vista Previa' }).click();
    assert.equal(await page.evaluate(() => window.recibido), nombre);
    await page.getByRole('button', { name: 'Eliminar' }).click();
    assert.equal(await page.evaluate(() => window.recibido), nombre);
    for (const boton of await page.getByRole('button', { name: 'Copiar', exact: true }).all()) {
        await boton.click(); assert.equal(await page.evaluate(() => window.enlace), enlace);
    }
    assert.equal(await page.evaluate(() => Boolean(window.inyeccion)), false);
    assert.deepEqual(errores, []);
    await page.close();
});

test('la selección de competencias trata el nombre del instructor como texto', async () => {
    const controlador = bloque('app/templates/instructor/juicios.html', 'const ALL_COMPS').replaceAll('{{ ficha.id }}', '1').replace('`/instructor/fichas/${fichaId}/competencias/toggle`', "'/competencias/toggle'");
    paginas.set('/juicios', pagina('<script id="comp-data" type="application/json">[{"nombre":"Competencia de prueba"}]</script><div id="comp-card-0"><button class="comp-select-btn">Seleccionar</button></div>', controlador));
    const page = await browser.newPage(); await page.goto(`${url}/juicios`);
    await page.evaluate(() => toggleSeleccionCompetencia(1, 'Competencia de prueba', 0));
    await page.waitForFunction(() => document.querySelector('.comp-select-btn').textContent.includes('👤'));
    assert.equal(await page.locator('.comp-select-btn img').count(), 0);
    assert.ok((await page.locator('.comp-select-btn').textContent()).includes('<img src=x'));
    assert.equal(await page.evaluate(() => Boolean(window.inyeccion)), false);
    await page.close();
});

test('las advertencias de importación permanecen visibles hasta que el usuario actualiza', async () => {
    respuestaImportacion = { estado: 'completado', resultado: { nuevos: 2, advertencias: ['Los indicadores están pendientes.', '<img src=x onerror=window.inyeccion=true>'] } };
    for (const archivo of ['aprendices', 'juicios']) {
        assert.ok(leer(`app/templates/instructor/${archivo}.html`).includes("filename='js/importaciones.js'"));
    }
    paginas.set('/importacion?importacion_id=3', pagina('<div id="import-status" data-status-url="/import-job" aria-busy="true"><p id="import-status-message" role="status">Consultando</p></div>') + '<script src="/importaciones.js"></script>');
    const page = await browser.newPage(); await page.goto(`${url}/importacion?importacion_id=3`);
    await page.waitForFunction(() => document.querySelector('#import-status-message').getAttribute('role') === 'alert');
    assert.match(await page.getByRole('alert').textContent(), /2 aprendices nuevos.*indicadores están pendientes/);
    assert.equal(await page.locator('#import-status img').count(), 0);
    assert.equal(await page.locator('#import-status').getAttribute('aria-busy'), 'false');
    await page.waitForTimeout(1300);
    assert.equal(page.url(), `${url}/importacion?importacion_id=3`);
    await page.getByRole('button', { name: 'Actualizar vista' }).click();
    await page.waitForURL(`${url}/importacion`);
    await page.close();
});

test('la consulta de importación detecta la redirección real al ingreso y detiene los reintentos', async () => {
    paginas.set('/auth/login', pagina('<form class="auth-form"><input type="password" name="password"><button>Ingresar</button></form>'));
    paginas.set('/importacion-redir?importacion_id=4', pagina('<div id="import-status" data-status-url="/import-job-redirect" aria-busy="true"><p id="import-status-message" role="status">Consultando</p></div>') + '<script src="/importaciones.js"></script>');
    const page = await browser.newPage();
    const redireccion = page.waitForResponse(respuesta => respuesta.url().endsWith('/auth/login'));
    await page.goto(`${url}/importacion-redir?importacion_id=4`);
    const ingreso = await redireccion;
    assert.equal(ingreso.status(), 200);
    assert.equal(ingreso.request().redirectedFrom().url(), `${url}/import-job-redirect`);
    await page.getByRole('alert').waitFor();
    assert.match(await page.getByRole('alert').textContent(), /sesión/i);
    assert.equal(await page.getByRole('button', { name: 'Actualizar vista' }).isVisible(), true);
    assert.equal(await page.getByRole('button', { name: 'Volver a consultar' }).isVisible(), false);
    assert.equal(await page.locator('#import-status').getAttribute('aria-busy'), 'false');
    assert.equal(page.url(), `${url}/importacion-redir?importacion_id=4`);
    await page.getByRole('button', { name: 'Actualizar vista' }).click();
    await page.waitForURL(`${url}/importacion-redir`);
    await page.close();
});

test('el chat conserva el borrador hasta recibir confirmación del mensaje guardado', async () => {
    respuestaChat = {};
    paginas.set('/chat', pagina('<section data-grupo-chat data-chat-url="/chat-mensajes"><div data-chat-messages><p data-chat-empty></p></div><form data-chat-form><input type="hidden" name="csrf_token" value="example"><textarea data-chat-input></textarea><span data-chat-count></span><button data-chat-submit>Enviar</button></form><p data-chat-status role="status">Consultando</p></section>') + '<script src="/grupo_chat.js"></script>');
    const page = await browser.newPage();
    const lectura = page.waitForResponse(respuesta => respuesta.url().endsWith('/chat-mensajes'));
    await page.goto(`${url}/chat`); await lectura;
    await page.locator('textarea').fill('Mi mensaje pendiente');
    await page.getByRole('button', { name: 'Enviar' }).click();
    await page.waitForFunction(() => document.querySelector('[data-chat-submit]').disabled === false);
    assert.equal(await page.locator('textarea').inputValue(), 'Mi mensaje pendiente');
    assert.match(await page.locator('[data-chat-status]').textContent(), /confirmar/);
    respuestaChat = { message: { id: 1, contenido: 'Mi mensaje pendiente', propio: true } };
    await page.getByRole('button', { name: 'Enviar' }).click();
    await page.waitForFunction(() => document.querySelector('[data-chat-status]').textContent === 'Mensaje enviado.');
    assert.equal(await page.locator('textarea').inputValue(), '');
    assert.equal(await page.locator('.learner-group-chat-message').count(), 1);
    await page.close();
});

test('la cobertura de horas no presenta cien por ciento cuando falta una referencia', async () => {
    const fuente = leer('app/templates/instructor/planeacion.html');
    const calculo = fuente.slice(fuente.indexOf('// Métricas resumidas gráficas'), fuente.indexOf('// Conteo en badges de pestañas'));
    paginas.set('/horas', pagina('<div id="metricas"></div>', 'window.renderMetricas=function(dato){const metricsBar=document.getElementById("metricas");' + calculo + '};'));
    const page = await browser.newPage(); await page.goto(`${url}/horas`);
    await page.evaluate(() => renderMetricas({ horas_programa: 0, horas_planeadas: 0 }));
    const caja = page.locator('.pl-metric-box').first();
    assert.match(await caja.textContent(), /referencia|no disponible/i);
    assert.doesNotMatch(await caja.textContent(), /100%/);
    assert.equal(await caja.locator('.pl-progress-mini-bar').evaluate(el => el.style.width), '0%');
    await page.evaluate(() => renderMetricas({ horas_programa: 40, horas_planeadas: 20 }));
    assert.match(await caja.textContent(), /50%/);
    assert.equal(await caja.locator('.pl-progress-mini-bar').evaluate(el => el.style.width), '50%');
    await page.close();
});

test('un solo registro de rendimiento no se presenta como una tendencia estable', async () => {
    const fuente = leer('app/templates/aprendiz/panel.html');
    const inicio = fuente.indexOf('<div class="learner-curve-badges">');
    const fragmento = fuente.slice(inicio, fuente.indexOf('</div>', inicio) + 6);
    const curva = { badge_class: 'badge-info', nivel_desempeno: 'Básico', puntos: [{}], tendencia_clase: 'neutral', tendencia_icono: '→', tendencia: 'estable', diferencia_ultimo: 0 };
    paginas.set('/curva-uno', pagina(render(fragmento, { curva_rendimiento: curva })));
    paginas.set('/curva-dos', pagina(render(fragmento, { curva_rendimiento: { ...curva, puntos: [{}, {}] } })));
    const page = await browser.newPage(); await page.goto(`${url}/curva-uno`);
    assert.match(await page.locator('.trend-chip').textContent(), /Primer registro/);
    assert.doesNotMatch(await page.locator('.trend-chip').textContent(), /Estable/);
    await page.goto(`${url}/curva-dos`);
    assert.match(await page.locator('.trend-chip').textContent(), /Estable/);
    await page.close();
});
