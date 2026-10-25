import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

test('instala contrato, pruebas y CI sin reemplazar la aplicación', async () => {
  const { installProject, discoverManagedFiles } = await import('../text-layout-install.mjs');
  const root = mkdtempSync(join(tmpdir(),'prose-install-'));
  try {
    for (const type of ['static','python','node','fullstack','wails','powershell']) {
      const project = join(root,type); mkdirSync(project);
      const entry = type === 'python' ? 'app/interfaces/http/templates/base.html' : type === 'fullstack' || type === 'wails' ? 'frontend/index.html' : 'index.html';
      if (type !== 'powershell') {
        mkdirSync(join(project,entry,'..'),{recursive:true});
        writeFileSync(join(project,entry),'<!doctype html><html><head><title>Aplicación</title></head><body><p>Contenido original</p></body></html>');
      }
      const report = installProject(project,type);
      assert.equal(report.applicable,type !== 'powershell');
      if (report.applicable) {
        assert.equal(existsSync(join(project,'tools/text-layout/scripts/text-layout-audit.mjs')),true);
        const workflow = readFileSync(join(project,'.github/workflows/text-layout.yml'),'utf8');
        for (const file of ['text-layout-browser-audit.cjs','text-layout-browser-discovery.cjs','text-layout-browser-probes.cjs','text-layout-browser-engine.cjs','text-layout-browser-runner.cjs']) {
          const installedTool = join(project,'tools/text-layout/scripts',file);
          assert.equal(existsSync(installedTool),true,`${file} debe instalarse para auditar proyectos sin conexión`);
          assert.ok(readFileSync(installedTool,'utf8').split(/\r?\n/).length <= 400,`${file} debe respetar el límite de modularidad`);
          assert.ok(workflow.includes(`--test-coverage-include="**/${file}"`),`${file} debe tener cobertura de funciones en la CI`);
        }
        assert.match(readFileSync(join(project,entry),'utf8'), /Contenido original/);
        assert.match(readFileSync(join(project,entry),'utf8'), /devbrain-prose/);
        assert.match(workflow, /test-coverage-functions=100/);
        assert.equal(installProject(project,type).entries.length,1);
        assert.equal((readFileSync(join(project,entry),'utf8').match(/data-devbrain-prose(?=[ >])/g)||[]).length,1);
      }
    }
    const empty = join(root,'empty'); mkdirSync(empty);
    assert.equal(installProject(empty,'static').entries.length,1);
    assert.match(readFileSync(join(empty,'index.html'),'utf8'),/stylesheet/);
    const emptyPowershell = join(root,'empty-powershell'); mkdirSync(emptyPowershell);
    const emptyPowershellReport = installProject(emptyPowershell,'powershell',false);
    assert.equal(emptyPowershellReport.applicable,false);
    assert.equal(emptyPowershellReport.reason,'Sin superficie de lectura.');
    assert.equal(existsSync(join(emptyPowershell,'tools/text-layout/scripts/text-layout-audit.mjs')),false);
    const powershellUi = join(root,'powershell-ui'); mkdirSync(powershellUi);
    writeFileSync(join(powershellUi,'index.html'),'<!doctype html><html><head><title>Interfaz</title></head><body><p>Lectura</p></body></html>');
    const powershellUiReport = installProject(powershellUi,'powershell',false);
    assert.equal(powershellUiReport.applicable,true);
    assert.deepEqual(powershellUiReport.entries,['index.html']);
    assert.equal(existsSync(join(powershellUi,'tools/text-layout/scripts/text-layout-audit.mjs')),true);
    assert.match(readFileSync(join(powershellUi,'index.html'),'utf8'),/data-devbrain-prose-runtime/);
    const existing = join(root,'existing'); mkdirSync(existing);
    mkdirSync(join(existing,'.github/workflows'),{recursive:true});
    mkdirSync(join(existing,'guide'),{recursive:true});
    writeFileSync(join(existing,'index.html'),'<!doctype html><html><head><title>Inicio</title></head><body><p>Inicio</p></body></html>');
    writeFileSync(join(existing,'guide','lectura.html'),'<!doctype html><html><head><title>Lectura</title></head><body><p>Guía independiente</p></body></html>');
    writeFileSync(join(existing,'.github/workflows/text-layout.yml'),'name: flujo local');
    const installed = installProject(existing,'node',false);
    assert.deepEqual(installed.entries.sort(),['guide/lectura.html','index.html']);
    assert.match(readFileSync(join(existing,'guide','lectura.html'),'utf8'),/data-devbrain-prose-runtime/);
    assert.equal(readFileSync(join(existing,'.github/workflows/text-layout.yml'),'utf8'),'name: flujo local');
    assert.equal(existsSync(join(existing,'.github/workflows/devbrain-text-layout.yml')),true);

    const headless = join(root,'headless-html'); mkdirSync(headless);
    writeFileSync(join(headless,'LEEME.html'),'<!doctype html><html lang="es-CO"><meta charset="utf-8"><title>Lectura</title><style>p{max-width:78ch}</style><main><p>Contenido de lectura</p></main></html>');
    const headlessReport = installProject(headless,'static',false);
    assert.deepEqual(headlessReport.entries,['LEEME.html']);
    const headlessHtml = readFileSync(join(headless,'LEEME.html'),'utf8');
    assert.match(headlessHtml,/<head>/);
    assert.match(headlessHtml,/<\/head>/);
    assert.match(headlessHtml,/data-devbrain-prose-runtime/);

    const next = join(root,'next-app'); mkdirSync(join(next,'src/app'),{recursive:true});
    mkdirSync(join(next,'public'),{recursive:true});
    writeFileSync(join(next,'package.json'),JSON.stringify({dependencies:{next:'16.0.0',react:'19.0.0'}}));
    writeFileSync(join(next,'src/app/layout.tsx'),"import './globals.css';\nexport default function RootLayout({ children }) { return (\n  <html><body>\n    {children}\n  </body></html>\n); }\n");
    mkdirSync(join(next,'app'),{recursive:true});
    writeFileSync(join(next,'app/layout.jsx'),"export default function NestedRootLayout({ children }) { return <html><body>{children}</body></html>; }\n");
    const planned = discoverManagedFiles(next);
    assert.deepEqual(planned.nextLayouts.map(item=>item.layout),['app/layout.jsx','src/app/layout.tsx']);
    assert.ok(planned.files.includes('src/app/devbrain-prose.css'));
    assert.ok(planned.files.includes('public/devbrain-prose.js'));
    const nextReport = installProject(next,'node',false);
    assert.deepEqual(nextReport.nextLayouts,['app/layout.jsx','src/app/layout.tsx']);
    assert.match(readFileSync(join(next,'src/app/layout.tsx'),'utf8'),/\.\/devbrain-prose\.css/);
    assert.match(readFileSync(join(next,'src/app/layout.tsx'),'utf8'),/from 'next\/script'/);
    assert.match(readFileSync(join(next,'src/app/layout.tsx'),'utf8'),/data-devbrain-prose-runtime/);
    assert.match(readFileSync(join(next,'src/app/layout.tsx'),'utf8'),/^    <Script.*data-devbrain-prose-runtime/m);
    assert.equal(existsSync(join(next,'src/app/devbrain-prose.css')),true);
    assert.equal(existsSync(join(next,'public/devbrain-prose.js')),true);
    assert.match(readFileSync(join(next,'app/layout.jsx'),'utf8'),/data-devbrain-prose-runtime/);
    assert.equal(installProject(next,'node',false).nextLayouts.length,2);

    const vite = join(root,'vite-app');
    mkdirSync(join(vite,'frontend/public'),{recursive:true});
    writeFileSync(join(vite,'frontend/package.json'),JSON.stringify({devDependencies:{vite:'6.0.0'}}));
    writeFileSync(join(vite,'frontend/index.html'),'<!doctype html><html><head><title>Vite</title></head><body><main>Lectura</main></body></html>');
    const viteReport = installProject(vite,'fullstack',false);
    const viteHtml = readFileSync(join(vite,'frontend/index.html'),'utf8');
    assert.deepEqual(viteReport.entries,['frontend/index.html']);
    assert.match(viteHtml,/href="\/devbrain-prose\.css" data-devbrain-prose/);
    assert.match(viteHtml,/src="\/devbrain-prose\.js" data-devbrain-prose-runtime/);
    assert.equal(existsSync(join(vite,'frontend/public/devbrain-prose.css')),true);
    assert.equal(existsSync(join(vite,'frontend/public/devbrain-prose.js')),true);
    const viteManaged = discoverManagedFiles(vite);
    assert.ok(viteManaged.files.includes('frontend/index.html'));
    assert.ok(viteManaged.files.includes('frontend/public/devbrain-prose.css'));
    assert.ok(viteManaged.files.includes('frontend/public/devbrain-prose.js'));

    const malformedVite = join(root,'malformed-vite');
    mkdirSync(join(malformedVite,'frontend'),{recursive:true});
    writeFileSync(join(malformedVite,'frontend/index.html'),'<!doctype html><html><head><title>Vite parcial</title></head><body><main>Lectura</main></body></html>');
    writeFileSync(join(malformedVite,'package.json'),'{"dependencies":');
    const malformedPlan = discoverManagedFiles(malformedVite);
    assert.ok(malformedPlan.files.includes('frontend/devbrain-prose.css'));
    assert.ok(malformedPlan.files.includes('frontend/devbrain-prose.js'));

    const cli = fileURLToPath(new URL('../text-layout-install.mjs',import.meta.url));
    const missingProject = spawnSync(process.execPath,[cli],{encoding:'utf8'});
    assert.notEqual(missingProject.status,0);
    assert.match(missingProject.stderr,/Indique la ruta del proyecto/);
    const cliInventory = spawnSync(process.execPath,[cli,next,'--discover-managed-json'],{encoding:'utf8'});
    assert.equal(cliInventory.status,0);
    assert.deepEqual(JSON.parse(cliInventory.stdout).nextLayouts.map(item=>item.layout),['app/layout.jsx','src/app/layout.tsx']);

    assert.throws(()=>installProject(root,'unsupported'),/Tipo/);
  } finally { rmSync(root,{recursive:true,force:true}); }
});
