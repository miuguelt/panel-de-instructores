import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('la plantilla aplica el umbral al contenedor y conserva palabras y última línea', () => {
  const css = readFileSync(new URL('../../templates/prose-layout.css', import.meta.url), 'utf8');
  assert.doesNotMatch(css, /container-type/);
  const runtime = readFileSync(new URL('../../templates/prose-layout.js', import.meta.url), 'utf8');
  assert.match(runtime, /width >= 40 \* rem/);
  assert.match(css, /text-align-last: start/);
  assert.match(css, /hyphens: none/);
  assert.match(css, /inline-size: 100%/);
  assert.doesNotMatch(css, /!important|78ch/);
});

test('la migración retira límites de prosa y conserva títulos, código y controles', async () => {
  const { migrateCss } = await import('../text-layout-migration.mjs');
  const css = '.hero h1 {max-width: 20ch;text-align:center} .intro p {--text-align-reading:start;max-width:78ch;text-align:start;hyphens:auto} pre code {max-width:70ch} button {text-align:center}';
  const result = migrateCss(css);
  assert.match(result, /h1 \{max-width: 20ch;text-align:center\}/);
  assert.match(result, /max-width:100%/);
  assert.match(result, /text-align:var\(--text-align-reading, start\)/);
  assert.match(result, /--text-align-reading:start/);
  assert.match(result, /hyphens:none/);
  assert.match(result, /pre code \{max-width:70ch\}/);
  assert.equal(migrateCss(result), result);
  assert.equal(migrateCss('button{width:40px}'), 'button{width:40px}');
  const multiple = migrateCss('p{max-width:78ch} .intro{max-inline-size:400px}');
  assert.equal((multiple.match(/100%/g) || []).length >= 2, true);
  assert.match(migrateCss('.reading-layout{max-width:1420px} p{--text-align-reading:start;text-align:start}'), /\.reading-layout\{max-width:100%\}/);
});

test('la migración conserva estilos locales después del contrato previo', async () => {
  const { migrateCss } = await import('../text-layout-migration.mjs');
  const css = 'p{max-width:78ch}\n/* devbrain-prose-contract:start */\ncontrato anterior\n/* devbrain-prose-contract:end */\n.document-header{border-radius:14px}\n';
  const migrated = migrateCss(css);
  assert.match(migrated, /\.document-header\{border-radius:14px\}/);
  assert.ok(migrated.indexOf('devbrain-prose-contract:end') < migrated.indexOf('.document-header'));
  assert.match(migrated, /p\{max-width:100%\}/);
});

test('clasifica superficies de lectura según el renderizador real', async () => {
  const { classifySurface } = await import('../text-layout-migration.mjs');
  assert.equal(classifySurface('html', '{% extends "base.html" %}'), 'servidor');
  assert.equal(classifySurface('html', '<script type="module" src="/main.js"></script>'), 'aplicación');
  assert.equal(classifySurface('tsx', 'return <p style={{maxWidth:"78ch"}} />'), 'aplicación');
  assert.equal(classifySurface('css', 'p { color: black; }'), 'estático');
  assert.equal(classifySurface('pdf', ''), 'renderizador');
  assert.equal(classifySurface('md', '# Guía'), 'documentación');
});

test('la migración conserva los estilos de no-script cuando la página ya conecta el contrato compartido', async () => {
  const { migrateFile } = await import('../text-layout-migration.mjs');
  const root = mkdtempSync(join(tmpdir(), 'prose-noscript-'));
  try {
    const page = join(root, 'index.html');
    writeFileSync(page, '<!doctype html><html><head><link rel="stylesheet" href="devbrain-prose.css" data-devbrain-prose></head><body><noscript><style>.module-page{display:block}</style><p>Lectura sin JavaScript.</p></noscript></body></html>');
    assert.equal(migrateFile(page, false), false);
    assert.equal(migrateFile(page, true), false);
    assert.doesNotMatch(readFileSync(page, 'utf8'), /devbrain-prose-contract:start/);
    const fallback = join(root, 'fallback.html');
    writeFileSync(fallback, '<!doctype html><html><body><noscript><style>p{max-width:78ch}</style><p>Lectura de respaldo.</p></noscript></body></html>');
    assert.equal(migrateFile(fallback, false), true);
    assert.equal(migrateFile(fallback, true), true);
    assert.match(readFileSync(fallback, 'utf8'), /max-width:100%/);
  } finally { rmSync(root, { recursive:true, force:true }); }
});

