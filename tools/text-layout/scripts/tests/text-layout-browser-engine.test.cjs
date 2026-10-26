const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {
  DEFAULT_VIEWPORTS,
  CDPClient,
  createAuditExpression,
  createStressExpression,
  discoverIndexPages,
  resolveTemplateAssets,
  getJson,
  main,
  reportCliError,
  resolveEdgePath,
  runFromCommandLine,
  runBrowserAudit,
  setProcessExitCode,
  waitForPage,
  waitForTarget
} = require('../text-layout-browser-audit.cjs');

test('el contrato distingue región estrecha en pantalla amplia y detecta límites heredados', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'prose-regions-'));
  try {
    const dir = path.join(root, '_projects', 'fixture');
    fs.mkdirSync(dir, { recursive: true });
    const css = fs.readFileSync(path.join(__dirname, '../../templates/prose-layout.css'), 'utf8');
    fs.writeFileSync(path.join(dir, 'index.html'), `<!doctype html><html><style>body{margin:0}main{width:100%}.small{width:300px}.limited{max-width:78ch}.full{max-width:100%;margin-inline:48px} ${css}</style><main><p class="wide">Texto amplio para comprobar su alineación.</p><section class="small"><p>Tarjeta estrecha.</p></section><section class="limited"><p>Límite heredado.</p></section><section class="full"><p>Full container.</p></section></main><script>${fs.readFileSync(path.join(__dirname,'../../templates/prose-layout.js'),'utf8')}</script></html>`);
    const report = await runBrowserAudit(root, {viewports:[{label:'1440px',width:1440}],probeSelectors:['.wide','.small p'],renderDelayMs:20});
    const probes = report.pages[0].viewports[0].probes;
    assert.equal(probes['.wide'][0].textAlign, 'justify');
    assert.equal(probes['.small p'][0].textAlign, 'start');
    assert.equal(report.findings.some(item=>item.rule === 'text-justification'), false);
    assert.equal(report.findings.some(item=>item.rule === 'unused-region-width'), true);
    assert.equal(report.findings.some(item=>item.rule === 'unused-region-width' && item.text === 'Full container.'), false);
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});

