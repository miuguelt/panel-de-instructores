import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  isNaturalTextSelector,
  isReadingRegionSelector,
  parseCssDeclarations,
  extractCssRules,
  scanStylesheet,
  scanWorkspace,
  parseArguments,
  formatReport,
  stripComments,
  runAudit,
} from '../text-layout-audit.mjs';

test('clasifica prosa y excluye controles y bloques técnicos', () => {
  assert.equal(isNaturalTextSelector('.card > p'), true);
  assert.equal(isNaturalTextSelector('.module-description'), true);
  assert.equal(isNaturalTextSelector('.tool-lab-heading'), true);
  assert.equal(isNaturalTextSelector('#pageTitle'), true);
  assert.equal(isNaturalTextSelector('.topbar #content-title'), true);
  assert.equal(isNaturalTextSelector('.article h2'), true);
  assert.equal(isNaturalTextSelector('.button, .badge'), false);
  assert.equal(isNaturalTextSelector('.ai-guided-card-heading .btn'), false);
  assert.equal(isNaturalTextSelector('.icon-heading'), false);
  assert.equal(isNaturalTextSelector('pre code'), false);
  assert.equal(isNaturalTextSelector('.article p code'), false);
  assert.equal(isNaturalTextSelector('.article :is(p, li)'), true);
  assert.deepEqual(scanStylesheet('#pageTitle { white-space: nowrap; }', 'app.css').findings.map(item => item.rule), ['content-no-wrap']);
});

test('quita comentarios CSS sin cambiar posiciones de línea', () => {
  const source = 'p { color:red; } /* nota\nextendida */\n.copy { color:blue; }';
  const cleaned = stripComments(source);
  assert.doesNotMatch(cleaned, /nota|extendida/);
  assert.equal(cleaned.split('\n').length, source.split('\n').length);
});

test('lee declaraciones sin partir valores con funciones o cadenas', () => {
  assert.deepEqual(parseCssDeclarations('max-width: min(100%, 78ch); content: "a;b";'), {
    'max-width': 'min(100%, 78ch)',
    content: '"a;b"',
  });
});

test('extrae selectores dentro de media y container queries con sus líneas', () => {
  const source = '@media (min-width: 60rem) {\n  .article p {\n    max-width: 50ch;\n  }\n}';
  const rules = extractCssRules(source);
  assert.equal(rules.length, 1);
  assert.equal(rules[0].selector, '.article p');
  assert.equal(rules[0].line, 2);
  assert.equal(rules[0].declarations['max-width'], '50ch');
  assert.equal(source.slice(rules[0].bodyStart, rules[0].bodyEnd).trim(), 'max-width: 50ch;');
});

test('detecta recorte, no-wrap, división forzada, justificación y medida estrecha', () => {
  const source = [
    '.copy p { text-overflow: ellipsis; white-space: nowrap; word-break: break-all; text-align: justify; max-width: 48ch; }',
  ].join('\n');
  const report = scanStylesheet(source, 'app.css');
  assert.deepEqual(report.findings.map(item => item.rule).sort(), [
    'content-no-wrap',
    'content-truncation',
    'forced-word-break',
    'narrow-prose-measure',
  ]);
  assert.ok(report.findings.some(item => item.property === 'word-break' && item.value === 'break-all'));
});

test('distingue la medida de un párrafo de la jerarquía de un título', () => {
  const report = scanStylesheet('.copy p { width: 70%; } .hero h2 { max-width: 32ch; }', 'app.css');
  assert.deepEqual(report.findings.map(item => item.rule), ['narrow-prose-width']);
});

test('detecta topes heredables y columnas estrechas en regiones de lectura', () => {
  assert.equal(isReadingRegionSelector('.module-explanation'), true);
  assert.equal(isReadingRegionSelector('.hero h2'), false);
  assert.equal(isReadingRegionSelector('.search-container'), false);
  assert.equal(isReadingRegionSelector('.hero-image-wrapper'), false);
  assert.equal(isReadingRegionSelector('.step-content .code-window'), false);
  assert.equal(isReadingRegionSelector('#toast-container'), false);
  const report = scanStylesheet('.timeline { max-width: 72ch; } .module-explanation { grid-template-columns: minmax(0, 78ch) minmax(16rem, 1fr); }', 'app.css');
  assert.deepEqual(report.findings.map(item => item.rule).sort(), ['narrow-reading-column', 'narrow-reading-region']);
  assert.equal(scanStylesheet('.step-content .code-window { max-width: calc(100% + 56px); } #toast-container { max-width: calc(100vw - 24px); }', 'app.css').findings.length, 0);
});