test('la migración retira límites de las regiones de lectura y de sus columnas', async () => {
  const { migrateCss } = await import('../text-layout-migration.mjs');
  const migrated = migrateCss('.timeline{max-width:72ch}.module-container{max-width:min(1600px,90vw)}.module-explanation{display:grid;grid-template-columns:minmax(0,78ch) minmax(16rem,1fr)}');
  assert.match(migrated, /\.timeline\{max-width:100%\}/);
  assert.match(migrated, /\.module-container\{max-width:100%\}/);
  assert.match(migrated, /grid-template-columns:minmax\(0,1fr\) minmax\(16rem,1fr\)/);
  assert.doesNotMatch(migrated.split('devbrain-prose-contract:start')[0], /78ch/);
});

test('inventa un registro de superficies sin omitir rutas anidadas ni plantillas', async () => {
  const { inventory, migrateFile, runMigration } = await import('../text-layout-migration.mjs');
  const root = mkdtempSync(join(tmpdir(), 'prose-inventory-'));
  try {
    for (const dir of ['_projects/demo/nested/templates', '_projects/demo/nested/components', '_projects/demo/node_modules', '_library/guide/assets']) mkdirSync(join(root, dir), { recursive:true });
    const html = join(root, '_projects/demo/nested/templates/detail.html');
    writeFileSync(html, '{% extends "base.html" %}<p>Detalle</p>');
    const component = join(root, '_projects/demo/nested/components/Panel.tsx');
    writeFileSync(component, 'export function Panel(){return <p style={{maxWidth:"78ch"}}>Texto</p>}');
    writeFileSync(join(root, '_projects/demo/node_modules/index.html'), '<p>Dependencia</p>');
    writeFileSync(join(root, '_library/guide/lesson.html'), '<!doctype html><html><style>p{max-width:78ch}</style><p>Guía</p></html>');
    writeFileSync(join(root, '_library/guide/report.docx'), 'documento');
    const css = join(root, '_library/guide/styles.css');
    writeFileSync(css, 'p{max-width:78ch}');
    const builtCss = join(root, '_library/guide/assets/index-D5ZykAW2.css');
    writeFileSync(builtCss, 'p{max-width:78ch}');
    writeFileSync(join(root, '_library/guide/devbrain-prose.css'), readFileSync(new URL('../../templates/prose-layout.css', import.meta.url), 'utf8'));
    const rows = inventory(root);
    assert.equal(rows.length, 6);
    assert.equal(rows.find(row=>row.path.endsWith('detail.html')).method, 'servidor');
    assert.equal(rows.find(row=>row.path.endsWith('Panel.tsx')).method, 'aplicación');
    assert.equal(rows.find(row=>row.path.endsWith('report.docx')).status, 'pendiente');
    assert.equal(rows.some(row=>row.path.includes('node_modules')), false);
    assert.equal(rows.some(row=>row.path.endsWith('assets/index-D5ZykAW2.css')), false, 'los CSS compilados con hash se actualizan desde su fuente oficial');
    assert.equal(migrateFile(css, false), true);
    assert.equal(readFileSync(css,'utf8'), 'p{max-width:78ch}');
    assert.equal(migrateFile(css, true), true);
    assert.match(readFileSync(css,'utf8'), /Contrato 7\.4/);
    assert.equal(migrateFile(css, true), false);
    const page = join(root, '_library/guide/lesson.html');
    assert.equal(migrateFile(page, true), true);
    assert.match(readFileSync(page, 'utf8'), /text-align-last/);
    assert.equal(migrateFile(html, true), false);
    writeFileSync(html, '<p style="max-width:480px;text-align:left">Detalle</p>');
    assert.equal(migrateFile(html,true), true);
    assert.match(readFileSync(html,'utf8'), /max-width:100%/);
    writeFileSync(css, 'p{max-width:78ch}');
    assert.deepEqual(runMigration(root,false).changed, ['_library/guide/styles.css']);
    assert.equal(runMigration(root,true).changed.length, 1);
    assert.equal(readFileSync(join(root,'output/text-layout/originals/_library/guide/styles.css'),'utf8'), 'p{max-width:78ch}');
    writeFileSync(css, 'p{max-width:78ch}');
    assert.equal(runMigration(root,true).changed.length, 1);
  } finally { rmSync(root,{recursive:true,force:true}); }
});