test('trata el ancho acotado de una ventana de diálogo como una región propia', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'prose-dialog-'));
  try {
    const dir = path.join(root, '_projects', 'fixture');
    fs.mkdirSync(dir, { recursive: true });
    const css = fs.readFileSync(path.join(__dirname, '../../templates/prose-layout.css'), 'utf8');
    const runtime = fs.readFileSync(path.join(__dirname, '../../templates/prose-layout.js'), 'utf8');
    fs.writeFileSync(path.join(dir, 'index.html'), `<!doctype html><html><style>body{margin:0}main{width:100%}.device-inspection-shell{width:100%;max-width:56rem;margin:auto}${css}</style><main><dialog open><section class="device-inspection-shell"><p>Texto dentro de una ventana de inspección.</p></section></dialog></main><script>${runtime}</script></html>`);
    const report = await runBrowserAudit(root, { viewports: [{ label: '1440px', width: 1440 }], renderDelayMs: 20 });
    assert.equal(report.findings.some(item => item.rule === 'unused-region-width' && item.text === 'Texto dentro de una ventana de inspección.'), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('descubre páginas mantenidas e ignora dependencias y carpetas generadas', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'text-layout-pages-'));
  try {
    const allowed = path.join(root, '_projects', 'guide', 'index.html');
    const uppercase = path.join(root, '_library', 'reference', 'Index.HTML');
    const dependency = path.join(root, '_projects', 'guide', 'node_modules', 'sample', 'index.html');
    const generated = path.join(root, '_projects', 'guide', 'playwright-report', 'index.html');
    const targetOutput = path.join(root, '_projects', 'guide', 'target', 'site', 'index.html');
    const serverTemplate = path.join(root, '_projects', 'server-app', 'templates', 'index.html');
    const moduleEntry = path.join(root, '_projects', 'vite-app', 'index.html');
    const nativeModuleEntry = path.join(root, '_projects', 'native-module-app', 'index.html');
    const styledModuleEntry = path.join(root, '_projects', 'vite-styled-app', 'index.html');
    const rootStyledModuleEntry = path.join(root, '_projects', 'vite-root-styled-app', 'index.html');
    const vitePackage = path.join(root, '_projects', 'vite-app', 'package.json');
    const viteStyledPackage = path.join(root, '_projects', 'vite-styled-app', 'package.json');
    const viteRootStyledPackage = path.join(root, '_projects', 'vite-root-styled-app', 'package.json');
    const viteNestedPackage = path.join(root, '_projects', 'vite-app', 'nested', 'package.json');
    const viteNestedEntry = path.join(root, '_projects', 'vite-app', 'nested', 'index.html');
    const hidden = path.join(root, '_projects', '.codex', 'index.html');
    const archived = path.join(root, '_projects', 'guide', 'archive', 'index.html');
    for (const file of [allowed, uppercase, dependency, generated, targetOutput, serverTemplate, moduleEntry, nativeModuleEntry, styledModuleEntry, rootStyledModuleEntry, viteNestedEntry, hidden, archived]) {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, file === serverTemplate
        ? "{% extends 'base.html' %}{% block content %}<main>Rendered by the application</main>{% endblock %}"
        : file === styledModuleEntry
          ? '<!doctype html><html><head><link rel="stylesheet" href="src/styles.css"><script type="module" src="/src/main.js"></script></head><body><main>Vite source entry with linked styles</main></body></html>'
        : file === rootStyledModuleEntry
          ? '<!doctype html><html><head><link rel="stylesheet" href="/src/styles.css"><script type="module" src="/src/main.js"></script></head><body><main>Vite source entry with root styles</main></body></html>'
        : [moduleEntry, nativeModuleEntry, viteNestedEntry].includes(file)
          ? '<!doctype html><html><head><script type="module" src="/src/main.js"></script></head><body><main>Module source entry</main></body></html>'
        : '<!doctype html><title>fixture</title>');
    }
    fs.writeFileSync(vitePackage, JSON.stringify({ devDependencies: { vite: '^6.0.0' } }));
    fs.writeFileSync(viteNestedPackage, '{ malformed: json');
    fs.writeFileSync(viteStyledPackage, JSON.stringify({ devDependencies: { vite: '^6.0.0' } }));
    fs.writeFileSync(viteRootStyledPackage, JSON.stringify({ devDependencies: { vite: '^6.0.0' } }));
    fs.mkdirSync(path.dirname(path.join(path.dirname(styledModuleEntry), 'src/styles.css')), { recursive: true });
    fs.writeFileSync(path.join(path.dirname(styledModuleEntry), 'src/styles.css'), 'main { inline-size: 100%; }');
    fs.mkdirSync(path.join(path.dirname(rootStyledModuleEntry), 'src'), { recursive: true });
    fs.writeFileSync(path.join(path.dirname(rootStyledModuleEntry), 'src/styles.css'), 'main { inline-size: 100%; }');

    assert.deepEqual(discoverIndexPages(root), [allowed, nativeModuleEntry, styledModuleEntry, uppercase].sort((left, right) => left.localeCompare(right)));
    assert.equal(discoverIndexPages(root).includes(moduleEntry), false, 'las entradas de Vite requieren el servidor para cargar sus recursos');
    assert.equal(discoverIndexPages(root).includes(rootStyledModuleEntry), false, 'los estilos root-relative de Vite no funcionan en file://');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('resuelve recursos locales de prosa en plantillas Flask sin iniciar el servidor', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'text-layout-template-assets-'));
  try {
    const app = path.join(root, '_projects', 'server-app');
    const templateDirectory = path.join(app, 'templates');
    const staticCss = path.join(app, 'static', 'css', 'devbrain-prose.css');
    const staticJs = path.join(app, 'static', 'js', 'devbrain-prose.js');
    const page = path.join(templateDirectory, 'index.html');
    fs.mkdirSync(templateDirectory, { recursive: true });
    fs.mkdirSync(path.dirname(staticCss), { recursive: true });
    fs.mkdirSync(path.dirname(staticJs), { recursive: true });
    fs.writeFileSync(staticCss, fs.readFileSync(path.join(__dirname, '../../templates/prose-layout.css'), 'utf8'));
    fs.writeFileSync(staticJs, fs.readFileSync(path.join(__dirname, '../../templates/prose-layout.js'), 'utf8'));
    fs.writeFileSync(page, `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" data-devbrain-prose href="{{ url_for('static', filename='css/devbrain-prose.css') }}"><script data-devbrain-prose-runtime src="{{ url_for('static', filename='js/devbrain-prose.js') }}"></script></head><body><main><p>Texto de una página de servidor cuyo recurso aún no está renderizado.</p></main></body></html>`);

    const assets = resolveTemplateAssets(page, root);
    assert.deepEqual(assets.styles.map(item => item.path), [staticCss]);
    assert.deepEqual(assets.scripts.map(item => item.path), [staticJs]);
    assert.match(assets.styles[0].content, /--text-align-reading/);
    assert.match(assets.scripts[0].content, /ResizeObserver/);

    const browserReport = await runBrowserAudit(root, {
      scopes: ['_projects/server-app'],
      viewports: [{ label: '1440px', width: 1440 }],
      probeSelectors: ['p'],
      renderDelayMs: 20
    });
    assert.equal(browserReport.pagesScanned, 1);
    assert.equal(browserReport.pages[0].viewports[0].probes.p[0].textAlign, 'justify');
    assert.equal(browserReport.findings.length, 0);

    const ordinaryPage = path.join(templateDirectory, 'ordinary.html');
    fs.writeFileSync(ordinaryPage, '<!doctype html><p>Texto.</p>');
    assert.deepEqual(resolveTemplateAssets(ordinaryPage, root), { styles: [], scripts: [] });
    fs.writeFileSync(page, `<link data-devbrain-prose href="{{ url_for('static', filename='css/missing.css') }}">`);
    assert.deepEqual(resolveTemplateAssets(page, root), { styles: [], scripts: [] });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('resuelve recursos locales de prosa en proyectos Vite y plantillas Django', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'text-layout-vite-assets-'));
  try {
    const viteApp = path.join(root, '_projects', 'vite-app');
    const vitePackage = path.join(viteApp, 'package.json');
    const publicCss = path.join(viteApp, 'public', 'css', 'prose.css');
    const publicJs = path.join(viteApp, 'public', 'js', 'prose.js');
    const publicFallback = path.join(viteApp, 'public', 'fallback.css');
    const localCss = path.join(viteApp, 'src', 'local.css');
    const rootCss = path.join(root, 'workspace-root.css');
    const staticDjangoCss = path.join(root, '_projects', 'django-app', 'static', 'django.css');
    const djangoPage = path.join(root, '_projects', 'django-app', 'templates', 'index.html');

    fs.mkdirSync(path.dirname(publicCss), { recursive: true });
    fs.mkdirSync(path.dirname(publicJs), { recursive: true });
    fs.mkdirSync(path.dirname(localCss), { recursive: true });
    fs.mkdirSync(path.dirname(staticDjangoCss), { recursive: true });
    fs.mkdirSync(path.dirname(djangoPage), { recursive: true });

    fs.writeFileSync(vitePackage, JSON.stringify({ devDependencies: { vite: '^6.0.0' } }));
    fs.writeFileSync(publicCss, 'p { inline-size: 100%; }');
    fs.writeFileSync(publicJs, 'console.log("prose runtime");');
    fs.writeFileSync(publicFallback, 'p { text-align: justify; }');
    fs.writeFileSync(localCss, 'p { color: inherit; }');
    fs.writeFileSync(rootCss, 'main { display: block; }');
    fs.writeFileSync(staticDjangoCss, 'body { margin: 0; }');

    const vitePage = path.join(viteApp, 'src', 'index.html');
    fs.writeFileSync(vitePage, `<!doctype html><html><head>
      <link rel="stylesheet" data-devbrain-prose href="/css/prose.css">
      <script data-devbrain-prose-runtime src="/js/prose.js"></script>
      <link rel="stylesheet" data-devbrain-prose href="local.css">
      <link rel="stylesheet" data-devbrain-prose href="fallback.css">
      <link rel="stylesheet" data-devbrain-prose href="/workspace-root.css">
      <link rel="stylesheet" data-devbrain-prose href="#">
      <link rel="stylesheet" data-devbrain-prose href="">
    </head><body><p>Vite test</p></body></html>`);

    const assets = resolveTemplateAssets(vitePage, root);
    assert.deepEqual(assets.styles.map(item => item.path), [
      publicCss,
      localCss,
      publicFallback,
      rootCss
    ]);
    assert.deepEqual(assets.scripts.map(item => item.path), [publicJs]);

    fs.writeFileSync(djangoPage, `<!doctype html><html><head>
      <link rel="stylesheet" data-devbrain-prose href="{% static 'django.css' %}">
    </head><body><p>Django test</p></body></html>`);
    const djangoAssets = resolveTemplateAssets(djangoPage, root);
    assert.deepEqual(djangoAssets.styles.map(item => item.path), [staticDjangoCss]);

    const brokenDir = path.join(root, '_projects', 'broken-app');
    const brokenPage = path.join(brokenDir, 'index.html');
    fs.mkdirSync(brokenDir, { recursive: true });
    fs.writeFileSync(path.join(brokenDir, 'package.json'), '{ malformed json');
    fs.writeFileSync(brokenPage, `<!doctype html><link rel="stylesheet" data-devbrain-prose href="/missing.css">`);
    const brokenAssets = resolveTemplateAssets(brokenPage, root);
    assert.deepEqual(brokenAssets.styles, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('crea sondas de texto, limita la carga de ejemplo y resuelve Edge', () => {
  assert.match(createStressExpression(0), /phrase\.repeat\(1\)/);
  assert.match(createStressExpression(99), /phrase\.repeat\(20\)/);
  assert.match(createAuditExpression(), /content-clipping/);
  assert.match(createAuditExpression(['.column']), /gridTemplateColumns/);
  assert.match(createAuditExpression(), /page-overflow/);
  assert.match(createAuditExpression(), /const viewportWidth = window\.innerWidth \|\| document\.documentElement\.clientWidth/);
  assert.match(createAuditExpression(['@overflow']), /rightRect\.right - viewportWidth/);
  assert.deepEqual(DEFAULT_VIEWPORTS.map(viewport => viewport.width), [320, 390, 768, 1440, 1920, 2560, 720]);
  assert.equal(DEFAULT_VIEWPORTS.at(-1).zoom, 200);
  assert.ok(resolveEdgePath());
  assert.equal(resolveEdgePath(path.join(os.tmpdir(), 'edge-not-installed.exe')), null);
});

test('los lectores HTTP informan respuestas dañadas, agotamiento y puertos sin Edge', async () => {
  const invalidJsonServer = http.createServer((_request, response) => response.end('{'));
  await new Promise(resolve => invalidJsonServer.listen(0, '127.0.0.1', resolve));
  const invalidJsonUrl = `http://127.0.0.1:${invalidJsonServer.address().port}/invalid`;
  try {
    await assert.rejects(getJson(invalidJsonUrl), SyntaxError);
  } finally {
    await new Promise(resolve => invalidJsonServer.close(resolve));
  }

  const stalledServer = http.createServer(() => {});
  await new Promise(resolve => stalledServer.listen(0, '127.0.0.1', resolve));
  const stalledUrl = `http://127.0.0.1:${stalledServer.address().port}/stalled`;
  try {
    await assert.rejects(getJson(stalledUrl, 20), /Timeout al consultar/);
  } finally {
    await new Promise(resolve => stalledServer.close(resolve));
  }
  await assert.rejects(waitForTarget(0, 1), /Microsoft Edge no abrió/);
  await assert.rejects(waitForPage({ evaluate: async () => 'loading' }, 1), /La página no terminó de cargar/);
});

test('CDP procesa respuestas reales y errores de protocolo y de tiempo límite', async () => {
  const originalWebSocket = globalThis.WebSocket;
  let behavior = 'success';
  class FakeWebSocket extends EventTarget {
    constructor() {
      super();
      queueMicrotask(() => this.dispatchEvent(new Event('open')));
    }

    send(serialized) {
      if (behavior === 'silent') return;
      const request = JSON.parse(serialized);
      const response = behavior === 'error'
        ? { id: request.id, error: { message: 'Error CDP esperado' } }
        : { id: request.id, result: { result: { value: 42 } } };
      queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(response) })));
    }

    close() {}
  }

  globalThis.WebSocket = FakeWebSocket;
  try {
    const successful = new CDPClient('ws://fixture', 15);
    assert.equal(await successful.evaluate('6 * 7'), 42);
    successful.close();

    behavior = 'error';
    const rejected = new CDPClient('ws://fixture', 15);
    await assert.rejects(rejected.send('Invalid.method'), /Error CDP esperado/);
    rejected.close();

    behavior = 'silent';
    const timedOut = new CDPClient('ws://fixture', 10);
    await assert.rejects(timedOut.send('No.response'), /CDP no respondió/);
    timedOut.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test('Edge detecta recortes reales de contenido extenso y valida anchos móviles y zoom', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'text-layout-browser-'));
  const goodPage = path.join(root, '_projects', 'good', 'index.html');
  const badPage = path.join(root, '_projects', 'bad', 'index.html');
  try {
    fs.mkdirSync(path.dirname(goodPage), { recursive: true });
    fs.mkdirSync(path.dirname(badPage), { recursive: true });
    fs.writeFileSync(goodPage, '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0}.column{width:100%;max-width:100%;padding:12px;box-sizing:border-box}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:32px}@media(max-width:768px){.grid{grid-template-columns:1fr}}.dbc{overflow:hidden}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.hidden-copy{opacity:0;max-height:1px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}p{width:100%;margin:0;white-space:normal;word-break:normal;overflow-wrap:break-word}</style></head><body><main class="column"><div class="grid"></div><p>Texto base.</p><figure class="dbc"><p>Texto técnico que se conserva en el bloque de código.</p></figure><p class="hidden-copy">Contenido de un panel inactivo que no está visible.</p><label class="sr-only">Etiqueta para lectores de pantalla</label></main></body></html>');
    fs.writeFileSync(badPage, '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0}.column{width:100%;padding:12px;box-sizing:border-box}.bad-copy{height:1.5em;max-height:1.5em;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}</style></head><body><main class="column"><p class="bad-copy">Texto base.</p></main></body></html>');

    fs.appendFileSync(goodPage, '<style>'+fs.readFileSync(path.join(__dirname,'../../templates/prose-layout.css'),'utf8')+'</style><script>'+fs.readFileSync(path.join(__dirname,'../../templates/prose-layout.js'),'utf8')+'</script>');
    const report = await runBrowserAudit(root, {
      scopes: ['_projects'],
      viewports: [{ label: '320px', width: 320 }, { label: '200% zoom', width: 720, zoom: 200 }],
      probeSelectors: ['.column', '.grid', '@overflow'],
      renderDelayMs: 20,
      progress: true
    });

    assert.equal(report.pagesScanned, 2);
    assert.equal(report.viewportsChecked, 4);
    assert.equal(report.findings.filter(item => item.page.endsWith('/good/index.html')).length, 0);
    const goodPageResult = report.pages.find(page => page.page.endsWith('/good/index.html'));
    assert.equal(goodPageResult.viewports[0].viewportWidth, 320);
    assert.equal(goodPageResult.viewports[1].viewportWidth, 720);
    assert.equal(goodPageResult.viewports[0].probes['.column'][0].width, 320);
    assert.equal(goodPageResult.viewports[0].probes['.grid'][0].gridTemplateColumns.trim().split(/\s+/).length, 1);
    assert.equal(goodPageResult.viewports[0].probes['@overflow'].length, 0);
    const badPageResult = report.pages.find(page => page.page.endsWith('/bad/index.html'));
    const overflowingCopy = badPageResult.viewports[0].probes['@overflow'].find(item => item.selector === 'p.bad-copy');
    assert.ok(overflowingCopy, 'la sonda debe identificar el bloque que rebasa el ancho de su contenedor');
    assert.match(overflowingCopy.text, /Texto base\./, 'la sonda debe incluir una muestra para localizar el contenido afectado');
    assert.ok(overflowingCopy.ancestors.some(item => item.selector === 'main.column'), 'la sonda debe mostrar la cadena de contenedores del bloque');
    assert.ok(report.findings.some(item => item.page.endsWith('/bad/index.html') && item.rule === 'content-truncation'));
    assert.ok(report.findings.some(item => item.page.endsWith('/bad/index.html') && item.rule === 'content-no-wrap'));
    assert.equal(await main(['--root', root], {
      scopes: ['_projects'],
      viewports: [{ label: '320px', width: 320 }],
      renderDelayMs: 20,
      progress: false
    }), 1);
    await assert.rejects(runBrowserAudit(root, { scopes: ['_projects'], edgePath: path.join(root, 'missing-edge.exe') }), /No se encontró Microsoft Edge/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('main genera un informe JSON vacío cuando el alcance no tiene páginas', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'text-layout-empty-'));
  try {
    assert.equal(await main(['--root', root, '--json']), 0);
    const oldExitCode = process.exitCode;
    const oldError = console.error;
    let reported = '';
    try {
      console.error = message => { reported = message; };
      reportCliError(new Error('falla recuperable'));
      assert.equal(process.exitCode, 1);
      assert.equal(reported, 'falla recuperable');
      setProcessExitCode(2);
      assert.equal(process.exitCode, 2);
    } finally {
      console.error = oldError;
      process.exitCode = oldExitCode;
    }
    assert.equal(await main([], { scopes: ['_no-pages'] }), 0);
    await runFromCommandLine(['--root', root]);
    assert.equal(process.exitCode, 0);

    const invalidRoot = path.join(root, 'with-page');
    const indexPage = path.join(invalidRoot, '_projects', 'sample', 'index.html');
    fs.mkdirSync(path.dirname(indexPage), { recursive: true });
    fs.writeFileSync(indexPage, '<!doctype html><title>test</title>');
    let cliError = '';
    const currentError = console.error;
    const currentExitCode = process.exitCode;
    try {
      console.error = message => { cliError = message; };
      await runFromCommandLine(['--root', invalidRoot], {
        scopes: ['_projects'],
        edgePath: path.join(root, 'missing-edge.exe')
      });
      assert.equal(process.exitCode, 1);
      assert.match(cliError, /No se encontró Microsoft Edge/);
    } finally {
      console.error = currentError;
      process.exitCode = currentExitCode;
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