test('detecta división forzada heredada desde una región de lectura', () => {
  const report = scanStylesheet('.document-content { overflow-wrap: anywhere; word-break: break-all; white-space: nowrap; }', 'document.css');
  assert.deepEqual(report.findings.map(item=>item.rule), ['content-no-wrap','forced-word-break','forced-word-break']);
});

test('detecta truncamiento y recorte aplicados a un elemento que contiene texto', () => {
  const report = scanStylesheet('.ficha-context strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; height: 1rem; }', 'ficha.css');
  assert.deepEqual(report.findings.map(item=>item.rule), ['content-truncation','content-no-wrap','content-clipping']);
});

test('no confunde regiones decorativas ni estados colapsados con prosa recortada', () => {
  const source = [
    '.carousel-image-container { height: 0; overflow: hidden; }',
    '.quality-bar-container { height: 8px; overflow: hidden; }',
    '.particles-container { position: fixed; overflow: clip; }',
    '.module-content { max-height: 0; overflow: hidden; transition: max-height .5s; }',
    '.page-section { display: none !important; max-height: 0; overflow: hidden; }',
  ].join('\n');
  assert.deepEqual(scanStylesheet(source, 'decorative.css').findings, []);
});

test('mantiene auditables las regiones de lectura con desplazamiento necesario', () => {
  const report = scanStylesheet('.modal-content { max-height: 90vh; overflow: hidden; }', 'modal.css');
  assert.deepEqual(report.findings.map(item=>item.rule), ['content-clipping']);
});

test('excluye botones, marcadores y etiquetas compactas de la detección heredada', () => {
  for (const selector of ['.reading-time-badge','.timeline-marker','.nav-context-btn-back','.kit-copy-btn','.xp-text','.page-switcher-link','.guided-case-done']) {
    assert.equal(isReadingRegionSelector(selector),false,selector);
  }
  assert.deepEqual(scanStylesheet('.reading-time-badge{white-space:nowrap}.nav-context-btn-back{white-space:nowrap}','controls.css').findings,[]);
});

test('permite el quiebre de respaldo para tokens largos y detecta word-break o anywhere', () => {
  const safeFallback = scanStylesheet('.copy p { overflow-wrap: break-word; }', 'app.css');
  const forcedAnywhere = scanStylesheet('.copy p { overflow-wrap: anywhere; }', 'app.css');
  assert.equal(safeFallback.findings.length, 0);
  assert.equal(forcedAnywhere.findings[0].rule, 'forced-word-break');
});

test('detecta anywhere heredado desde el contenedor de un encabezado natural', () => {
  const report = scanStylesheet('.tool-lab-heading { overflow-wrap: anywhere; }', 'app.css');
  assert.equal(report.findings.length, 1);
  assert.equal(report.findings[0].rule, 'forced-word-break');
});

test('acepta excepciones CSS declaradas con motivo junto al selector', () => {
  const source = '/* text-layout-exception: etiqueta compacta con valor completo accesible */\n.copy p { white-space: nowrap; }';
  const report = scanStylesheet(source, 'app.css');
  assert.equal(report.findings.length, 0);
  assert.equal(report.exceptions.length, 1);
});

test('ubica comentarios de excepción dentro de consultas CSS anidadas', () => {
  const source = '@container card (min-width: 40rem) {\n  /* text-layout-exception: etiqueta compacta consultable en el detalle */\n  .copy p { white-space: nowrap; }\n}';
  const report = scanStylesheet(source, 'app.css');
  assert.equal(report.findings.length, 0);
  assert.equal(report.exceptions.length, 1);
  assert.match(report.exceptions[0].reason, /consultable en el detalle/);
});

test('escanea carpetas mantenidas y excluye dependencias y archivos generados', () => {
  const root = mkdtempSync(join(tmpdir(), 'text-layout-'));
  try {
    mkdirSync(join(root, '_projects', 'demo', 'node_modules'), { recursive: true });
    mkdirSync(join(root, '_projects', 'demo', 'htmlcov'), { recursive: true });
    mkdirSync(join(root, '_projects', 'demo', 'test-results'), { recursive: true });
    mkdirSync(join(root, '_projects', 'demo', 'artifacts'), { recursive: true });
    mkdirSync(join(root, '_projects', 'demo', 'target', 'site'), { recursive: true });
    mkdirSync(join(root, '_projects', 'demo', 'assets'), { recursive: true });
    mkdirSync(join(root, '_projects', 'demo', '.agents'), { recursive: true });
    mkdirSync(join(root, '_library', 'demo', 'archive'), { recursive: true });
    mkdirSync(join(root, '_library', 'demo'), { recursive: true });
    writeFileSync(join(root, '_projects', 'demo', 'style.css'), '.copy p { max-width: 50ch; }');
    writeFileSync(join(root, '_projects', 'demo', 'node_modules', 'third-party.css'), '.copy p { max-width: 20ch; }');
    writeFileSync(join(root, '_projects', 'demo', 'htmlcov', 'coverage.css'), '.copy p { text-overflow: ellipsis; }');
    writeFileSync(join(root, '_projects', 'demo', 'test-results', 'browser.css'), '.copy p { text-overflow: ellipsis; }');
    writeFileSync(join(root, '_projects', 'demo', 'artifacts', 'visual-fixture.css'), '.copy p { text-overflow: ellipsis; }');
    writeFileSync(join(root, '_projects', 'demo', 'target', 'site', 'index.html'), '<p class="copy">Generated documentation</p>');
    writeFileSync(join(root, '_projects', 'demo', 'assets', 'index-aBcD1234eF.css'), '.copy p { text-overflow: ellipsis; }');
    writeFileSync(join(root, '_projects', 'demo', '.agents', 'spec-fixture.css'), '.content { max-width: 48ch; }');
    writeFileSync(join(root, '_library', 'demo', 'guide.html'), '<p class="copy truncate">Texto resumido</p>\n<p class="copy truncate" data-text-layout-exception="control compacto con acceso al detalle">Ver detalle</p>\n<style>.copy p { text-overflow: ellipsis; }</style>');
    writeFileSync(join(root, '_library', 'demo', 'archive', 'old.css'), '.copy p { max-width: 20ch; }');

    const report = scanWorkspace(root);
    assert.equal(report.filesScanned, 2);
    assert.equal(report.findings.length, 3);
    assert.equal(report.exceptions.length, 1);
    assert.ok(report.scopes.some(scope => scope.path === '_projects'));
    assert.ok(report.scopes.some(scope => scope.path === '_library'));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('interpreta argumentos CLI y produce informe JSON legible', () => {
  const options = parseArguments(['--root', 'C:/workspace', '--fail-on-violations', '--json']);
  assert.deepEqual(options, { root: 'C:/workspace', failOnViolations: true, json: true, project: false });
  assert.match(formatReport({ filesScanned: 2, findings: [], exceptions: [], scopes: [] }, true), /"filesScanned": 2/);
  assert.match(formatReport({ filesScanned: 2, findings: [], exceptions: [], scopes: [] }, false), /2 archivos/);
});

test('el CLI devuelve error solo cuando se solicita y hay hallazgos', () => {
  const root = mkdtempSync(join(tmpdir(), 'text-layout-cli-'));
  try {
    mkdirSync(join(root, '_projects', 'demo'), { recursive: true });
    writeFileSync(join(root, '_projects', 'demo', 'style.css'), '.copy p { white-space: nowrap; }');
    const messages = [];
    assert.equal(runAudit(['--root', root, '--fail-on-violations', '--json'], { log: value => messages.push(value) }), 1);
    assert.equal(runAudit(['--root', root, '--json'], { log: value => messages.push(value) }), 0);
    assert.equal(messages.length, 2);
    assert.match(messages[0], /"errors": 1/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});


test('detecta límites físicos y lógicos de prosa sin rechazar la justificación', () => {
  for (const property of ['max-width', 'max-inline-size']) {
    for (const value of ['78ch', 'min(100%, 78ch)', '800px', '48rem']) {
      assert.equal(scanStylesheet(`.intro p { ${property}: ${value}; }`, 'a.css').findings[0]?.rule, 'narrow-prose-measure');
    }
  }
  assert.equal(scanStylesheet('p { text-align: justify; max-inline-size: 100%; hyphens: none; }', 'a.css').findings.length, 0);
  assert.equal(scanStylesheet('p { hyphens: auto; }', 'a.css').findings[0]?.rule, 'automatic-hyphenation');
  assert.equal(scanStylesheet('.text-column { max-width: 78ch; }', 'a.css').findings[0]?.rule, 'narrow-prose-measure');
});

test('el modo proyecto inspecciona también src y las utilidades de prosa', () => {
  assert.equal(parseArguments(['--project']).project, true);
  const root = mkdtempSync(join(tmpdir(), 'prose-project-'));
  try { mkdirSync(join(root,'src')); writeFileSync(join(root,'src','a.css'),'p{max-width:78ch}'); assert.equal(runAudit(['--root',root,'--project','--fail-on-violations'],{log:()=>{}}),1); } finally { rmSync(root,{recursive:true,force:true}); }
});

test('resuelve topes CSS guardados en variables antes de auditar la región', () => {
  const report = scanStylesheet(':root { --container-max: 76rem; } .container { max-width: var(--container-max); }', 'layout.css');
  assert.equal(report.findings[0]?.rule, 'narrow-reading-region');
  assert.equal(report.findings[0]?.value, 'var(--container-max)');
});

test('audita topes en wrappers, módulos y cuadrículas de contenido', () => {
  const report = scanStylesheet('.wrap { max-width: 1200px; } .module-page > .block { max-width: 78ch; } .content-grid { max-width: 72rem; }', 'regions.css');
  assert.deepEqual(report.findings.map(item => item.rule), ['narrow-reading-region', 'narrow-reading-region', 'narrow-reading-region']);
});

test('detecta topes de ancho en utilidades de marcado para contenedores y prosa', () => {
  const root = mkdtempSync(join(tmpdir(), 'prose-utility-audit-'));
  try {
    mkdirSync(join(root, '_projects', 'demo'), { recursive: true });
    writeFileSync(join(root, '_projects', 'demo', 'index.html'), '<main class="container max-w-7xl"><p class="copy max-w-prose">Texto extenso de lectura.</p></main>');
    const report = scanWorkspace(root, ['_projects']);
    assert.ok(report.findings.some(item => item.rule === 'narrow-reading-region' && item.selector.includes('.max-w-7xl')));
    assert.ok(report.findings.some(item => item.rule === 'narrow-prose-measure' && item.selector.includes('.max-w-prose')));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('audita texto truncado en spans sin tratar sus clases de bloque como contenedores', () => {
  const root = mkdtempSync(join(tmpdir(), 'prose-span-audit-'));
  try {
    mkdirSync(join(root, '_projects', 'demo'), { recursive: true });
    writeFileSync(join(root, '_projects', 'demo', 'index.html'), '<span class="block truncate">Descripción completa</span><span class="truncate" aria-hidden="true">▶</span>');
    const report = scanWorkspace(root, ['_projects']);
    assert.deepEqual(report.findings.map(item => item.rule), ['content-truncation']);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('detecta truncamiento dentro de clases JSX con expresiones dinámicas', () => {
  const root = mkdtempSync(join(tmpdir(), 'prose-jsx-class-audit-'));
  try {
    mkdirSync(join(root, '_projects', 'demo'), { recursive: true });
    writeFileSync(join(root, '_projects', 'demo', 'index.html'), '<p className={`text-xs leading-relaxed line-clamp-2 ${!item.read ? "text-slate-700" : "text-slate-500"}`}>Descripción completa</p>');
    const report = scanWorkspace(root, ['_projects']);
    assert.deepEqual(report.findings.map(item => item.rule), ['content-line-clamp']);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('no confunde utilidades tipográficas, tablas ni ventanas emergentes con regiones de lectura', () => {
  assert.equal(isReadingRegionSelector('td .text-foreground .whitespace-nowrap'), false);
  assert.equal(isReadingRegionSelector('DialogContent .max-w-md .p-6'), true);
  assert.deepEqual(scanStylesheet('.dialog-content { max-width: 36rem; } .popover-content { max-width: 48rem; } .decoder-container { max-width: 50rem; }', 'overlay.css').findings, []);
  assert.deepEqual(scanStylesheet('.device-inspection-shell { max-width: 56rem; }', 'overlay.css').findings, []);
  assert.deepEqual(scanStylesheet('.modal-content { max-height: 90vh; overflow: hidden; }', 'overlay.css').findings.map(item => item.rule), ['content-clipping']);
  assert.equal(isReadingRegionSelector('main .max-w-7xl'), true);
  assert.equal(isReadingRegionSelector('TabsList .grid .max-w-2xl'), false);
  assert.equal(isReadingRegionSelector('.nav-grid'), false);
  assert.equal(isReadingRegionSelector('span .block .line-clamp-1'), false);
  assert.deepEqual(scanStylesheet('.nav-grid { max-width: 100vw !important; }', 'navigation.css').findings, []);
  assert.deepEqual(scanStylesheet('.fixed.pagination-toolbar { max-width: 95vw; }', 'fixed-controls.css').findings, []);
});
